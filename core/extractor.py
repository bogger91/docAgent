"""Извлечение текста из .docx с сохранением структуры заголовков и таблиц."""
from __future__ import annotations

from io import BytesIO

from docx import Document as DocxDocument
from docx.document import Document as _DocxDocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from .models import Document, Section


def _iter_block_items(parent):
    """Обходит абзацы и таблицы в естественном порядке их следования в документе.

    python-docx по умолчанию разделяет paragraphs и tables, теряя их взаимный
    порядок. Здесь мы идём по XML-телу и сохраняем порядок.
    """
    if isinstance(parent, _DocxDocumentType):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise TypeError(f"Unsupported parent type: {type(parent)!r}")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _heading_level(paragraph: Paragraph) -> int | None:
    """Возвращает уровень заголовка (1..9) или None, если абзац не заголовок."""
    style = paragraph.style.name if paragraph.style else ""
    if not style:
        return None
    # Поддерживаем англоязычные ("Heading 1") и русские ("Заголовок 1") стили.
    for prefix in ("Heading", "Заголовок"):
        if style.startswith(prefix):
            tail = style[len(prefix):].strip()
            if tail.isdigit():
                return int(tail)
    if style.lower() in ("title", "заголовок"):
        return 1
    return None


def _table_to_markdown(table: Table) -> str:
    """Простое представление таблицы как markdown — чтобы модель видела структуру."""
    rows: list[str] = []
    for r_idx, row in enumerate(table.rows):
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
        if r_idx == 0:
            rows.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(rows)


def extract_document(data: bytes, name: str) -> Document:
    """Парсит байты .docx в структурированный Document."""
    docx = DocxDocument(BytesIO(data))

    sections: list[Section] = []
    current_heading = ""
    current_level = 0
    body_parts: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal index, body_parts
        body = "\n".join(p for p in body_parts if p.strip())
        # Не создаём пустых секций без заголовка и без текста.
        if not current_heading and not body.strip():
            body_parts = []
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
        body_parts = []

    for block in _iter_block_items(docx):
        if isinstance(block, Paragraph):
            level = _heading_level(block)
            if level is not None and block.text.strip():
                # Начинается новая секция — сохраняем предыдущую.
                flush()
                current_heading = block.text.strip()
                current_level = level
            elif block.text.strip():
                body_parts.append(block.text.strip())
        elif isinstance(block, Table):
            md = _table_to_markdown(block)
            if md.strip():
                body_parts.append("\n" + md + "\n")

    flush()

    if not sections:
        # Документ без распознанных заголовков — кладём всё одной секцией.
        sections.append(
            Section(heading="", level=0, body=docx_plain_text(docx), index=0)
        )

    return Document(name=name, sections=sections)


def docx_plain_text(docx) -> str:
    """Фолбэк: весь текст документа плоско, если структура не распозналась."""
    parts: list[str] = []
    for block in _iter_block_items(docx):
        if isinstance(block, Paragraph) and block.text.strip():
            parts.append(block.text.strip())
        elif isinstance(block, Table):
            parts.append(_table_to_markdown(block))
    return "\n".join(parts)
