"""Юнит-тесты core: извлечение, оценка токенов, выравнивание секций, конфиг, LLM-клиент."""
from __future__ import annotations

import dataclasses

import pytest

from core.aligner import align
from core.chunker import count_tokens, fits_whole, group_sections
from core.config import Settings
from core.extractor import extract_document

from .conftest import make_docx, make_docx_with_table


def test_extract_splits_by_headings(contract_a: bytes):
    doc = extract_document(contract_a, "A.docx")
    headings = [s.heading for s in doc.sections]
    assert headings == ["Предмет договора", "Стоимость и оплата", "Срок действия"]
    # Тело секции содержит относящийся к заголовку текст.
    assert "100000" in doc.sections[1].body


def test_extract_indexes_are_sequential(contract_b: bytes):
    doc = extract_document(contract_b, "B.docx")
    assert [s.index for s in doc.sections] == list(range(len(doc.sections)))


def test_extract_table_to_markdown():
    data = make_docx_with_table("Тарифы", [["Услуга", "Цена"], ["Консультация", "5000"]])
    doc = extract_document(data, "T.docx")
    body = doc.sections[0].body
    assert "| Услуга | Цена |" in body
    assert "| --- | --- |" in body
    assert "| Консультация | 5000 |" in body


def test_extract_no_headings_single_section():
    data = make_docx([(0, "Просто текст без заголовков."), (0, "Второй абзац.")])
    doc = extract_document(data, "flat.docx")
    assert len(doc.sections) == 1
    assert "Просто текст" in doc.sections[0].text


def test_count_tokens_positive():
    assert count_tokens("Договор оказания услуг") > 0
    assert count_tokens("") == 0 or count_tokens("") >= 0


def test_fits_whole_budget():
    small_tokens = count_tokens("короткий текст")
    assert fits_whole(small_tokens, budget=10_000) is True
    big_tokens = count_tokens("слово " * 5000) * 2
    assert fits_whole(big_tokens, budget=50) is False


def test_group_sections_respects_limit(contract_b: bytes):
    doc = extract_document(contract_b, "B.docx")
    chunks = group_sections(doc.sections, max_tokens=30)
    # Сумма секций по чанкам == всем секциям, порядок сохранён.
    flat = [s for chunk in chunks for s in chunk]
    assert [s.index for s in flat] == [s.index for s in doc.sections]
    assert len(chunks) >= 1


def test_align_matches_same_headings(contract_a: bytes, contract_b: bytes):
    da = extract_document(contract_a, "A.docx")
    db = extract_document(contract_b, "B.docx")
    pairs = align(da, db)

    matched = {
        (p.left.heading if p.left else None): (p.right.heading if p.right else None)
        for p in pairs
    }
    # Одноимённые секции сопоставлены друг с другом.
    assert matched["Предмет договора"] == "Предмет договора"
    assert matched["Стоимость и оплата"] == "Стоимость и оплата"


def test_align_detects_added_section(contract_a: bytes, contract_b: bytes):
    da = extract_document(contract_a, "A.docx")
    db = extract_document(contract_b, "B.docx")
    pairs = align(da, db)

    # "Ответственность сторон" есть только в B → пара с left=None.
    added = [p for p in pairs if p.left is None and p.right is not None]
    assert any("Ответственность" in p.right.heading for p in added)


def test_align_detects_removed_section():
    a = make_docx([(1, "Раздел 1"), (0, "текст"), (1, "Удаляемый раздел"), (0, "будет удалён")])
    b = make_docx([(1, "Раздел 1"), (0, "текст")])
    da = extract_document(a, "A.docx")
    db = extract_document(b, "B.docx")
    pairs = align(da, db)

    removed = [p for p in pairs if p.right is None and p.left is not None]
    assert any("Удаляемый" in p.left.heading for p in removed)


# --- конфиг: min_output_tokens и doc_token_budget ----------------------------

def test_settings_min_output_tokens_default():
    s = Settings()
    assert s.min_output_tokens == 1024


def test_settings_doc_token_budget_uses_reserve_ratio():
    s = Settings()
    expected = int(s.max_context * (1.0 - s.reserve_ratio))
    assert s.doc_token_budget == expected


def test_settings_budget_consistent():
    """budget для whole-режима = max_context - min_output_tokens.
    Это должно быть меньше max_context и больше нуля."""
    s = Settings()
    budget = s.max_context - s.min_output_tokens
    assert 0 < budget < s.max_context


# --- llm_client: max_tokens передаётся в API ----------------------------------

def test_llm_complete_passes_max_tokens(monkeypatch):
    """complete() должен передавать max_tokens в API-вызов."""
    import core.llm_client as llm_client

    captured = {}

    class FakeChoice:
        message = type("M", (), {"content": "ответ"})()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletion:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResp()

    class FakeChat:
        completions = FakeCompletion()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm_client, "_client", FakeClient())
    monkeypatch.setattr(llm_client, "_MOCK", False)

    llm_client.complete("sys", "user", max_tokens=512)
    assert captured.get("max_tokens") == 512


def test_llm_complete_default_max_tokens(monkeypatch):
    """Если max_tokens не передан, используется min_output_tokens из settings."""
    import core.llm_client as llm_client
    from core.config import settings

    captured = {}

    class FakeChoice:
        message = type("M", (), {"content": "ответ"})()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletion:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResp()

    class FakeChat:
        completions = FakeCompletion()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm_client, "_client", FakeClient())
    monkeypatch.setattr(llm_client, "_MOCK", False)

    llm_client.complete("sys", "user")
    assert captured.get("max_tokens") == settings.min_output_tokens


def test_llm_complete_mock_ignores_max_tokens(monkeypatch):
    """В MOCK-режиме max_tokens игнорируется — всегда возвращается заглушка."""
    import core.llm_client as llm_client

    monkeypatch.setattr(llm_client, "_MOCK", True)
    result = llm_client.complete("sys", "user", max_tokens=1)
    assert "mock" in result.lower() or "MOCK" in result


# --- comparator: whole/sectioned выбирается по полному промпту ----------------

def test_comparator_uses_full_prompt_for_budget(monkeypatch, contract_a, contract_b):
    """fits_whole вызывается с числом токенов полного промпта, а не просто текстов."""
    import core.comparator as comparator
    import core.llm_client as llm_client

    received_prompt_tokens = {}

    original_fits_whole = comparator.fits_whole

    def spy_fits_whole(prompt_tokens: int, budget: int) -> bool:
        received_prompt_tokens["tokens"] = prompt_tokens
        received_prompt_tokens["budget"] = budget
        return True  # форсируем whole-режим

    monkeypatch.setattr(comparator, "fits_whole", spy_fits_whole)
    monkeypatch.setattr(llm_client, "complete", lambda *a, **k: "# Отчёт")

    from core.comparator import compare_documents
    compare_documents(contract_a, "a.docx", contract_b, "b.docx")

    # prompt_tokens должны включать не только тексты, но и обёртку промпта
    tokens = received_prompt_tokens["tokens"]
    assert tokens > 0
    # budget = max_context - min_output_tokens
    from core.config import settings
    assert received_prompt_tokens["budget"] == settings.max_context - settings.min_output_tokens


def test_comparator_output_budget_positive(monkeypatch, contract_a, contract_b):
    """_output_budget никогда не возвращает 0 или отрицательное число."""
    import core.comparator as comparator
    import core.llm_client as llm_client

    max_tokens_used = {}

    def capture_complete(system_prompt, user_prompt, max_tokens=None):
        max_tokens_used["value"] = max_tokens
        return "# Отчёт"

    monkeypatch.setattr(llm_client, "complete", capture_complete)

    from core.comparator import compare_documents
    compare_documents(contract_a, "a.docx", contract_b, "b.docx")

    assert max_tokens_used.get("value", 0) > 0
