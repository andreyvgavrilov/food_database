from __future__ import annotations

from fastapi import FastAPI

from app.config import load_settings
from app.db import connect, has_successful_import, initialize_database
from app.usda.importer import import_usda_dump
from app.web.routes import create_router


settings = load_settings()
connection = connect(settings.database_path)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Nutrition Agent")
    initialize_database(connection)
    if settings.auto_import_usda_on_first_run and not has_successful_import(connection):
        if settings.usda_json_dump_path.exists():
            import_usda_dump(connection, settings.usda_json_dump_path)
    app.include_router(create_router(settings, connection))
    return app


app = create_app()
