from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


RETENTION_PERIOD = timedelta(days=1)
_write_lock = threading.Lock()


class InteractionLogger:
    def __init__(self, logs_path: Path):
        self.logs_path = logs_path

    def write(self, kind: str, name: str, payload: dict[str, Any]) -> None:
        try:
            self.prune_old_logs()
            self.logs_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc)
            entry = {
                "timestamp": timestamp.isoformat(),
                "kind": kind,
                "name": name,
                "payload": _json_safe(payload),
            }
            path = self.logs_path / f"interactions-{timestamp.date().isoformat()}.jsonl"
            line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            with _write_lock:
                with path.open("a", encoding="utf-8") as file:
                    file.write(line + "\n")
        except Exception:
            return

    def prune_old_logs(self) -> None:
        try:
            if not self.logs_path.exists():
                return
            cutoff = datetime.now(timezone.utc) - RETENTION_PERIOD
            for path in self.logs_path.iterdir():
                if not path.is_file():
                    continue
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                if modified_at < cutoff:
                    path.unlink()
        except Exception:
            return


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"))
        except TypeError:
            return _json_safe(model_dump())
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
