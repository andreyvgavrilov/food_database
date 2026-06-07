from app.chat.history import add_chat_message, create_chat_thread, list_chat_messages, list_chat_threads
from app.db import connect, initialize_database


def test_connect_configures_sqlite_for_concurrent_app_access(tmp_path):
    connection = connect(tmp_path / "nutrition.sqlite")

    try:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        connection.close()

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 60000
    assert foreign_keys == 1


def test_chat_history_persists_threads_and_messages(tmp_path):
    connection = connect(tmp_path / "nutrition.sqlite")
    try:
        initialize_database(connection)

        thread_id = create_chat_thread(connection, title="Lunch plan")
        add_chat_message(connection, thread_id, "user", "100g egg")
        add_chat_message(
            connection,
            thread_id,
            "assistant",
            "Egg nutrition by ingredient.",
            tool_activity=["Looked up **egg**."],
            raw={"messages": [{"role": "assistant", "content": "Egg nutrition by ingredient."}]},
        )

        threads = list_chat_threads(connection)
        messages = list_chat_messages(connection, thread_id)
    finally:
        connection.close()

    assert threads == [
        {
            "id": thread_id,
            "title": "Lunch plan",
            "created_at": threads[0]["created_at"],
            "updated_at": threads[0]["updated_at"],
            "message_count": 2,
        }
    ]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "100g egg"
    assert messages[1]["tool_activity"] == ["Looked up **egg**."]
    assert messages[1]["raw"]["messages"][0]["content"] == "Egg nutrition by ingredient."
