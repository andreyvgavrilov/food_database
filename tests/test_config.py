from app.config import load_settings


def test_load_settings_from_env_mapping(tmp_path):
    settings = load_settings(
        {
            "DATABASE_URL": "sqlite:///./data/test.sqlite",
            "OLLAMA_BASE_URL": "https://ollama.example.test",
            "OLLAMA_MODEL": "qwen2.5",
            "OLLAMA_API_KEY": "secret",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
            "AUTO_IMPORT_USDA_ON_FIRST_RUN": "false",
        }
    )

    assert settings.ollama_base_url == "https://ollama.example.test"
    assert settings.ollama_model == "qwen2.5"
    assert settings.ollama_api_key == "secret"
    assert settings.auto_import_usda_on_first_run is False
    assert settings.usda_json_dump_path == tmp_path
    assert settings.usda_download_data_types == ("Foundation Foods", "SR Legacy", "FNDDS")


def test_load_settings_loads_env_file_into_process_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OLLAMA_BASE_URL=https://ollama.example.test",
                "OLLAMA_MODEL=env-file-model",
                "OLLAMA_API_KEY=env-file-secret",
                f"USDA_JSON_DUMP_PATH={tmp_path.as_posix()}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("USDA_JSON_DUMP_PATH", raising=False)

    settings = load_settings(env_file=env_file)

    assert settings.ollama_base_url == "https://ollama.example.test"
    assert settings.ollama_model == "env-file-model"
    assert settings.ollama_api_key == "env-file-secret"
    assert settings.usda_json_dump_path == tmp_path
    assert __import__("os").environ["OLLAMA_MODEL"] == "env-file-model"
