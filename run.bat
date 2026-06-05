@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  docAgent - запуск приложения (Windows)
REM  При первом запуске создаёт venv, ставит зависимости и .env
REM ============================================================

pushd "%~dp0"

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

REM --- Создание .env из примера, если его ещё нет (ДО установки: прокси нужен pip) ---
if not exist ".env" goto make_env
echo [1/4] Файл .env найден.
goto env_ready
:make_env
echo [1/4] Создаю .env из env.example.txt...
copy /y "env.example.txt" ".env" >nul
echo.
echo [ВНИМАНИЕ] Создан файл .env с настройками по умолчанию.
echo Если интернет только через корпоративный прокси, откройте .env,
echo заполните PIP_PROXY и запустите run.bat снова.
echo.
:env_ready

REM --- Читаем настройки прокси из .env и применяем к pip ---
REM Используем goto-метки вместо вложенных if(...) — скобки в значениях/эхо
REM внутри блоков if ломают парсер cmd и окно закрывается молча.
set "PIP_PROXY="
set "PIP_TRUST_HOST="
for /f "usebackq tokens=1* delims==" %%K in (`findstr /b /c:"PIP_PROXY=" ".env"`) do set "PIP_PROXY=%%L"
for /f "usebackq tokens=1* delims==" %%K in (`findstr /b /c:"PIP_TRUST_HOST=" ".env"`) do set "PIP_TRUST_HOST=%%L"

set "PIP_EXTRA_ARGS="
if not defined PIP_PROXY goto check_trust
if "%PIP_PROXY%"=="" goto check_trust
echo [i] Использую прокси из .env для pip: %PIP_PROXY%
set "HTTP_PROXY=%PIP_PROXY%"
set "HTTPS_PROXY=%PIP_PROXY%"
set "PIP_EXTRA_ARGS=%PIP_EXTRA_ARGS% --proxy %PIP_PROXY%"

:check_trust
if not "%PIP_TRUST_HOST%"=="1" goto proxy_done
echo [i] pip: доверяю зеркалам PyPI ^(PIP_TRUST_HOST=1^)
set "PIP_EXTRA_ARGS=%PIP_EXTRA_ARGS% --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org"
:proxy_done

REM --- Создание виртуального окружения при первом запуске ---
REM Проверяем, что venv существует И реально работает (мог быть создан на другой машине)
set "VENV_OK=0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>nul
    if not errorlevel 1 set "VENV_OK=1"
)
if "%VENV_OK%"=="0" (
    if exist ".venv" (
        echo [2/4] Виртуальное окружение повреждено или создано на другой машине. Пересоздаю...
        rmdir /s /q ".venv"
    ) else (
        echo [2/4] Создаю виртуальное окружение через "%PY_CMD%"...
    )
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Виртуальное окружение найдено.
)

REM --- Проверяем, что зависимости РЕАЛЬНО установлены (а не просто есть venv).
REM Если предыдущий pip install падал (нет сети/прокси), venv остаётся пустым,
REM и сервер падает с ModuleNotFoundError. Поэтому проверяем сам пакет. ---
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, docx, openai" >nul 2>nul
if errorlevel 1 (
    echo [3/4] Устанавливаю зависимости...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip %PIP_EXTRA_ARGS%
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt %PIP_EXTRA_ARGS%
    if errorlevel 1 (
        echo.
        echo [ОШИБКА] Не удалось установить зависимости.
        echo Частые причины и решения:
        echo   * Нет доступа в интернет / корпоративный прокси —
        echo     откройте .env и заполните PIP_PROXY ^(см. комментарий в файле^).
        echo   * Ошибка SSL / CERTIFICATE_VERIFY_FAILED —
        echo     поставьте в .env  PIP_TRUST_HOST=1  и запустите снова.
        pause
        exit /b 1
    )
    REM Повторная проверка: установка могла "пройти", но пакета всё равно нет.
    ".venv\Scripts\python.exe" -c "import fastapi" >nul 2>nul
    if errorlevel 1 (
        echo [ОШИБКА] fastapi не установился. Прокрутите вывод pip выше и пришлите ошибку.
        pause
        exit /b 1
    )
) else (
    echo [3/4] Зависимости уже установлены.
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

popd
endlocal
