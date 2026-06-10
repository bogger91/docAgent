"""Клиент к self-hosted Qwen3 через OpenAI-совместимый endpoint.

При MOCK_LLM=true (или любое непустое значение) реальные запросы к модели
не выполняются — вместо них возвращается заглушка. Удобно для ручного
тестирования UI без запущенного Ollama/vLLM.
"""
from __future__ import annotations

import logging
import os
import re

from openai import OpenAI

from .config import settings

log = logging.getLogger(__name__)

_MOCK = bool(os.getenv("MOCK_LLM", ""))

_client = OpenAI(
    base_url=settings.base_url,
    api_key=settings.api_key,
    timeout=settings.request_timeout,
)

# Qwen3 в режиме «thinking» оборачивает рассуждения в <think>...</think>.
# В итоговый отчёт они не нужны — вырезаем.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def complete(system_prompt: str, user_prompt: str, max_tokens: int | None = None) -> str:
    """Один запрос к модели. Возвращает текст ответа без блока рассуждений."""
    if _MOCK:
        return (
            "# Отчёт (mock-режим)\n\n"
            "> Реальная модель не подключена (`MOCK_LLM=true`).\n\n"
            "Документы успешно извлечены и отправлены бы на сравнение — "
            "подключите Qwen3 для получения настоящего анализа."
        )
    effective_max_tokens = max_tokens or settings.min_output_tokens
    sys_tokens = len(system_prompt.split())   # грубая оценка для лога
    usr_tokens = len(user_prompt.split())
    log.info(
        "LLM request | max_tokens=%d | sys_words≈%d | usr_words≈%d | "
        "sum_approx=%d | max_context=%d",
        effective_max_tokens,
        sys_tokens,
        usr_tokens,
        effective_max_tokens + sys_tokens + usr_tokens,
        settings.max_context,
    )
    if effective_max_tokens + sys_tokens + usr_tokens > settings.max_context * 1.1:
        log.warning(
            "POTENTIAL OVERFLOW: max_tokens=%d exceeds safe budget "
            "(max_context=%d, approx_input_words=%d)",
            effective_max_tokens,
            settings.max_context,
            sys_tokens + usr_tokens,
        )
    resp = _client.chat.completions.create(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=effective_max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    usage = resp.usage
    if usage:
        log.info(
            "LLM response | prompt_tokens=%d | completion_tokens=%d | total_tokens=%d",
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
        )
    content = resp.choices[0].message.content or ""
    return _strip_thinking(content)


def health_check() -> tuple[bool, str]:
    """Проверка доступности endpoint и модели. Возвращает (ок, сообщение)."""
    if _MOCK:
        return True, f"MOCK-режим (MOCK_LLM=true) — реальная модель не используется"
    try:
        models = _client.models.list()
        ids = [m.id for m in models.data]
        if settings.model not in ids:
            return (
                False,
                f"Модель '{settings.model}' не найдена на {settings.base_url}. "
                f"Доступны: {', '.join(ids) or '—'}",
            )
        return True, f"OK: {settings.model} @ {settings.base_url}"
    except Exception as exc:  # noqa: BLE001 — наружу отдаём человекочитаемо.
        return False, f"Нет связи с {settings.base_url}: {exc}"
