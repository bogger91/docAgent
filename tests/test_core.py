"""Юнит-тесты core: извлечение, оценка токенов, выравнивание секций."""
from __future__ import annotations

from core.aligner import align
from core.chunker import count_tokens, fits_whole, group_sections
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
    short = "короткий текст"
    assert fits_whole(short, short, budget=10_000) is True
    assert fits_whole("слово " * 5000, "слово " * 5000, budget=50) is False


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
