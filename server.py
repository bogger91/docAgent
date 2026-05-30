"""FastAPI-сервер: отдаёт фронт и принимает документы на сравнение."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from core.comparator import compare_documents
from core.config import settings
from core.llm_client import health_check

app = FastAPI(title="docAgent — сравнение docx через Qwen3")

WEB_DIR = Path(__file__).parent / "web"
MAX_FILE_MB = 25


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> JSONResponse:
    ok, message = health_check()
    return JSONResponse(
        {
            "ok": ok,
            "message": message,
            "model": settings.model,
            "base_url": settings.base_url,
            "max_context": settings.max_context,
        }
    )


MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024


def _check_size_before_read(file: UploadFile) -> None:
    """Отклоняет слишком большой файл ДО чтения его в память.

    Starlette проставляет UploadFile.size из заголовков multipart — это позволяет
    не загружать гигабайтный файл в RAM ради того, чтобы потом его отвергнуть."""
    if file.size is not None and file.size > MAX_FILE_BYTES:
        raise HTTPException(400, f"Файл '{file.filename}' больше {MAX_FILE_MB} МБ")


def _validate(file: UploadFile, data: bytes) -> None:
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, f"Файл '{file.filename}' не .docx")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(400, f"Файл '{file.filename}' больше {MAX_FILE_MB} МБ")
    if not data:
        raise HTTPException(400, f"Файл '{file.filename}' пуст")


@app.post("/api/compare")
async def compare(
    file_a: UploadFile,
    file_b: UploadFile,
    focus: str = Form(""),
) -> JSONResponse:
    # Сначала проверяем заявленный размер, лишь затем читаем в память.
    _check_size_before_read(file_a)
    _check_size_before_read(file_b)
    data_a = await file_a.read()
    data_b = await file_b.read()
    _validate(file_a, data_a)
    _validate(file_b, data_b)

    try:
        result = compare_documents(
            data_a, file_a.filename or "A.docx",
            data_b, file_b.filename or "B.docx",
            user_focus=focus,
        )
    except Exception as exc:  # noqa: BLE001 — наружу человекочитаемо.
        raise HTTPException(500, f"Ошибка сравнения: {exc}") from exc

    return JSONResponse(
        {
            "report_markdown": result.report_markdown,
            "mode": result.mode,
            "doc_a_name": result.doc_a_name,
            "doc_b_name": result.doc_b_name,
            "tokens_a": result.tokens_a,
            "tokens_b": result.tokens_b,
            "sections_compared": result.sections_compared,
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
