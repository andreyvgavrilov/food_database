from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def create_chat_thread(connection: sqlite3.Connection, title: str | None = None) -> int:
    now = _now()
    cursor = connection.execute(
        """
        INSERT INTO chat_threads (title, created_at, updated_at)
        VALUES (?, ?, ?)
        """,
        ((title or "New chat").strip() or "New chat", now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_chat_thread(connection: sqlite3.Connection, thread_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, title, created_at, updated_at
        FROM chat_threads
        WHERE id = ?
        """,
        (thread_id,),
    ).fetchone()
    return dict(row) if row else None


def list_chat_threads(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
          chat_threads.id,
          chat_threads.title,
          chat_threads.created_at,
          chat_threads.updated_at,
          COUNT(chat_messages.id) AS message_count
        FROM chat_threads
        LEFT JOIN chat_messages ON chat_messages.thread_id = chat_threads.id
        GROUP BY chat_threads.id
        ORDER BY chat_threads.updated_at DESC, chat_threads.id DESC
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"]),
        }
        for row in rows
    ]


def add_chat_message(
    connection: sqlite3.Connection,
    thread_id: int,
    role: str,
    content: str,
    *,
    tool_activity: list[str] | None = None,
    raw: Any | None = None,
) -> int:
    now = _now()
    cursor = connection.execute(
        """
        INSERT INTO chat_messages (thread_id, role, content, tool_activity, raw_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            thread_id,
            role,
            content,
            json.dumps(tool_activity or [], ensure_ascii=False),
            json.dumps(raw, ensure_ascii=False) if raw is not None else None,
            now,
        ),
    )
    connection.execute(
        """
        UPDATE chat_threads
        SET updated_at = ?
        WHERE id = ?
        """,
        (now, thread_id),
    )
    connection.commit()
    return int(cursor.lastrowid)


def list_chat_messages(connection: sqlite3.Connection, thread_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, thread_id, role, content, tool_activity, raw_json, created_at
        FROM chat_messages
        WHERE thread_id = ?
        ORDER BY id ASC
        """,
        (thread_id,),
    ).fetchall()
    return [_message_from_row(row) for row in rows]


def _message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "thread_id": int(row["thread_id"]),
        "role": row["role"],
        "content": row["content"],
        "tool_activity": _json_or_default(row["tool_activity"], []),
        "raw": _json_or_default(row["raw_json"], None),
        "created_at": row["created_at"],
    }


def _json_or_default(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
