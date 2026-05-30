# docAgent

Сравнение двух версий многостраничного `.docx` (договор, регламент и т.п.)
с помощью self-hosted **Qwen3** через OpenAI-совместимый API. Пользователь
загружает два файла, задаёт фокус анализа промптом и получает связный
текстовый отчёт о различиях в Markdown с возможностью экспорта.

## Архитектура

```
[2 docx] → extractor → секции/таблицы
                          │
                    chunker (оценка токенов)
                          │
            ┌─────────────┴──────────────┐
   влезает в контекст           не влезает
            │                            │
  comparator: 1 запрос          aligner: пары секций
            │                            │
            │                    comparator: N запросов → summary
            └─────────────┬──────────────┘
                          │
              llm_client (Qwen3 via OpenAI API)
                          │
                  отчёт (Markdown)
                          │
              FastAPI /api/compare → web/index.html
```

| Модуль | Назначение |
|---|---|
| `core/config.py` | Настройки из `.env` (endpoint, модель, бюджет контекста) |
| `core/models.py` | Модели данных: `Section`, `Document` |
| `core/extractor.py` | `.docx` → секции по заголовкам + таблицы в markdown |
| `core/chunker.py` | Оценка токенов, проверка «влезает целиком», группировка |
| `core/aligner.py` | Сопоставление секций двух версий (fuzzy по заголовкам) |
| `core/llm_client.py` | OpenAI-совместимый клиент к Qwen3, срез `<think>` |
| `core/prompts.py` | Системные и пользовательские шаблоны промптов |
| `core/comparator.py` | Оркестрация: выбор режима, сборка отчёта |
| `server.py` | FastAPI: отдаёт фронт, `/api/compare`, `/api/health` |
| `web/index.html` | Фронт на vanilla JS (загрузка, промпт, спиннер, экспорт) |

### Два режима сравнения
- **whole** — если оба документа влезают в `MAX_CONTEXT * (1 - RESERVE_RATIO)`,
  сравниваем одним запросом (максимальная точность).
- **sectioned** — если не влезают: бьём на секции, сопоставляем версии,
  сравниваем попарно, затем сводим заметки в итоговый отчёт.

## Установка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp env.example.txt .env   # затем отредактируйте .env под свой Qwen3
```

## Подготовка Qwen3 (пример с Ollama)

```bash
ollama pull qwen3:8b
ollama serve
```

> **Важно:** в Ollama окно контекста по умолчанию 4096 токенов. Для длинных
> документов поднимите его (`num_ctx`) и укажите фактическое значение в
> `MAX_CONTEXT` в `.env`. Для vLLM/LM Studio используйте их базовый URL и имя модели.

## Запуск

```bash
python server.py
# или: uvicorn server:app --reload --port 8000
```

Откройте http://127.0.0.1:8000 — индикатор сверху покажет, доступна ли модель.

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

- `tests/test_core.py` — юнит-тесты извлечения, оценки токенов и выравнивания секций (без сети).
- `tests/test_e2e.py` — e2e через FastAPI `TestClient` с замоканным LLM-клиентом:
  проверяют полный путь загрузка `.docx` → `/api/compare` → отчёт в обоих режимах
  (whole / sectioned), а также health, валидацию входных файлов и проброс ошибок модели.

Запущенный Qwen3 для тестов **не требуется** — обращения к модели замоканы.

## Настройки (`.env`)

| Переменная | Смысл |
|---|---|
| `QWEN_BASE_URL` | OpenAI-совместимый endpoint (Ollama/vLLM/LM Studio) |
| `QWEN_MODEL` | Имя модели в раннере |
| `MAX_CONTEXT` | Фактическое окно контекста модели, токенов |
| `RESERVE_RATIO` | Доля окна под инструкции и ответ (остальное — под документы) |
| `TEMPERATURE` | Температура генерации |
| `REQUEST_TIMEOUT` | Таймаут запроса к модели, сек |
