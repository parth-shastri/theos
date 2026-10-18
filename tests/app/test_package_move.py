"""The moved application keeps Theos defaults and its own package resources."""

from importlib.resources import files
from pathlib import Path

from theos import DEFAULT_API, DEFAULT_MODEL, DEFAULT_PROVIDER
from theos.settings import Settings


def test_theos_defaults_and_environment_namespace(monkeypatch):
    settings = Settings(_env_file=None)
    assert settings.provider == DEFAULT_PROVIDER == "openai"
    assert settings.model == DEFAULT_MODEL == "gpt-6-luna"
    assert DEFAULT_API == "responses"
    assert settings.data_dir == Path(".theos")
    assert settings.name == "Theos"
    monkeypatch.setenv("AGENT_MODEL", "configured-model")
    monkeypatch.setenv("AGENT_MEMORY__ENABLED", "true")
    configured = Settings(_env_file=None)
    assert configured.model == "configured-model"
    assert configured.memory.enabled


def test_theos_owns_static_files_and_migrations():
    package = files("theos")
    page = (package / "transports/browser/static/index.html").read_text()
    assert "<title>{{AGENT_NAME}} / Personal assistant</title>" in page
    assert (package / "storage/migrations/001_initial.sql").is_file()
