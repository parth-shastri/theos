"""Errors that integrations can safely show to a user."""


class ServiceError(RuntimeError):
    """An integration error that is safe to show without remote response bodies."""
