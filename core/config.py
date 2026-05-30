"""Конфигурация приложения. Значения берутся из .env (см. env.example.txt)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("QWEN_BASE_URL", "http://localhost:11434/v1")
    model: str = os.getenv("QWEN_MODEL", "qwen3:8b")
    api_key: str = os.getenv("QWEN_API_KEY", "local")

    # Полное окно контекста модели в токенах.
    max_context: int = _get_int("MAX_CONTEXT", 32000)
    # Доля окна, зарезервированная под инструкции промпта и ответ модели.
    reserve_ratio: float = _get_float("RESERVE_RATIO", 0.35)

    temperature: float = _get_float("TEMPERATURE", 0.2)
    request_timeout: int = _get_int("REQUEST_TIMEOUT", 600)

    @property
    def doc_token_budget(self) -> int:
        """Сколько токенов остаётся под текст обоих документов в режиме «целиком»."""
        return int(self.max_context * (1.0 - self.reserve_ratio))


settings = Settings()
