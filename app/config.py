from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT_DIR = Path(__file__).resolve().parent.parent


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    ollama_base_url: str
    ollama_model: str
    ollama_api_key: str | None
    ollama_timeout_seconds: int
    usda_json_dump_path: Path
    usda_download_page_url: str
    usda_download_data_types: tuple[str, ...]
    auto_import_usda_on_first_run: bool

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// DATABASE_URL values are supported")

        raw_path = self.database_url.removeprefix(prefix)
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    @property
    def deepagents_model(self) -> str:
        return f"ollama:{self.ollama_model}"


def load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Settings:
    env_values: dict[str, str] = {}

    try:
        from dotenv import dotenv_values, load_dotenv

        resolved_env_file = env_file or ROOT_DIR / ".env"
        load_dotenv(resolved_env_file, override=False)
        env_values.update({key: str(value) for key, value in dotenv_values(resolved_env_file).items() if value is not None})
    except Exception:
        env_values.update(_read_env_file(env_file or ROOT_DIR / ".env"))

    env_values.update(os.environ)

    if env:
        env_values.update(dict(env))

    dump_path = Path(env_values.get("USDA_JSON_DUMP_PATH", "./data/usda-fooddata-central"))
    if not dump_path.is_absolute():
        dump_path = ROOT_DIR / dump_path

    data_types = tuple(
        item.strip()
        for item in env_values.get("USDA_DOWNLOAD_DATA_TYPES", "Foundation Foods,SR Legacy,FNDDS").split(",")
        if item.strip()
    )

    return Settings(
        app_env=env_values.get("APP_ENV", "development"),
        database_url=env_values.get("DATABASE_URL", "sqlite:///./data/nutrition.sqlite"),
        ollama_base_url=env_values.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=env_values.get("OLLAMA_MODEL", "llama3.1"),
        ollama_api_key=env_values.get("OLLAMA_API_KEY") or None,
        ollama_timeout_seconds=int(env_values.get("OLLAMA_TIMEOUT_SECONDS", "120")),
        usda_json_dump_path=dump_path,
        usda_download_page_url=env_values.get("USDA_DOWNLOAD_PAGE_URL", "https://fdc.nal.usda.gov/download-datasets/"),
        usda_download_data_types=data_types,
        auto_import_usda_on_first_run=_bool(env_values.get("AUTO_IMPORT_USDA_ON_FIRST_RUN"), True),
    )
