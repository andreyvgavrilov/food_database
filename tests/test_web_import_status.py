from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import load_settings
from app.db import connect, initialize_database, latest_import_status
from app.usda.downloader import DownloadResult
from app.web import routes
from app.web.routes import create_router


def _test_app(tmp_path, monkeypatch):
    settings = load_settings(
        {
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'nutrition.sqlite').as_posix()}",
            "USDA_JSON_DUMP_PATH": str(tmp_path / "usda"),
            "USDA_DOWNLOAD_PAGE_URL": "https://fdc.example.test/download-datasets/",
            "AUTO_IMPORT_USDA_ON_FIRST_RUN": "false",
        }
    )
    connection = connect(settings.database_path)
    initialize_database(connection)
    app = FastAPI()
    app.include_router(create_router(settings, connection))
    return app, connection


def test_manual_import_records_downloading_before_download(tmp_path, monkeypatch):
    app, connection = _test_app(tmp_path, monkeypatch)
    observed_statuses = []

    def fake_download(download_page_url, selected_data_types, destination_root):
        observed_statuses.append(latest_import_status(connection)["status"])
        return DownloadResult(extracted_path=tmp_path / "extracted", downloads=[])

    monkeypatch.setattr(routes, "download_usda_json_dump", fake_download)
    monkeypatch.setattr(routes, "import_usda_dump", lambda *args, **kwargs: None)

    response = TestClient(app).post("/api/usda/import")

    assert response.status_code == 200
    assert observed_statuses == ["downloading"]
    assert latest_import_status(connection)["source_path"] == "https://fdc.example.test/download-datasets/"


def test_chat_page_contains_history_loader_and_composer(tmp_path, monkeypatch):
    app, _connection = _test_app(tmp_path, monkeypatch)

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert 'id="history"' in response.text
    assert 'class="spinner"' in response.text
    assert "renderMarkdown" in response.text
    assert response.text.index('id="history"') < response.text.index('id="message"')


def test_chat_endpoint_returns_tool_activity(tmp_path, monkeypatch):
    app, _connection = _test_app(tmp_path, monkeypatch)

    class FakeNutritionAgent:
        def __init__(self, settings, db):
            pass

        def invoke(self, message):
            return {
                "response": "Done",
                "tool_activity": ["Looked up **olive oil**."],
                "raw": {"message": message},
            }

    monkeypatch.setattr(routes, "NutritionAgent", FakeNutritionAgent)

    response = TestClient(app).post("/api/chat", json={"message": "olive oil"})

    assert response.status_code == 200
    assert response.json()["tool_activity"] == ["Looked up **olive oil**."]


def test_manual_import_endpoint_prevents_duplicate_jobs(tmp_path, monkeypatch):
    app, _connection = _test_app(tmp_path, monkeypatch)
    routes.import_lock.acquire()
    try:
        response = TestClient(app).post("/api/usda/import")
    finally:
        routes.import_lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "USDA import is already running"
