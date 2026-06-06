from app.db import connect


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
