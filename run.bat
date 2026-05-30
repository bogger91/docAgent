@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  docAgent - запуск приложения (Windows)
REM  При первом запуске создаёт venv, ставит зависимости и .env
REM ============================================================

cd /d "%~dp0"

REM --- Поиск Python: сначала лаунчер py, затем python ---
set "PY_CMD="
where py >nul 2>nul && set "PY_CMD=py"
if not defined PY_CMD (
    where python >nul 2>nul && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [ОШИБКА] Python не найден в PATH. Установите Python 3.10+ и повторите.
    echo Скачать: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Создание виртуального окружения при первом запуске ---
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Создаю виртуальное окружение через "%PY_CMD%"...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b 1
    )
    echo [2/4] Устанавливаю зависимости...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Виртуальное окружение найдено.
    echo [2/4] Зависимости уже установлены.
)

REM --- Создание .env из примера, если его ещё нет ---
if not exist ".env" (
    echo [3/4] Создаю .env из env.example.txt...
    copy /y "env.example.txt" ".env" >nul
    echo.
    echo [ВНИМАНИЕ] Создан файл .env с настройками по умолчанию.
    echo Откройте .env и укажите адрес вашего Qwen3 ^(QWEN_BASE_URL^) и имя модели ^(QWEN_MODEL^).
    echo.
) else (
    echo [3/4] Файл .env найден.
)

REM --- Запуск сервера и открытие браузера ---
echo [4/4] Запускаю сервер на http://127.0.0.1:8000 ...
echo Для остановки нажмите Ctrl+C в этом окне.
echo.

REM Браузер откроется через 4 секунды (даём серверу время подняться),
REM параллельно с запуском сервера в этом же окне.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" http://127.0.0.1:8000"

".venv\Scripts\python.exe" server.py

REM Если сервер завершился (в т.ч. с ошибкой) — НЕ закрываем окно молча,
REM чтобы можно было прочитать сообщение/трейсбек.
echo.
echo ============================================================
echo  Сервер остановлен. Если выше есть ошибка - пришлите её текст.
echo ============================================================
pause

endlocal
