#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

APP_URL="${APP_URL:-http://127.0.0.1:8000}"
PYTHON_EXE=".venv/bin/python"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="python"
else
  echo "Python was not found on PATH. Install Python 3 and try again."
  exit 1
fi

if [ ! -x "$PYTHON_EXE" ]; then
  echo "Creating virtual environment..."
  "$PYTHON_CMD" -m venv .venv
fi

echo "Installing dependencies if needed..."
"$PYTHON_EXE" -m pip install -r requirements.txt

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  echo "Creating .env from .env.example..."
  cp ".env.example" ".env"
fi

echo "Starting AI Nutrition Agent at $APP_URL"
echo "Press Ctrl+C to stop the app."

(
  sleep 3
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$APP_URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$APP_URL" >/dev/null 2>&1 || true
  fi
) &

"$PYTHON_EXE" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
