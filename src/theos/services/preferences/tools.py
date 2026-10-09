"""User preferences and instruction overrides."""

from typing import Literal
from zoneinfo import ZoneInfo

from harness import tool


def preferences(db, owner, default_timezone="UTC"):
    """Read preferences without creating a record during a read."""
    try:
        return db.record(owner, "preferences", "settings")
    except LookupError:
        return {"timezone": default_timezone, "calorie_goal": 2000}


def preference_tools(db, owner, default_timezone):
    """Build preference tools bound to the authenticated owner."""

    def user_preferences():
        return preferences(db, owner, default_timezone)

    @tool
    async def set_preference(
        name: Literal["timezone", "calorie_goal", "instructions", "display_name"], value: str
    ):
        """Set your timezone, calorie goal, display name, or instruction override."""
        current = user_preferences()
        if name == "timezone":
            ZoneInfo(value)
        if name == "calorie_goal":
            value = int(value)
            if not 100 <= value <= 20000:
                raise ValueError("Use a calorie goal from 100 to 20000.")
        if len(str(value)) > 8000:
            raise ValueError("The preference is too long.")
        current[name] = value
        return db.put_record(owner, "preferences", "settings", current)

    @tool
    async def get_preferences():
        """Read your preferences and instruction override."""
        return user_preferences()

    return [set_preference, get_preferences]
