"""One scheduler for reminders, agent tasks, memory consolidation, and health work."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from theos.services.phone_calls import REMINDER_WINDOW

logger = logging.getLogger("theos")


class Scheduler:
    """Commit reminder occurrences before external delivery."""

    def __init__(self, runtime, telegram=None):
        self.runtime = runtime
        self.db = runtime.db
        self.telegram = telegram
        self.stopping = asyncio.Event()
        self.last_tick = 0.0
        self.health_task = None
        self.memory_task = None
        self.github_task = None
        self.phone_task = None
        self.spoken_task = None
        from .scheduled import ScheduledTasks

        self.scheduled = ScheduledTasks(runtime, telegram)

    def reminders(self, now):
        """Save due reminder occurrences and advance recurring schedules."""
        for row in self.db.rows(
            "SELECT * FROM reminders WHERE status='pending' AND due<=? ORDER BY due LIMIT 100",
            (now,),
        ):
            # The occurrence ID prevents duplicate inbox items across scheduler restarts.
            occurrence = row["id"] + ":" + str(row["due"])
            with self.db.transaction():
                saved = self.db.execute(
                    "INSERT OR IGNORE INTO notifications(id,owner,session,text,created,delivered) VALUES (?,?,?,?,?,0)",
                    (occurrence, row["owner"], row["session"], row["text"], now),
                )
                if saved.rowcount and row["delivery"] == "phone":
                    self.runtime.phone_calls.enqueue(
                        occurrence,
                        row["owner"],
                        row["session"],
                        "reminder",
                        row["id"],
                        row["due"],
                        row["due"] + REMINDER_WINDOW,
                    )
                # Advance from now, rather than sending a backlog after downtime.
                if row["cron"]:
                    base = datetime.fromtimestamp(now, UTC).astimezone(ZoneInfo(row["timezone"]))
                    due = croniter(row["cron"], base).get_next(datetime).timestamp()
                    self.db.execute("UPDATE reminders SET due=? WHERE id=?", (due, row["id"]))
                else:
                    self.db.execute(
                        "UPDATE reminders SET status='completed' WHERE id=?", (row["id"],)
                    )

    async def notifications(self):
        """Deliver pending Telegram reminders without retrying uncertain sends."""
        if not self.telegram:
            return
        for row in self.db.rows(
            "SELECT n.*,s.channel,s.address FROM notifications n JOIN sessions s ON s.id=n.session WHERE n.delivered=0 AND s.channel LIKE 'telegram-%' LIMIT 20"
        ):
            # Claim before sending. Recovery treats an interrupted send as uncertain.
            self.db.execute("UPDATE notifications SET delivered=2 WHERE id=?", (row["id"],))
            try:
                chat, topic = row["address"].split(":")
                await self.telegram.send(int(chat), row["text"], int(topic) or None)
            except Exception as error:
                # Telegram has no send idempotency key. Keep uncertain deliveries for manual review.
                self.db.execute("UPDATE notifications SET delivered=-1 WHERE id=?", (row["id"],))
                logger.error("notification_failed", extra={"error_type": type(error).__name__})
            else:
                self.db.execute("UPDATE notifications SET delivered=1 WHERE id=?", (row["id"],))

    async def tick(self):
        """Advance due work and launch independent Health and memory batches."""
        self.last_tick = time.time()
        # 1. Save due occurrences before delivery so a restart cannot create duplicates.
        self.reminders(self.last_tick)
        self.scheduled.tick(self.last_tick)
        self.db.execute(
            "UPDATE approvals SET status='expired' WHERE status='pending' AND expires<?",
            (self.last_tick,),
        )
        if self.phone_task is None or self.phone_task.done():
            self.phone_task = asyncio.create_task(self.phone_work(self.last_tick))
        if self.spoken_task is None or self.spoken_task.done():
            self.spoken_task = asyncio.create_task(self.spoken_work())
        # 2. Deliver saved notifications. Keep uncertain sends for review.
        await self.notifications()
        if self.github_task is None or self.github_task.done():
            self.github_task = asyncio.create_task(self.github_work())
        # 3. Start at most one Health batch so slow imports cannot block reminders.
        if self.runtime.settings.health.enabled and (
            self.health_task is None or self.health_task.done()
        ):
            # A slow import must not delay reminder delivery. Only one health batch can run.
            self.health_task = asyncio.create_task(self.health_work())
        if self.memory_task is None or self.memory_task.done():
            self.memory_task = asyncio.create_task(self.memory_work())

    async def github_work(self):
        """Keep signed-event processing separate from reminder delivery."""
        try:
            await self.runtime.github_events.tick(self.telegram)
        except Exception:
            logger.warning("github_notifications_failed")

    async def phone_work(self, now):
        """Keep speech generation and dialing independent of reminder messages."""
        try:
            await self.runtime.phone_calls.tick(now)
        except Exception:
            logger.warning("phone_call_worker_failed")

    async def spoken_work(self):
        """Process voice turns independently of speech generation for other calls."""
        try:
            await self.runtime.call_conversations.tick(self.telegram)
        except Exception as error:
            logger.warning(
                "spoken_approval_worker_failed", extra={"error_type": type(error).__name__}
            )

    async def memory_work(self):
        """Isolate optional consolidation from reminder and scheduled-task delivery."""
        try:
            await self.runtime.memory_automation.consolidate()
        except Exception:
            logger.warning("memory_consolidation_failed")

    async def health_work(self):
        """Keep Health failures inside their background task."""
        try:
            await self.runtime.health.tick()
        except Exception as error:
            logger.error("scheduler_failed", extra={"error_type": type(error).__name__})

    async def close(self):
        """Stop background workers before their database and HTTP client close."""
        self.stopping.set()
        await self.scheduled.close()
        if self.phone_task is not None:
            self.phone_task.cancel()
            await asyncio.gather(self.phone_task, return_exceptions=True)
        if self.spoken_task is not None:
            self.spoken_task.cancel()
            await asyncio.gather(self.spoken_task, return_exceptions=True)
        if self.github_task is not None:
            self.github_task.cancel()
            await asyncio.gather(self.github_task, return_exceptions=True)
        if self.memory_task is not None:
            self.memory_task.cancel()
            await asyncio.gather(self.memory_task, return_exceptions=True)
        if self.health_task is not None:
            self.health_task.cancel()
            await asyncio.gather(self.health_task, return_exceptions=True)

    async def run(self):
        """Run periodic work until shutdown or cancellation."""
        while not self.stopping.is_set():
            try:
                await self.tick()
            except Exception as error:
                # One failed integration must not disable all future reminder deliveries.
                logger.error("scheduler_failed", extra={"error_type": type(error).__name__})
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=1)
            except TimeoutError:
                pass
