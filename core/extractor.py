"""Извлечение текста из документов через markitdown с восстановлением секций.

markitdown отдаёт плоский Markdown (для .docx заголовки приходят как `#`/`##`,
в т.ч. для русских стилей; для цифровых .pdf заголовков обычно нет). Структуру
`Section[]`, на которой держится режим sectioned, восстанавливаем парсингом
строк-заголовков `#`.
"""
from __future__ import annotations

import re
from io import BytesIO

from markitdown import MarkItDown, StreamInfo

from .models import Document, Section

# Инициализация markitdown (magika) дорогая — создаём конвертер один раз на модуль.
_md = MarkItDown()

# Строка-заголовок Markdown: уровень = число решёток, остальное — текст заголовка.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def convert_to_markdown(data: bytes, name: str) -> str:
    """Конвертирует байты документа (.docx/.pdf) в плоский Markdown."""
    ext = ".pdf" if name.lower().endswith(".pdf") else ".docx"
    try:
        result = _md.convert_stream(
            BytesIO(data), stream_info=StreamInfo(extension=ext)
        )
    except Exception as exc:  # noqa: BLE001 — наружу человекочитаемо.
        raise ValueError(f"Не удалось извлечь текст из '{name}': {exc}") from exc
    return result.text_content or ""


def parse_markdown_to_sections(markdown: str) -> list[Section]:
    """Разбивает плоский Markdown на секции по заголовкам `#`.

    Строки до первого заголовка собираются в преамбулу (`heading=""`, `level=0`),
    но только если непустые. Если заголовков нет вовсе, а текст есть — весь текст
    кладётся одной секцией уровня 0."""
    sections: list[Section] = []
    current_heading = ""
    current_level = 0
    body_lines: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal index, body_lines
        body = "\n".join(body_lines).strip()
        # Не создаём пустых секций без заголовка и без текста (как старый extractor).
        if not current_heading and not body:
            body_lines = []
            return
        sections.append(
            Section(
                heading=current_heading,
                level=current_level,
                body=body,
                index=index,
            )
        )
        index += 1
        body_lines = []

    for line in markdown.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            current_level = len(m.group(1))
            current_heading = m.group(2).strip()
        else:
            body_lines.append(line)

    flush()
    return sections


def extract_document_with_markdown(data: bytes, name: str) -> tuple[Document, str]:
    """Извлекает Document и одновременно возвращает плоский Markdown документа.

    Markdown считается один раз и переиспользуется: и для построения секций,
    и для показа/скачивания на фронте."""
    markdown = convert_to_markdown(data, name)
    sections = parse_markdown_to_sections(markdown)
    if not sections:
        # Пустой документ — одна пустая секция, чтобы full_text/режимы не падали.
        sections.append(Section(heading="", level=0, body="", index=0))
    return Document(name=name, sections=sections), markdown


def extract_document(data: bytes, name: str) -> Document:
    """Парсит байты документа в структурированный Document."""
    return extract_document_with_markdown(data, name)[0]
