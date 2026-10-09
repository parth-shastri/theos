"""Tests for the application's environment-specific logging setup."""

from __future__ import annotations

import config.logging.logger as logging_module


def test_local_and_higher_configs_use_different_handlers():
    local = logging_module.get_logging_config("local")
    higher = logging_module.get_logging_config("production")

    assert local["handlers"]["console"]["class"] == "rich.logging.RichHandler"
    assert higher["handlers"]["console"]["class"] == "logging.StreamHandler"
    assert local["handlers"]["console"]["formatter"] == "rich"
    assert higher["handlers"]["console"]["formatter"] == "standard"


def test_environment_variables_select_environment_and_level(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    config = logging_module.get_logging_config()

    assert config["root"]["level"] == "DEBUG"
    assert config["handlers"]["console"]["level"] == "DEBUG"
    assert config["handlers"]["console"]["class"] == "logging.StreamHandler"


def test_configure_logging_passes_dict_config_to_logging_module(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(logging_module, "dictConfig", captured.append)

    logging_module.configure_logging("development", level="WARNING")

    assert captured[0]["root"]["level"] == "WARNING"
    assert captured[0]["handlers"]["console"]["class"] == (
        "rich.logging.RichHandler"
    )
