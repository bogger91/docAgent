"""Оценка размера текста в токенах и группировка секций в чанки."""
from __future__ import annotations

from .models import Section

try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        """Оценка числа токенов. cl100k — лишь приближение для Qwen, но достаточно
        точное для бюджетирования контекста (ошибка в безопасную сторону)."""
        return len(_enc.encode(text))

except Exception:  # tiktoken недоступен — грубая эвристика по символам.

    def count_tokens(text: str) -> int:
        # ~4 символа на токен для смешанного русско-английского текста.
        return max(1, len(text) // 3)


def fits_whole(doc_a_text: str, doc_b_text: str, budget: int) -> bool:
    """Помещаются ли оба документа целиком в бюджет токенов."""
    return count_tokens(doc_a_text) + count_tokens(doc_b_text) <= budget


def group_sections(sections: list[Section], max_tokens: int) -> list[list[Section]]:
    """Группирует подряд идущие секции в чанки не больше max_tokens токенов.

    Секции, которые сами по себе больше лимита, идут отдельным чанком (будут
    отправлены как есть — модель обрежет, но это крайний случай)."""
    chunks: list[list[Section]] = []
    current: list[Section] = []
    current_tokens = 0

    for section in sections:
        sec_tokens = count_tokens(section.text)
        if current and current_tokens + sec_tokens > max_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(section)
        current_tokens += sec_tokens

    if current:
        chunks.append(current)
    return chunks
