"""E2E-тесты HTTP-эндпоинтов FastAPI.

LLM-клиент замокан, чтобы тесты не требовали запущенного Qwen3. Проверяется
полный путь: загрузка .docx → /api/compare → отчёт, в обоих режимах сравнения.
"""
from __future__ import annotations

import core.llm_client as llm_client
from core.config import settings
from fastapi.testclient import TestClient

import server

from .conftest import make_docx, make_docx_with_table


client = TestClient(server.app)


# --- /api/health --------------------------------------------------------------

def test_health_ok(monkeypatch):
    monkeypatch.setattr(server, "health_check", lambda: (True, "OK: qwen3 @ local"))
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["model"] == settings.model


def test_health_reports_failure(monkeypatch):
    monkeypatch.setattr(server, "health_check", lambda: (False, "Нет связи"))
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is False


# --- index --------------------------------------------------------------------

def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "docAgent" in r.text


# --- /api/compare: режим whole ------------------------------------------------

def test_compare_whole_mode(monkeypatch, contract_a, contract_b):
    """Маленькие документы влезают целиком → один запрос, mode=whole."""
    calls = []

    def fake_complete(system_prompt: str, user_prompt: str) -> str:
        calls.append((system_prompt, user_prompt))
        # Проверяем, что в запрос попали оба документа и фокус пользователя.
        assert "ВЕРСИЯ A" in user_prompt and "ВЕРСИЯ B" in user_prompt
        assert "штраф" in user_prompt.lower()
        return "# Отчёт\nИзменилась стоимость и срок оплаты."

    monkeypatch.setattr(llm_client, "complete", fake_complete)

    r = client.post(
        "/api/compare",
        files={
            "file_a": ("a.docx", contract_a, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "file_b": ("b.docx", contract_b, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        },
        data={"focus": "обрати внимание на штраф и сроки"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "whole"
    assert body["sections_compared"] == 1
    assert "стоимость" in body["report_markdown"].lower()
    assert body["tokens_a"] > 0 and body["tokens_b"] > 0
    assert len(calls) == 1  # один запрос к модели


# --- /api/compare: режим sectioned --------------------------------------------

def test_compare_sectioned_mode(monkeypatch, contract_a, contract_b):
    """При недостатке бюджета контекста включается посекционное сравнение."""
    # settings — frozen dataclass, поэтому вместо правки бюджета подменяем
    # решение «влезает ли целиком» в неймспейсе comparator на False.
    import core.comparator as comparator

    monkeypatch.setattr(comparator, "fits_whole", lambda *a, **k: False)

    seen_titles = []

    def fake_complete(system_prompt: str, user_prompt: str) -> str:
        # Сводный запрос содержит маркер заметок; посекционные — заголовок раздела.
        if "посекционные заметки" in user_prompt.lower() or "заметк" in system_prompt.lower():
            return "# Итоговый отчёт\nКлючевые правки: стоимость, сроки, новый раздел."
        seen_titles.append(user_prompt)
        return "Изменение в этом разделе."

    monkeypatch.setattr(llm_client, "complete", fake_complete)

    r = client.post(
        "/api/compare",
        files={
            "file_a": ("a.docx", contract_a, "application/octet-stream"),
            "file_b": ("b.docx", contract_b, "application/octet-stream"),
        },
        data={"focus": ""},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "sectioned"
    assert body["sections_compared"] >= 3  # несколько секций сравнивалось
    assert "Итоговый отчёт" in body["report_markdown"]


# --- /api/compare: документы с таблицами --------------------------------------

def test_compare_passes_table_content_to_model(monkeypatch):
    """Реальный .docx с таблицей проходит полный путь, и содержимое таблицы
    (в виде markdown) доходит до промпта модели."""
    doc_a = make_docx_with_table(
        "Тарифы",
        [["Услуга", "Цена"], ["Консультация", "5000"], ["Аудит", "20000"]],
    )
    doc_b = make_docx_with_table(
        "Тарифы",
        [["Услуга", "Цена"], ["Консультация", "7000"], ["Аудит", "20000"]],
    )

    captured = {}

    def fake_complete(system_prompt: str, user_prompt: str) -> str:
        captured["prompt"] = user_prompt
        return "# Отчёт\nЦена консультации выросла с 5000 до 7000."

    monkeypatch.setattr(llm_client, "complete", fake_complete)

    r = client.post(
        "/api/compare",
        files={
            "file_a": ("tariffs_a.docx", doc_a, "application/octet-stream"),
            "file_b": ("tariffs_b.docx", doc_b, "application/octet-stream"),
        },
        data={"focus": "сравни цены в таблице"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "whole"

    # Таблица извлечена как markdown и попала в промпт обеих версий.
    prompt = captured["prompt"]
    assert "| Услуга | Цена |" in prompt
    assert "| --- | --- |" in prompt
    assert "| Консультация | 5000 |" in prompt  # из версии A
    assert "| Консультация | 7000 |" in prompt  # из версии B
    assert "7000" in body["report_markdown"]


# --- валидация входных данных -------------------------------------------------

def test_reject_non_docx(monkeypatch, contract_a):
    r = client.post(
        "/api/compare",
        files={
            "file_a": ("a.txt", b"hello", "text/plain"),
            "file_b": ("b.docx", contract_a, "application/octet-stream"),
        },
    )
    assert r.status_code == 400
    assert ".docx" in r.json()["detail"]


def test_reject_empty_file(contract_a):
    r = client.post(
        "/api/compare",
        files={
            "file_a": ("a.docx", b"", "application/octet-stream"),
            "file_b": ("b.docx", contract_a, "application/octet-stream"),
        },
    )
    assert r.status_code == 400


def test_compare_surfaces_llm_error(monkeypatch, contract_a, contract_b):
    def boom(*_a, **_k):
        raise RuntimeError("модель недоступна")

    monkeypatch.setattr(llm_client, "complete", boom)

    r = client.post(
        "/api/compare",
        files={
            "file_a": ("a.docx", contract_a, "application/octet-stream"),
            "file_b": ("b.docx", contract_b, "application/octet-stream"),
        },
    )
    assert r.status_code == 500
    assert "модель недоступна" in r.json()["detail"]


# --- DoS-лимиты ---------------------------------------------------------------

def test_reject_oversized_file(monkeypatch, contract_a):
    """Файл, чей заявленный size превышает лимит, отвергается до обработки."""
    monkeypatch.setattr(server, "MAX_FILE_BYTES", 1024)  # 1 КБ для теста

    big = b"PK" + b"\x00" * 5000  # «большой» файл (>1 КБ)
    r = client.post(
        "/api/compare",
        files={
            "file_a": ("big.docx", big, "application/octet-stream"),
            "file_b": ("b.docx", contract_a, "application/octet-stream"),
        },
    )
    assert r.status_code == 400
    assert "больше" in r.json()["detail"]


def test_section_pairs_limit(monkeypatch, contract_a, contract_b):
    """При превышении MAX_SECTION_PAIRS режим sectioned отдаёт понятную ошибку,
    а не уходит в тысячи запросов к LLM."""
    import dataclasses

    import core.comparator as comparator
    from core.config import settings

    monkeypatch.setattr(comparator, "fits_whole", lambda *a, **k: False)
    # settings — frozen dataclass: подменяем его в неймспейсе comparator копией
    # с урезанным лимитом (replace создаёт новый экземпляр, не трогая оригинал).
    monkeypatch.setattr(
        comparator, "settings", dataclasses.replace(settings, max_section_pairs=1)
    )

    # complete не должен вызываться вовсе — лимит срабатывает до запросов.
    def must_not_call(*_a, **_k):
        raise AssertionError("LLM не должен вызываться при превышении лимита секций")

    monkeypatch.setattr(llm_client, "complete", must_not_call)

    r = client.post(
        "/api/compare",
        files={
            "file_a": ("a.docx", contract_a, "application/octet-stream"),
            "file_b": ("b.docx", contract_b, "application/octet-stream"),
        },
    )
    assert r.status_code == 500
    assert "Слишком много секций" in r.json()["detail"]
