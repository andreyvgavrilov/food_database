from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import load_settings
from app.db import connect, initialize_database, latest_import_status, record_import_started, update_import_status
from app.usda.downloader import DownloadResult
from app.usda.importer import SOURCE_NAME
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


def _mark_successful_import(connection):
    import_id = record_import_started(connection, SOURCE_NAME, "/tmp/usda-fixture")
    update_import_status(connection, import_id, "completed", completed=True)


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
    assert 'id="chatList"' in response.text
    assert 'id="newChatButton"' in response.text
    assert 'class="spinner"' in response.text
    assert "renderMarkdown" in response.text
    assert "wrapRenderedTables" in response.text
    assert "marked.umd.js" in response.text
    assert "purify.min.js" in response.text
    assert "tex-mml-chtml.js" in response.text
    assert "MathJax.typesetPromise" in response.text
    assert "formatInlineMath" not in response.text
    assert "Tool activity" not in response.text
    assert response.text.index('id="history"') < response.text.index('id="message"')


def test_chat_page_disables_composer_until_usda_import_completes(tmp_path, monkeypatch):
    app, _connection = _test_app(tmp_path, monkeypatch)

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Nutrition database setup is required before chat can answer questions." in response.text
    assert '<textarea id="message" placeholder="Paste a recipe or ask about ingredients" disabled>' in response.text
    assert '<button id="sendButton" type="submit" disabled>Send</button>' in response.text


def test_chat_endpoint_returns_tool_activity(tmp_path, monkeypatch):
    app, connection = _test_app(tmp_path, monkeypatch)
    _mark_successful_import(connection)
    observed_calls = []

    class FakeNutritionAgent:
        def __init__(self, settings, db):
            pass

        def invoke(self, message, history=None):
            observed_calls.append({"message": message, "history": history})
            return {
                "response": "Done",
                "tool_activity": ["Looked up **olive oil**."],
                "raw": {"message": message},
            }

    monkeypatch.setattr(routes, "NutritionAgent", FakeNutritionAgent)

    response = TestClient(app).post("/api/chat", json={"message": "olive oil"})

    assert response.status_code == 200
    assert response.json()["chat_id"] > 0
    assert response.json()["tool_activity"] == ["Looked up **olive oil**."]
    assert observed_calls == [{"message": "olive oil", "history": []}]


def test_chat_endpoint_reuses_chat_and_passes_history(tmp_path, monkeypatch):
    app, connection = _test_app(tmp_path, monkeypatch)
    _mark_successful_import(connection)
    observed_calls = []

    class FakeNutritionAgent:
        def __init__(self, settings, db):
            pass

        def invoke(self, message, history=None):
            observed_calls.append({"message": message, "history": history})
            return {"response": f"Answer to {message}", "tool_activity": [], "raw": None}

    monkeypatch.setattr(routes, "NutritionAgent", FakeNutritionAgent)
    client = TestClient(app)

    first = client.post("/api/chat", json={"message": "100g egg"}).json()
    second_response = client.post(
        "/api/chat",
        json={"chat_id": first["chat_id"], "message": "What about per 100g?"},
    )

    assert second_response.status_code == 200
    assert second_response.json()["chat_id"] == first["chat_id"]
    assert observed_calls[1] == {
        "message": "What about per 100g?",
        "history": [
            {"role": "user", "content": "100g egg"},
            {"role": "assistant", "content": "Answer to 100g egg"},
        ],
    }


def test_chat_history_endpoints_list_and_load_previous_chats(tmp_path, monkeypatch):
    app, connection = _test_app(tmp_path, monkeypatch)
    _mark_successful_import(connection)

    class FakeNutritionAgent:
        def __init__(self, settings, db):
            pass

        def invoke(self, message, history=None):
            return {"response": "Stored answer", "tool_activity": ["Calculated nutrition."], "raw": {"ok": True}}

    monkeypatch.setattr(routes, "NutritionAgent", FakeNutritionAgent)
    client = TestClient(app)
    chat_id = client.post("/api/chat", json={"message": "Lunch recipe"}).json()["chat_id"]

    list_response = client.get("/api/chats")
    messages_response = client.get(f"/api/chats/{chat_id}/messages")

    assert list_response.status_code == 200
    assert list_response.json()["chats"][0]["id"] == chat_id
    assert list_response.json()["chats"][0]["message_count"] == 2
    assert messages_response.status_code == 200
    assert messages_response.json()["messages"] == [
        {
            "id": messages_response.json()["messages"][0]["id"],
            "thread_id": chat_id,
            "role": "user",
            "content": "Lunch recipe",
            "tool_activity": [],
            "raw": None,
            "created_at": messages_response.json()["messages"][0]["created_at"],
        },
        {
            "id": messages_response.json()["messages"][1]["id"],
            "thread_id": chat_id,
            "role": "assistant",
            "content": "Stored answer",
            "tool_activity": ["Calculated nutrition."],
            "raw": {"ok": True},
            "created_at": messages_response.json()["messages"][1]["created_at"],
        },
    ]


def test_chat_endpoint_rejects_messages_until_usda_import_completes(tmp_path, monkeypatch):
    app, _connection = _test_app(tmp_path, monkeypatch)

    class FailingNutritionAgent:
        def __init__(self, settings, db):
            pass

        def invoke(self, message, history=None):
            raise AssertionError("chat should not invoke the agent before nutrition data is imported")

    monkeypatch.setattr(routes, "NutritionAgent", FailingNutritionAgent)

    response = TestClient(app).post("/api/chat", json={"message": "100g egg"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Nutrition data has not been imported yet. Open Settings and update the nutrition database."
    )


def test_manual_import_endpoint_prevents_duplicate_jobs(tmp_path, monkeypatch):
    app, _connection = _test_app(tmp_path, monkeypatch)
    routes.import_lock.acquire()
    try:
        response = TestClient(app).post("/api/usda/import")
    finally:
        routes.import_lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "USDA import is already running"
