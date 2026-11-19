"""One-time and recurring reminders."""

import time
from datetime import datetime
from typing import Literal
from uuid import uuid4

from croniter import croniter

from harness import tool
from theos.services.phone_calls import MAX_REMINDER_TEXT
from theos.services.preferences.tools import preferences

from .timezones import local_time


def reminder_tools(
    db, owner, session_id, default_timezone, *, phone_enabled=False, phone_default=False
):
    """Build reminder tools bound to the owner and delivery conversation."""

    def user_preferences():
        return preferences(db, owner, default_timezone)

    def save(text, due, recurrence, timezone, delivery="message"):
        zone = timezone or user_preferences()["timezone"]
        when = local_time(due, zone)
        if len(text) > 4000 or not text.strip():
            raise ValueError("Supply reminder text from 1 to 4000 characters.")
        if delivery == "phone":
            if not phone_enabled:
                raise ValueError("Phone calls are unavailable for this conversation.")
            if len(text.strip()) > MAX_REMINDER_TEXT:
                raise ValueError(
                    f"Use at most {MAX_REMINDER_TEXT} characters for a phone reminder."
                )
        if recurrence:
            if len(recurrence.split()) != 5 or not croniter.is_valid(recurrence):
                raise ValueError("Use a valid five-field cron expression.")
            when = croniter(recurrence, when).get_next(datetime)
        if when.timestamp() <= time.time():
            raise ValueError("The reminder time must be in the future.")
        reminder_id = uuid4().hex
        db.execute(
            "INSERT INTO reminders(id,owner,session,text,due,cron,timezone,delivery) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (reminder_id, owner, session_id, text, when.timestamp(), recurrence, zone, delivery),
        )
        return {
            "id": reminder_id,
            "due": when.isoformat(),
            "recurrence": recurrence,
            "delivery": delivery,
        }

    if phone_enabled:

        @tool
        async def schedule_reminder(
            text: str,
            due: datetime,
            recurrence: str | None = None,
            timezone: str | None = None,
            delivery: Literal["message", "phone"] = "phone" if phone_default else "message",
        ):
            """Schedule a reminder using your saved delivery preference. Use message delivery when requested. Phone text allows 360 characters. Recurrence uses five-field cron."""
            return save(text, due, recurrence, timezone, delivery)

    else:

        @tool
        async def schedule_reminder(
            text: str,
            due: datetime,
            recurrence: str | None = None,
            timezone: str | None = None,
        ):
            """Schedule a message reminder. Recurrence uses five-field cron in your timezone."""
            return save(text, due, recurrence, timezone)

    @tool
    async def list_reminders():
        """List your pending reminders and their delivery status."""
        return db.rows(
            "SELECT r.*, (SELECT c.status FROM phone_calls c "
            "WHERE c.kind='reminder' AND c.source_id=r.id AND c.owner=r.owner "
            "ORDER BY c.due DESC LIMIT 1) AS phone_status "
            "FROM reminders r WHERE r.owner=? ORDER BY r.due LIMIT 200",
            (owner,),
        )

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
