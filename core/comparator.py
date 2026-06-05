"""Оркестрация сравнения: выбор режима и сборка итогового отчёта."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import llm_client, prompts
from .aligner import align
from .chunker import count_tokens, fits_whole
from .config import settings
from .extractor import extract_document_with_markdown
from .models import Document


def _output_budget(input_tokens: int) -> int:
    """Сколько токенов оставляем под ответ модели."""
    return max(512, settings.max_context - input_tokens)


# Колбэк прогресса: (доля 0..1, текстовая метка). Используется UI для спиннера/лога.
ProgressCb = Callable[[float, str], None]


@dataclass
class AnalysisResult:
    report_markdown: str
    doc_name: str
    tokens: int
    markdown: str


@dataclass
class ComparisonResult:
    report_markdown: str
    mode: str               # "whole" | "sectioned"
    doc_a_name: str
    doc_b_name: str
    tokens_a: int
    tokens_b: int
    sections_compared: int
    markdown_a: str
    markdown_b: str


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
    doc_a, md_a = extract_document_with_markdown(file_a, name_a)
    doc_b, md_b = extract_document_with_markdown(file_b, name_b)

    text_a = doc_a.full_text
    text_b = doc_b.full_text
    tokens_a = count_tokens(text_a)
    tokens_b = count_tokens(text_b)

    whole_prompt = prompts.build_whole_prompt(doc_a.name, text_a, doc_b.name, text_b, user_focus)
    whole_input_tokens = count_tokens(prompts.SYSTEM_PROMPT) + count_tokens(whole_prompt)
    budget = settings.max_context - settings.min_output_tokens

    if fits_whole(whole_input_tokens, budget):
        progress(0.2, "Документы помещаются целиком — сравниваю одним запросом…")
        report = _compare_whole(doc_a, doc_b, user_focus, progress, whole_prompt, whole_input_tokens)
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
        markdown_a=md_a,
        markdown_b=md_b,
    )


def analyze_document(
    file: bytes,
    name: str,
    question: str = "",
    progress: ProgressCb | None = None,
) -> AnalysisResult:
    """Анализирует один документ: отвечает на вопрос пользователя или делает обзор."""
    progress = progress or _noop

    progress(0.1, "Извлечение текста из документа…")
    doc, md = extract_document_with_markdown(file, name)
    tokens = count_tokens(doc.full_text)

    progress(0.3, "Модель анализирует документ…")
    prompt = prompts.build_analyze_prompt(name, doc.full_text, question)
    input_tokens = count_tokens(prompts.ANALYZE_SYSTEM_PROMPT) + count_tokens(prompt)
    report = llm_client.complete(
        prompts.ANALYZE_SYSTEM_PROMPT,
        prompt,
        max_tokens=_output_budget(input_tokens),
    )

    progress(1.0, "Готово")
    return AnalysisResult(report_markdown=report, doc_name=name, tokens=tokens, markdown=md)


def _compare_whole(
    doc_a: Document,
    doc_b: Document,
    user_focus: str,
    progress: ProgressCb,
    prompt: str,
    input_tokens: int,
) -> str:
    progress(0.4, "Модель анализирует документы…")
    return llm_client.complete(
        prompts.SYSTEM_PROMPT,
        prompt,
        max_tokens=_output_budget(input_tokens),
    )


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
        input_tokens = count_tokens(prompts.SYSTEM_PROMPT) + count_tokens(prompt)
        note = llm_client.complete(
            prompts.SYSTEM_PROMPT,
            prompt,
            max_tokens=_output_budget(input_tokens),
        ).strip()
        compared += 1

        if note and note.lower() not in ("без изменений", "без изменений."):
            notes.append(f"### {pair.title}\n{note}")

    if not notes:
        return ("# Отчёт о сравнении\n\nСодержательных различий не обнаружено.", compared)

    section_notes = "\n\n".join(notes)
    progress(0.85, "Свожу посекционные заметки в итоговый отчёт…")
    summary_prompt = prompts.build_summary_prompt(section_notes, user_focus)
    summary_input_tokens = count_tokens(prompts.SUMMARY_SYSTEM_PROMPT) + count_tokens(summary_prompt)
    summary = llm_client.complete(
        prompts.SUMMARY_SYSTEM_PROMPT,
        summary_prompt,
        max_tokens=_output_budget(summary_input_tokens),
    )
    return summary, compared
