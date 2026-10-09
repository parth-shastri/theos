"""Dispatch durable scheduled occurrences through the normal agent runtime."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from harness import AssistantMessage
from theos.storage.telegram_access import account_access

logger = logging.getLogger("theos")


class ScheduledTasks:
    """Own background turn delivery without retrying interrupted agent work."""

    def __init__(self, runtime, telegram=None):
        self.runtime = runtime
        self.db = runtime.db
        self.telegram = telegram
        self.workers = set()

    def allowed(self, session):
        settings = self.runtime.settings
        if session["channel"] == "terminal":
            return session["owner"].startswith("terminal:")
        if session["channel"] == "browser":
            return session["owner"] in settings.users
        if session["channel"] == "telegram-private":
            return account_access(settings, self.db, session["owner"])
        if session["channel"] == "telegram-group":
            parts = session["owner"].split(":")
            return (
                len(parts) == 4
                and parts[1].lstrip("-").isdigit()
                and int(parts[1]) in settings.telegram_chats
                and account_access(settings, self.db, "telegram:" + parts[3])
            )
        return False

    def tick(self, now):
        """Claim each occurrence once, then advance recurrence from the present time."""
        if self.runtime.closed:
            return
        for row in self.db.rows(
            "SELECT * FROM scheduled_tasks WHERE status='pending' AND due<=? ORDER BY due LIMIT 100",
            (now,),
        ):
            if len(self.workers) >= self.runtime.settings.max_concurrent_turns:
                break
            session = self.db.session(row["owner"], row["session"])
            if not self.allowed(session):
                self.db.execute(
                    "UPDATE scheduled_tasks SET status='paused' WHERE id=?", (row["id"],)
                )
                continue
            if session["channel"].startswith("telegram-") and self.telegram is None:
                continue
            if (
                session["id"] in self.runtime.active
                or self.runtime.pending(row["owner"], session["id"])
                or session["status"] in {"waiting_for_approval", "budget_exhausted"}
            ):
                continue
            occurrence = row["id"] + ":" + str(row["due"])
            with self.db.transaction():
                inserted = self.db.execute(
                    "INSERT OR IGNORE INTO scheduled_runs(id,task_id,session,due,status,started) "
                    "VALUES (?,?,?,?,'running',?)",
                    (occurrence, row["id"], session["id"], row["due"], now),
                ).rowcount
                if row["cron"]:
                    base = datetime.fromtimestamp(now, UTC).astimezone(ZoneInfo(row["timezone"]))
                    due = croniter(row["cron"], base).get_next(datetime).timestamp()
                    self.db.execute("UPDATE scheduled_tasks SET due=? WHERE id=?", (due, row["id"]))
                else:
                    self.db.execute(
                        "UPDATE scheduled_tasks SET status='completed' WHERE id=?", (row["id"],)
                    )
                if not inserted:
                    continue
                turn = self.runtime.start(
                    row["owner"],
                    session["id"],
                    f"Scheduled task: {row['name']}\n{row['prompt']}",
                    scheduled=True,
                )
            worker = asyncio.create_task(self.deliver(turn, session, occurrence))
            self.workers.add(worker)
            worker.add_done_callback(self.workers.discard)

    async def deliver(self, turn, session, occurrence):
        """Keep generation separate from transport failure and preserve execution status."""
        try:
            if session["channel"].startswith("telegram-"):
                self.db.execute(
                    "UPDATE scheduled_runs SET delivery='sending' WHERE id=?", (occurrence,)
                )
                chat, topic = session["address"].split(":")
                await self.telegram.render(turn, int(chat), int(topic) or None)
            else:
                async for _ in turn.events():
                    pass
                history = self.db.load_history(turn.owner, turn.session_id)
                status = self.db.session(turn.owner, turn.session_id)["status"]
                text = (
                    history[-1].text
                    if status == "completed"
                    and history
                    and isinstance(history[-1], AssistantMessage)
                    and history[-1].text
                    else f"Scheduled task ended with status: {status}. Open the conversation to continue."
                )
                self.db.execute(
                    "INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,0)",
                    ("task:" + occurrence, turn.owner, turn.session_id, text[:4000], time.time()),
                )
            self.db.execute(
                "UPDATE scheduled_runs SET delivery='delivered' WHERE id=?", (occurrence,)
            )
        except asyncio.CancelledError:
            self.db.execute(
                "UPDATE scheduled_runs SET delivery='uncertain' WHERE id=?", (occurrence,)
            )
            raise
        except Exception:
            self.db.execute(
                "UPDATE scheduled_runs SET delivery='uncertain' WHERE id=?", (occurrence,)
            )
            logger.warning("scheduled_delivery_uncertain")
        finally:
            # A send failure must never start a second agent turn.
            if not turn.task.done():
                await asyncio.shield(turn.task)

    async def close(self):
        workers = list(self.workers)
        for worker in workers:
            worker.cancel()
        # Cancel active scheduled model work before awaiting delivery cleanup.
        for row in self.db.rows("SELECT session FROM scheduled_runs WHERE status='running'"):
            turn = self.runtime.active.get(row["session"])
            if turn:
                turn.task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
