@echo off
setlocal

cd /d "%~dp0"

set "APP_URL=http://127.0.0.1:8000"
set "PYTHON_EXE=.venv\Scripts\python.exe"
set "PYTHON_CMD=python"

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python was not found on PATH. Install Python and try again.
    exit /b 1
  )
  set "PYTHON_CMD=py -3"
)

if not exist "%PYTHON_EXE%" (
  echo Creating virtual environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment.
    exit /b 1
  )
)

echo Installing dependencies if needed...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install dependencies.
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    echo Creating .env from .env.example...
    copy ".env.example" ".env" >nul
  )
)

echo Starting AI Nutrition Agent at %APP_URL%
echo Close this window or press Ctrl+C to stop the app.

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 3; Start-Process '%APP_URL%'"

"%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

endlocal
