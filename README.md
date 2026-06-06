# AI Nutrition Agent

Python web app with a SQLite-backed nutrition database and an AI chat agent for recipe nutrition analysis.

The app uses:

- FastAPI for the web/API layer
- SQLite for local nutrition storage
- USDA FoodData Central JSON downloads as the nutrition source
- Ollama for LLM inference
- Deep Agents as the agent engine

## Quick Start

### Windows

Double-click `run-app.bat`, or run:

```bat
run-app.bat
```

### macOS/Linux

Run:

```sh
chmod +x run-app.sh
./run-app.sh
```

The launcher will:

- create `.venv` if needed
- install Python dependencies from `requirements.txt`
- create `.env` from `.env.example` if `.env` does not exist
- start the app at `http://127.0.0.1:8000`
- open a browser window when possible

Stop the app with `Ctrl+C` in the terminal window running it.

## Configuration

Configure the app in `.env`.

If `.env` does not exist, the launcher copies `.env.example`.

Important settings:

```env
DATABASE_URL=sqlite:///./data/nutrition.sqlite

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
OLLAMA_API_KEY=
OLLAMA_TIMEOUT_SECONDS=120

USDA_JSON_DUMP_PATH=./data/usda-fooddata-central
USDA_DOWNLOAD_PAGE_URL=https://fdc.nal.usda.gov/download-datasets/
USDA_DOWNLOAD_DATA_TYPES=Foundation Foods,SR Legacy,FNDDS
AUTO_IMPORT_USDA_ON_FIRST_RUN=true
```

For local Ollama, keep `OLLAMA_BASE_URL=http://localhost:11434` and set `OLLAMA_MODEL` to an installed local model.

For cloud or proxy Ollama-compatible endpoints, set `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_API_KEY`.

The app loads `.env` into both app settings and the Python process environment.

## Using The App

Open:

```text
http://127.0.0.1:8000
```

Pages:

- `/` - chat page
- `/settings` - import status, Ollama configuration summary, and nutrition database update button

API endpoints:

- `POST /api/chat`
- `POST /api/nutrition/lookup`
- `POST /api/nutrition/calculate`
- `GET /api/usda/import/status`
- `POST /api/usda/import`

## USDA Data

On first run, if `AUTO_IMPORT_USDA_ON_FIRST_RUN=true`, the app imports JSON files from `USDA_JSON_DUMP_PATH` when that path already exists.

The settings page has an `Update nutrition database` button. It downloads current USDA FoodData Central JSON archives from `USDA_DOWNLOAD_PAGE_URL`, extracts them under `USDA_JSON_DUMP_PATH`, and imports them into SQLite.

By default, the app downloads:

- Foundation Foods
- SR Legacy
- FNDDS

You can add `Branded` to `USDA_DOWNLOAD_DATA_TYPES`, but branded food data is much larger.

## Development

Install dependencies manually:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the app manually:

```sh
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Windows:

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run tests:

```sh
.venv/bin/python -m pytest
```

On Windows:

```bat
.venv\Scripts\python.exe -m pytest
```

## Git

The repository ignores generated files such as:

- `.venv/`
- `.env`
- SQLite database files under `data/`
- `__pycache__/`
- server logs
