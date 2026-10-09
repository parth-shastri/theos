"""One-time and recurring reminders."""

import time
from datetime import datetime
from uuid import uuid4

from croniter import croniter

from harness import tool
from theos.services.preferences.tools import preferences

from .timezones import local_time


def reminder_tools(db, owner, session_id, default_timezone):
    """Build reminder tools bound to the owner and delivery conversation."""

    def user_preferences():
        return preferences(db, owner, default_timezone)

    @tool
    async def schedule_reminder(
        text: str, due: datetime, recurrence: str | None = None, timezone: str | None = None
    ):
        """Schedule a reminder. Recurrence is a five-field cron expression in your timezone."""
        zone = timezone or user_preferences()["timezone"]
        when = local_time(due, zone)
        if len(text) > 4000 or not text.strip():
            raise ValueError("Supply reminder text from 1 to 4000 characters.")
        if recurrence:
            if len(recurrence.split()) != 5 or not croniter.is_valid(recurrence):
                raise ValueError("Use a valid five-field cron expression.")
            when = croniter(recurrence, when).get_next(datetime)
        if when.timestamp() <= time.time():
            raise ValueError("The reminder time must be in the future.")
        reminder_id = uuid4().hex
        db.execute(
            "INSERT INTO reminders(id,owner,session,text,due,cron,timezone) VALUES (?,?,?,?,?,?,?)",
            (reminder_id, owner, session_id, text, when.timestamp(), recurrence, zone),
        )
        return {"id": reminder_id, "due": when.isoformat(), "recurrence": recurrence}

    @tool
    async def list_reminders():
        """List your pending reminders and their delivery status."""
        return db.rows("SELECT * FROM reminders WHERE owner=? ORDER BY due LIMIT 200", (owner,))

    @tool
    async def cancel_reminder(reminder_id: str):
        """Cancel one of your reminders."""
        count = db.execute(
            "UPDATE reminders SET status='cancelled' WHERE id=? AND owner=?", (reminder_id, owner)
        ).rowcount
        if not count:
            raise LookupError("Reminder not found.")
        return {"cancelled": reminder_id}

    return [schedule_reminder, list_reminders, cancel_reminder]
