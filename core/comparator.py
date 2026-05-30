"""Оркестрация сравнения: выбор режима и сборка итогового отчёта."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import llm_client, prompts
from .aligner import align
from .chunker import count_tokens, fits_whole
from .config import settings
from .extractor import extract_document
from .models import Document

# Колбэк прогресса: (доля 0..1, текстовая метка). Используется UI для спиннера/лога.
ProgressCb = Callable[[float, str], None]


@dataclass
class ComparisonResult:
    report_markdown: str
    mode: str               # "whole" | "sectioned"
    doc_a_name: str
    doc_b_name: str
    tokens_a: int
    tokens_b: int
    sections_compared: int


def _noop(_frac: float, _msg: str) -> None:
    pass


def compare_documents(
    file_a: bytes,
    name_a: str,
    file_b: bytes,
    name_b: str,
    user_focus: str = "",
    progress: ProgressCb | None = None,
) -> ComparisonResult:
    """Главная точка входа. Извлекает документы, выбирает режим, возвращает отчёт."""
    progress = progress or _noop

    progress(0.05, "Извлечение текста из документов…")
    doc_a = extract_document(file_a, name_a)
    doc_b = extract_document(file_b, name_b)

    text_a = doc_a.full_text
    text_b = doc_b.full_text
    tokens_a = count_tokens(text_a)
    tokens_b = count_tokens(text_b)

    budget = settings.doc_token_budget

    if fits_whole(text_a, text_b, budget):
        progress(0.2, "Документы помещаются целиком — сравниваю одним запросом…")
        report = _compare_whole(doc_a, doc_b, user_focus, progress)
        mode = "whole"
        sections_compared = 1
    else:
        progress(
            0.2,
            "Документы большие — перехожу к посекционному сравнению…",
        )
        report, sections_compared = _compare_sectioned(
            doc_a, doc_b, user_focus, progress
        )
        mode = "sectioned"

    progress(1.0, "Готово")
    return ComparisonResult(
        report_markdown=report,
        mode=mode,
        doc_a_name=name_a,
        doc_b_name=name_b,
        tokens_a=tokens_a,
        tokens_b=tokens_b,
        sections_compared=sections_compared,
    )


def _compare_whole(
    doc_a: Document, doc_b: Document, user_focus: str, progress: ProgressCb
) -> str:
    prompt = prompts.build_whole_prompt(
        doc_a.name, doc_a.full_text, doc_b.name, doc_b.full_text, user_focus
    )
    progress(0.4, "Модель анализирует документы…")
    return llm_client.complete(prompts.SYSTEM_PROMPT, prompt)


def _compare_sectioned(
    doc_a: Document, doc_b: Document, user_focus: str, progress: ProgressCb
) -> tuple[str, int]:
    pairs = align(doc_a, doc_b)

    # Защита от DoS: ограничиваем число пар секций, чтобы битый/вредоносный docx
    # с тысячами абзацев не породил тысячи запросов к LLM.
    if len(pairs) > settings.max_section_pairs:
        raise ValueError(
            f"Слишком много секций для сравнения: {len(pairs)} "
            f"(лимит {settings.max_section_pairs}). Проверьте документы или "
            f"увеличьте MAX_SECTION_PAIRS."
        )

    notes: list[str] = []
    total = len(pairs) or 1
    compared = 0

    for i, pair in enumerate(pairs):
        left = pair.left.text if pair.left else ""
        right = pair.right.text if pair.right else ""

        # Пропускаем сравнение, если обе стороны пусты.
        if not left and not right:
            continue

        progress(
            0.2 + 0.6 * (i / total),
            f"Сравниваю раздел {i + 1}/{total}: {pair.title[:60]}…",
        )
        prompt = prompts.build_section_prompt(pair.title, left, right, user_focus)
        note = llm_client.complete(prompts.SYSTEM_PROMPT, prompt).strip()
        compared += 1

        if note and note.lower() not in ("без изменений", "без изменений."):
            notes.append(f"### {pair.title}\n{note}")

    if not notes:
        return ("# Отчёт о сравнении\n\nСодержательных различий не обнаружено.", compared)

    section_notes = "\n\n".join(notes)
    progress(0.85, "Свожу посекционные заметки в итоговый отчёт…")
    summary = llm_client.complete(
        prompts.SUMMARY_SYSTEM_PROMPT,
        prompts.build_summary_prompt(section_notes, user_focus),
    )
    return summary, compared
