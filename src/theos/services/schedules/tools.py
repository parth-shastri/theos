"""Owner-scoped creation and control of scheduled agent tasks."""

import time
from datetime import datetime
from uuid import uuid4

from croniter import croniter

from harness import tool
from theos.services.preferences.tools import preferences
from theos.services.reminders.timezones import local_time


def task_tools(db, owner, session_id, settings):
    """Bind task execution and delivery to the creating conversation."""

    def owned(task_id):
        row = db.one("SELECT * FROM scheduled_tasks WHERE id=? AND owner=?", (task_id, owner))
        if row is None:
            raise LookupError("Scheduled task not found.")
        return row

    def next_due(due, recurrence, timezone):
        when = local_time(due, timezone)
        if recurrence:
            if len(recurrence.split()) != 5 or not croniter.is_valid(recurrence):
                raise ValueError("Use a valid five-field cron expression.")
            when = croniter(recurrence, when).get_next(datetime)
        if when.timestamp() <= time.time():
            raise ValueError("The task time must be in the future.")
        return when

    @tool
    async def schedule_task(
        name: str,
        prompt: str,
        due: datetime,
        recurrence: str | None = None,
        timezone: str | None = None,
    ):
        """Schedule an agent task only at the user's request. Recurrence is five-field cron.

        It runs in this conversation with normal tools and approvals. Due is the first
        one-time run, or the exclusive starting time for a recurring cron schedule.
        """
        if not name.strip() or len(name) > 100 or not prompt.strip() or len(prompt) > 8000:
            raise ValueError("Supply a name of 1–100 and a task prompt of 1–8000 characters.")
        count = db.one(
            "SELECT COUNT(*) AS n FROM scheduled_tasks WHERE owner=? AND status IN ('pending','paused')",
            (owner,),
        )["n"]
        if count >= settings.max_scheduled_tasks:
            raise ValueError("The scheduled task limit has been reached. Cancel an unused task.")
        zone = timezone or preferences(db, owner, settings.timezone)["timezone"]
        when = next_due(due, recurrence, zone)
        task_id = uuid4().hex
        db.execute(
            "INSERT INTO scheduled_tasks(id,owner,session,name,prompt,due,cron,timezone,created) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                owner,
                session_id,
                name,
                prompt,
                when.timestamp(),
                recurrence,
                zone,
                time.time(),
            ),
        )
        return {"id": task_id, "name": name, "due": when.isoformat(), "recurrence": recurrence}

    @tool
    async def list_scheduled_tasks():
        """List your agent tasks, including paused, completed, and cancelled schedules."""
        return db.rows(
            "SELECT * FROM scheduled_tasks WHERE owner=? ORDER BY created DESC LIMIT 200", (owner,)
        )

    @tool
    async def pause_scheduled_task(task_id: str):
        """Pause future runs. An already running task is not cancelled."""
        row = owned(task_id)
        if row["status"] in {"cancelled", "completed"}:
            raise ValueError("A completed or cancelled schedule cannot be paused.")
        db.execute("UPDATE scheduled_tasks SET status='paused' WHERE id=?", (task_id,))
        return {"paused": task_id}

    @tool
    async def resume_scheduled_task(task_id: str, due: datetime):
        """Resume a paused schedule from a future time, after reviewing any uncertain run."""
        row = owned(task_id)
        if row["status"] != "paused":
            raise ValueError("Only a paused task can be resumed.")
        when = next_due(due, row["cron"], row["timezone"])
        db.execute(
            "UPDATE scheduled_tasks SET status='pending', due=? WHERE id=?",
            (when.timestamp(), task_id),
        )
        return {"resumed": task_id, "due": when.isoformat()}

    @tool
    async def cancel_scheduled_task(task_id: str):
        """Cancel future runs without deleting history or stopping an active turn."""
        owned(task_id)
        db.execute("UPDATE scheduled_tasks SET status='cancelled' WHERE id=?", (task_id,))
        return {"cancelled": task_id}

    @tool
    async def list_scheduled_runs(task_id: str):
        """Read the latest execution and delivery statuses for one of your tasks."""
        owned(task_id)
        return db.rows(
            "SELECT * FROM scheduled_runs WHERE task_id=? ORDER BY started DESC LIMIT 50",
            (task_id,),
        )

    return [
        schedule_task,
        list_scheduled_tasks,
        pause_scheduled_task,
        resume_scheduled_task,
        cancel_scheduled_task,
        list_scheduled_runs,
    ]
