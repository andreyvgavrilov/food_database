from __future__ import annotations

import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.agent.engine import NutritionAgent
from app.agent.ollama import IngredientNormalizer
from app.config import Settings
from app.db import connect, initialize_database, latest_import_status, record_import_failure
from app.nutrition.calculator import NutritionCalculator
from app.schemas import ChatRequest, ChatResponse, IngredientLookupRequest, NutritionCalculationRequest
from app.usda.downloader import download_usda_json_dump
from app.usda.importer import import_usda_dump
from app.usda.lookup import IngredientLookup


import_lock = threading.Lock()


def create_router(settings: Settings, connection: sqlite3.Connection) -> APIRouter:
    router = APIRouter()

    def get_connection() -> sqlite3.Connection:
        return connection

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        return """
        <!doctype html>
        <html>
          <head>
            <title>AI Nutrition Agent</title>
            <style>
              body { font-family: Arial, sans-serif; margin: 2rem; max-width: 960px; }
              textarea { width: 100%; min-height: 140px; }
              button { padding: 0.5rem 0.8rem; }
              pre { background: #f4f4f4; padding: 1rem; overflow: auto; }
              nav a { margin-right: 1rem; }
            </style>
          </head>
          <body>
            <nav><a href="/">Chat</a><a href="/settings">Settings</a></nav>
            <h1>AI Nutrition Agent</h1>
            <textarea id="message" placeholder="Paste a recipe or ask about ingredients"></textarea>
            <p><button onclick="sendChat()">Send</button></p>
            <pre id="response"></pre>
            <script>
              async function sendChat() {
                const message = document.getElementById('message').value;
                const res = await fetch('/api/chat', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({message})
                });
                document.getElementById('response').textContent = JSON.stringify(await res.json(), null, 2);
              }
            </script>
          </body>
        </html>
        """

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page() -> str:
        status = latest_import_status(connection)
        status_text = status["status"] if status else "no import yet"
        return f"""
        <!doctype html>
        <html>
          <head>
            <title>Nutrition Agent Settings</title>
            <style>
              body {{ font-family: Arial, sans-serif; margin: 2rem; max-width: 960px; }}
              button {{ padding: 0.5rem 0.8rem; }}
              pre {{ background: #f4f4f4; padding: 1rem; overflow: auto; }}
              nav a {{ margin-right: 1rem; }}
            </style>
          </head>
          <body>
            <nav><a href="/">Chat</a><a href="/settings">Settings</a></nav>
            <h1>Settings</h1>
            <p>USDA import status: <strong>{status_text}</strong></p>
            <p>Ollama endpoint: <code>{settings.ollama_base_url}</code></p>
            <p>Ollama model: <code>{settings.ollama_model}</code></p>
            <button onclick="updateDb()">Update nutrition database</button>
            <pre id="status"></pre>
            <script>
              async function updateDb() {{
                const res = await fetch('/api/usda/import', {{ method: 'POST' }});
                document.getElementById('status').textContent = JSON.stringify(await res.json(), null, 2);
              }}
            </script>
          </body>
        </html>
        """

    @router.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return NutritionAgent(settings, db).invoke(request.message)

    @router.post("/api/nutrition/lookup")
    def lookup(request: IngredientLookupRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return IngredientLookup(db).get_ingredient_nutrition(
            request.ingredient_name,
            request.preferred_food_category,
            request.max_results,
        )

    @router.post("/api/nutrition/calculate")
    def calculate(request: NutritionCalculationRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        ingredients = [ingredient.model_dump() for ingredient in request.ingredients]
        normalization_warning = None
        try:
            ingredients = IngredientNormalizer(settings).normalize(ingredients)
        except Exception as exc:
            normalization_warning = f"Ingredient normalization unavailable, using submitted names: {exc}"

        result = NutritionCalculator(db).calculate_total_nutrition(ingredients, request.servings)
        if normalization_warning:
            result["warnings"].insert(0, normalization_warning)
        return result

    @router.get("/api/usda/import/status")
    def import_status(db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return {"status": latest_import_status(db)}

    @router.post("/api/usda/import")
    def start_import(background_tasks: BackgroundTasks) -> dict[str, str]:
        if not import_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="USDA import is already running")

        def run_import() -> None:
            task_connection = connect(settings.database_path)
            try:
                initialize_database(task_connection)
                download = download_usda_json_dump(
                    settings.usda_download_page_url,
                    settings.usda_download_data_types,
                    settings.usda_json_dump_path,
                )
                import_usda_dump(task_connection, download.extracted_path)
            except Exception as exc:
                record_import_failure(
                    task_connection,
                    "USDA FoodData Central JSON dump",
                    str(settings.usda_json_dump_path),
                    str(exc),
                )
            finally:
                task_connection.close()
                import_lock.release()

        background_tasks.add_task(run_import)
        return {"status": "started"}

    return router
