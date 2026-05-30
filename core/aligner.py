"""Сопоставление секций двух версий документа для попарного сравнения."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import Document, Section

# Порог похожести заголовков (0..100), выше которого считаем секции «той же».
_MATCH_THRESHOLD = 70


@dataclass
class SectionPair:
    """Пара сопоставленных секций. Любая из сторон может быть None
    (секция добавлена или удалена между версиями)."""

    left: Section | None
    right: Section | None

    @property
    def title(self) -> str:
        if self.left and self.left.heading:
            return self.left.heading
        if self.right and self.right.heading:
            return self.right.heading
        return "(без заголовка)"


def _similarity(a: Section, b: Section) -> float:
    """Похожесть двух секций по заголовку (приоритет) и началу текста."""
    if a.heading and b.heading:
        return fuzz.token_sort_ratio(a.heading, b.heading)
    # Без заголовков сравниваем первые ~200 символов тела.
    return fuzz.token_sort_ratio(a.body[:200], b.body[:200])


def align(doc_a: Document, doc_b: Document) -> list[SectionPair]:
    """Жадно сопоставляет секции двух документов по похожести заголовков,
    сохраняя порядок. Несопоставленные секции возвращаются как добавленные/удалённые."""
    pairs: list[SectionPair] = []
    used_b: set[int] = set()

    for sec_a in doc_a.sections:
        best_idx = -1
        best_score = 0.0
        for j, sec_b in enumerate(doc_b.sections):
            if j in used_b:
                continue
            score = _similarity(sec_a, sec_b)
            if score > best_score:
                best_score = score
                best_idx = j

        if best_idx >= 0 and best_score >= _MATCH_THRESHOLD:
            used_b.add(best_idx)
            pairs.append(SectionPair(left=sec_a, right=doc_b.sections[best_idx]))
        else:
            pairs.append(SectionPair(left=sec_a, right=None))

    # Секции версии B, которым не нашлось пары — новые.
    for j, sec_b in enumerate(doc_b.sections):
        if j not in used_b:
            pairs.append(SectionPair(left=None, right=sec_b))

    return pairs
