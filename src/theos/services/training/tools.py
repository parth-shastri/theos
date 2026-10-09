"""Training programs, workout history, and measured results."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

from harness import tool
from theos.services.preferences.tools import preferences
from theos.services.reminders.timezones import local_time

from .models import Exercise, TrainingDay, TrainingType


def training_tools(db, owner, default_timezone):
    """Build training tools bound to the authenticated owner."""

    def user_preferences():
        return preferences(db, owner, default_timezone)

    @tool
    async def set_training_program(
        name: str,
        days: Annotated[list[TrainingDay | list[Exercise]], Field(min_length=1, max_length=31)],
        current_day: int = 1,
        current_week: int = 1,
        deload_every_weeks: int = 5,
        notes: str = "",
    ):
        """Save a rotating program with resistance, cardio, recovery, and rest days."""
        if (
            not 1 <= current_day <= len(days)
            or not 1 <= current_week <= 1000
            or not 1 <= deload_every_weeks <= 100
        ):
            raise ValueError("The program day, week, or deload interval is invalid.")
        normalized = []
        for day in days:
            if isinstance(day, list):
                day = {"exercises": day, "session_type": "resistance" if day else "rest"}
            normalized.append(TrainingDay.model_validate(day).model_dump())
        try:
            version = db.record(owner, "training", "program").get("version", 0) + 1
        except LookupError:
            version = 1
        program = {
            "name": name,
            "days": normalized,
            "position": current_day - 1,
            "week": current_week,
            "elapsed_days": (current_week - 1) * 7,
            "deload_every_weeks": deload_every_weeks,
            "version": version,
            "notes": notes,
        }
        # Preserve the old prescription so past workouts still refer to their original program.
        with db.transaction():
            db.put_record(owner, "training_version", str(version), program)
            return db.put_record(owner, "training", "program", program)

    def training_history(cycle_day=None, session_type=None, exercise=None, limit=50):
        rows = db.records(owner, "workout")
        return [
            row
            for row in rows
            if (cycle_day is None or row.get("cycle_day") == cycle_day)
            and (session_type is None or row.get("session_type") == session_type)
            and (
                exercise is None
                or any(e["name"].casefold() == exercise.casefold() for e in row["exercises"])
            )
        ][: max(1, min(200, limit))]

    @tool
    async def get_todays_training():
        """Read today's prescription, deload state, and last comparable workout."""
        program = db.record(owner, "training", "program")
        day = program["days"][program["position"]]
        history = training_history(program["position"] + 1, day["session_type"], limit=1)
        return {
            "name": program["name"],
            "position": program["position"],
            "week": program["week"],
            "deload": program["week"] % program["deload_every_weeks"] == 0,
            **day,
            "last_comparable_session": history[0] if history else None,
        }

    def advance():
        program = db.record(owner, "training", "program")
        # Cycle length and calendar week are separate counters for programs shorter than seven days.
        program["position"] = (program["position"] + 1) % len(program["days"])
        program["elapsed_days"] += 1
        program["week"] = program["elapsed_days"] // 7 + 1
        return db.put_record(owner, "training", "program", program)

    @tool
    async def advance_training_cycle():
        """Advance the training program by one day, including its week counter."""
        return advance()

    @tool
    async def log_training(
        exercises: list[Exercise],
        performed_at: datetime,
        notes: str = "",
        session_type: TrainingType = "resistance",
        cycle_day: int | None = None,
        completion_status: Literal["planned", "completed", "partial", "skipped"] = "completed",
        metrics: dict[str, float] | None = None,
        advance_cycle: bool = False,
    ):
        """Save training results, per-set details, metrics, and completion status."""
        when = local_time(performed_at, user_preferences()["timezone"])
        try:
            program = db.record(owner, "training", "program")
        except LookupError:
            program = None
        if advance_cycle and program is None:
            raise ValueError("Save a program before you advance its cycle.")
        value = {
            "exercises": [Exercise.model_validate(e).model_dump() for e in exercises],
            "performed_at": when.isoformat(),
            "notes": notes,
            "session_type": session_type,
            "cycle_day": cycle_day or (program["position"] + 1 if program else None),
            "program_version": program["version"] if program else None,
            "completion_status": completion_status,
            "metrics": metrics or {},
        }
        # Commit the workout and optional cycle advance together to avoid skipped training days.
        with db.transaction():
            saved = db.put_record(owner, "workout", uuid4().hex, value)
            if advance_cycle:
                saved["advanced_state"] = advance()
            return saved

    @tool
    async def get_training_history(
        cycle_day: int | None = None,
        session_type: TrainingType | None = None,
        exercise: str | None = None,
        limit: int = 50,
    ):
        """List comparable workouts by cycle day, session type, or exercise."""
        return training_history(cycle_day, session_type, exercise, limit)

    @tool
    async def delete_workout(workout_id: str):
        """Delete one of your saved workouts."""
        return db.delete_record(owner, "workout", workout_id)

    @tool
    async def update_training_metrics(name: str, value: float, unit: str, measured_at: datetime):
        """Record a training metric with an explicit unit and measurement time."""
        return db.put_record(
            owner,
            "metric",
            uuid4().hex,
            {
                "name": name,
                "value": value,
                "unit": unit,
                "measured_at": local_time(measured_at, user_preferences()["timezone"]).isoformat(),
            },
        )

    @tool
    async def get_training_metrics():
        """List your training metrics and measurement history."""
        return db.records(owner, "metric")

    return [
        set_training_program,
        get_todays_training,
        advance_training_cycle,
        log_training,
        get_training_history,
        delete_workout,
        update_training_metrics,
        get_training_metrics,
    ]
