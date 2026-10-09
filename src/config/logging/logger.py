"""Centralized application logging configuration.

The application uses Rich output for local development and a plain,
timestamped stream handler for higher environments.  Both configurations use
``logging.config.dictConfig`` so applications can select the environment at
startup without configuring handlers in individual modules.
"""

from __future__ import annotations

from copy import deepcopy
import logging
import os
from logging.config import dictConfig
from typing import Any

DEFAULT_ENVIRONMENT = "local"
LOCAL_ENVIRONMENTS = frozenset({"dev", "development", "local"})

LOCAL_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "rich": {
            "format": "%(message)s",
            "datefmt": "[%X]",
        },
    },
    "handlers": {
        "console": {
            "class": "rich.logging.RichHandler",
            "level": "INFO",
            "formatter": "rich",
            "rich_tracebacks": True,
            "show_path": False,
            "markup": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

HIGHER_ENV_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": (
                "%(asctime)s %(levelname)s %(name)s "
                "[%(process)d:%(threadName)s] %(message)s"
            ),
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


def _environment_name(environment: str | None) -> str:
    """Resolve an environment name from an argument or process environment."""

    return (
        environment
        or os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or DEFAULT_ENVIRONMENT
    ).strip().lower()


def _log_level(level: str | int | None) -> str | int:
    """Resolve a valid logging level, falling back to ``INFO``."""

    configured_level = level if level is not None else os.getenv("LOG_LEVEL", "INFO")
    if isinstance(configured_level, int):
        return configured_level

    normalized_level = configured_level.strip().upper()
    if normalized_level in logging.getLevelNamesMapping():
        return normalized_level
    return "INFO"


def _local_fallback_config() -> dict[str, Any]:
    """Return a local config that works when the optional Rich package is absent."""

    config = deepcopy(LOCAL_LOGGING_CONFIG)
    config["formatters"]["standard"] = deepcopy(
        HIGHER_ENV_LOGGING_CONFIG["formatters"]["standard"]
    )
    config["handlers"]["console"].update(
        {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    )
    config["handlers"]["console"].pop("rich_tracebacks", None)
    config["handlers"]["console"].pop("show_path", None)
    config["handlers"]["console"].pop("markup", None)
    return config


def get_logging_config(
    environment: str | None = None,
    *,
    level: str | int | None = None,
) -> dict[str, Any]:
    """Return a fresh dictConfig mapping for the requested environment.

    ``local``, ``dev``, and ``development`` select the Rich configuration.
    Any other environment selects the higher-environment configuration.
    ``LOG_LEVEL`` can override the default level, or callers can pass
    ``level`` directly.
    """

    environment_name = _environment_name(environment)
    source = (
        LOCAL_LOGGING_CONFIG
        if environment_name in LOCAL_ENVIRONMENTS
        else HIGHER_ENV_LOGGING_CONFIG
    )
    config = deepcopy(source)
    resolved_level = _log_level(level)
    config["root"]["level"] = resolved_level
    for handler in config["handlers"].values():
        handler["level"] = resolved_level
    return config


def configure_logging(
    environment: str | None = None,
    *,
    level: str | int | None = None,
) -> None:
    """Configure the process logger for local or higher environments."""

    resolved_environment = _environment_name(environment)
    config = get_logging_config(resolved_environment, level=level)

    if resolved_environment in LOCAL_ENVIRONMENTS:
        try:
            from rich.logging import RichHandler  # noqa: F401
        except ImportError:
            config = _local_fallback_config()
            resolved_level = _log_level(level)
            config["root"]["level"] = resolved_level
            for handler in config["handlers"].values():
                handler["level"] = resolved_level

    dictConfig(config)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a named application logger without configuring global handlers."""

    return logging.getLogger(name or "agents-intro")
