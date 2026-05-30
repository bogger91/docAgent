"""Лёгкие модели данных, общие для всех модулей core."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    """Логическая секция документа: заголовок и относящийся к нему текст."""

    heading: str          # текст заголовка ("" для преамбулы без заголовка)
    level: int            # уровень вложенности (0 — преамбула, 1 — H1, ...)
    body: str             # текст секции, включая таблицы в виде markdown
    index: int            # порядковый номер секции в документе

    @property
    def text(self) -> str:
        """Полный текст секции для подачи в модель."""
        if self.heading:
            return f"{self.heading}\n{self.body}".strip()
        return self.body.strip()


@dataclass
class Document:
    """Извлечённый документ как набор секций."""

    name: str
    sections: list[Section] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(s.text for s in self.sections if s.text)
