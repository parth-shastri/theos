"""Meal records, daily totals, and nutrition export intent."""

from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from harness import tool
from theos.services.health.queue import queue_nutrition
from theos.services.preferences.tools import preferences
from theos.services.reminders.timezones import local_time

from .models import Meal


def meal_tools(db, owner, default_timezone):
    """Build meal tools bound to the authenticated owner."""

    def user_preferences():
        return preferences(db, owner, default_timezone)

    def save_meal(meal_id, meal):
        value = Meal.model_validate(meal).model_dump(mode="json")
        value["eaten_at"] = local_time(
            datetime.fromisoformat(value["eaten_at"]), user_preferences()["timezone"]
        ).isoformat()
        # Save the meal change and export intent together so neither can be lost alone.
        with db.transaction():
            result = db.put_record(owner, "meal", meal_id, value)
            queue_nutrition(db, owner, meal_id, value)
        return result

    @tool
    async def log_meal(meal: Meal):
        """Save a meal with calories, nutrients, and the time you ate it."""
        return save_meal(uuid4().hex, meal)

    @tool
    async def edit_meal(meal_id: str, meal: Meal):
        """Replace a saved meal and queue its nutrition export."""
        # Read with the owner before replacing an existing meal.
        db.record(owner, "meal", meal_id)
        return save_meal(meal_id, meal)

    @tool
    async def delete_meal(meal_id: str):
        """Delete a meal and queue deletion of its exported nutrition record."""
        meal = db.record(owner, "meal", meal_id)
        # Save the meal change and export intent together so neither can be lost alone.
        with db.transaction():
            result = db.delete_record(owner, "meal", meal_id)
            queue_nutrition(db, owner, meal_id, meal, "delete")
        return result

    @tool
    async def get_calorie_summary(day: date | None = None):
        """List meals and nutrient totals for a day in your timezone."""
        zone = ZoneInfo(user_preferences()["timezone"])
        selected = day or datetime.now(zone).date()
        meals = [
            meal
            for meal in db.records(owner, "meal")
            if datetime.fromisoformat(meal["eaten_at"]).astimezone(zone).date() == selected
        ]
        return {
            "day": str(selected),
            "goal": user_preferences()["calorie_goal"],
            "meals": meals,
            "missing_nutrients": {
                key: sum(meal.get(key) is None for meal in meals)
                for key in ("protein", "carbohydrates", "fat")
            },
            "totals": {
                nutrient: sum(meal[nutrient] or 0 for meal in meals)
                for nutrient in ("calories", "protein", "carbohydrates", "fat")
            },
        }

    return [log_meal, edit_meal, delete_meal, get_calorie_summary]
