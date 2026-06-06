from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_status (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_version TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS food_categories (
  id INTEGER PRIMARY KEY,
  description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS foods (
  fdc_id INTEGER PRIMARY KEY,
  description TEXT NOT NULL,
  data_type TEXT,
  food_category_id INTEGER,
  publication_date TEXT,
  search_name TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY (food_category_id) REFERENCES food_categories(id)
);

CREATE TABLE IF NOT EXISTS nutrients (
  id INTEGER PRIMARY KEY,
  number TEXT,
  name TEXT NOT NULL,
  unit_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS food_nutrients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fdc_id INTEGER NOT NULL,
  nutrient_id INTEGER NOT NULL,
  amount REAL,
  derivation_code TEXT,
  FOREIGN KEY (fdc_id) REFERENCES foods(fdc_id) ON DELETE CASCADE,
  FOREIGN KEY (nutrient_id) REFERENCES nutrients(id)
);

CREATE TABLE IF NOT EXISTS food_portions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fdc_id INTEGER NOT NULL,
  amount REAL,
  measure_unit_name TEXT,
  modifier TEXT,
  gram_weight REAL,
  FOREIGN KEY (fdc_id) REFERENCES foods(fdc_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingredient_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  original_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  fdc_id INTEGER,
  confidence REAL NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (fdc_id) REFERENCES foods(fdc_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_foods_search_name ON foods(search_name);
CREATE INDEX IF NOT EXISTS idx_foods_description ON foods(description);
CREATE INDEX IF NOT EXISTS idx_food_nutrients_fdc_id ON food_nutrients(fdc_id);
CREATE INDEX IF NOT EXISTS idx_food_portions_fdc_id ON food_portions(fdc_id);
CREATE INDEX IF NOT EXISTS idx_aliases_original_name ON ingredient_aliases(original_name);
CREATE INDEX IF NOT EXISTS idx_aliases_normalized_name ON ingredient_aliases(normalized_name);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 60000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()


def has_successful_import(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM import_status WHERE source_name = ? AND status = ? LIMIT 1",
        ("USDA FoodData Central JSON dump", "completed"),
    ).fetchone()
    return row is not None


def latest_import_status(connection: sqlite3.Connection) -> dict[str, object] | None:
    row = connection.execute(
        """
        SELECT source_name, source_path, source_version, started_at, completed_at, status, error_message
        FROM import_status
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def record_import_started(
    connection: sqlite3.Connection,
    source_name: str,
    source_path: str,
    source_version: str | None = None,
    status: str = "running",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO import_status
          (source_name, source_path, source_version, started_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_name, source_path, source_version, now, status),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_import_status(
    connection: sqlite3.Connection,
    import_id: int,
    status: str,
    *,
    source_path: str | None = None,
    source_version: str | None = None,
    error_message: str | None = None,
    completed: bool = False,
) -> None:
    completed_at = datetime.now(timezone.utc).isoformat() if completed else None
    connection.execute(
        """
        UPDATE import_status
        SET
          source_path = COALESCE(?, source_path),
          source_version = COALESCE(?, source_version),
          completed_at = ?,
          status = ?,
          error_message = ?
        WHERE id = ?
        """,
        (source_path, source_version, completed_at, status, error_message, import_id),
    )
    connection.commit()


def record_import_failure(
    connection: sqlite3.Connection,
    source_name: str,
    source_path: str,
    error_message: str,
) -> None:
    import_id = record_import_started(connection, source_name, source_path, "download-failed")
    update_import_status(connection, import_id, "failed", error_message=error_message, completed=True)
