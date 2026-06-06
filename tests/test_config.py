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
