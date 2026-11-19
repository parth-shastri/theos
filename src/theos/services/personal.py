"""Compose personal tools while each service owns its records and validation."""

from .meals.tools import meal_tools
from .preferences.tools import preference_tools
from .reminders.tools import reminder_tools
from .training.tools import training_tools


def personal_tools(db, owner, session_id, default_timezone, *, phone_enabled=False):
    """Use the server's owner identity for every personal service."""
    return [
        *preference_tools(db, owner, default_timezone),
        *reminder_tools(db, owner, session_id, default_timezone, phone_enabled=phone_enabled),
        *meal_tools(db, owner, default_timezone),
        *training_tools(db, owner, default_timezone),
    ]
