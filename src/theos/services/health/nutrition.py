"""Nutrition backfill and remote record reconciliation."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from theos.services.errors import ServiceError
from theos.services.health.queue import queue_nutrition


def nutrition_payload(meal):
    """Map a meal to Google's NutritionLog format without inventing serving units."""
    start = datetime.fromisoformat(meal["eaten_at"])
    end = start + timedelta(seconds=1)
    offset = str(int(start.utcoffset().total_seconds())) + "s"
    payload = {
        "nutritionLog": {
            "interval": {
                "startTime": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "endTime": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "startUtcOffset": offset,
                "endUtcOffset": offset,
            },
            "foodDisplayName": meal["name"],
            "energy": {"kcal": meal["calories"]},
            "nutrients": [{"nutrient": "PROTEIN", "quantity": {"grams": meal["protein"]}}],
            "totalCarbohydrate": {"grams": meal["carbohydrates"]},
            "totalFat": {"grams": meal["fat"]},
        }
    }

    nutrition = payload["nutritionLog"]
    if meal.get("protein") is None:
        nutrition.pop("nutrients")
    if meal.get("carbohydrates") is None:
        nutrition.pop("totalCarbohydrate")
    if meal.get("fat") is None:
        nutrition.pop("totalFat")
    if meal.get("meal_type"):
        nutrition["mealType"] = meal["meal_type"].upper()
    return payload


def backfill(client, owner):
    """Queue saved meals once through durable backfill markers."""
    count = 0
    with client.db.transaction():
        for meal in client.db.records(owner, "meal"):
            # A durable marker prevents repeated backfills from making duplicate jobs.
            if client.db.one(
                "SELECT 1 FROM records WHERE owner=? AND kind='backfill' AND id=?",
                (owner, meal["id"]),
            ):
                continue
            queue_nutrition(client.db, owner, meal["id"], meal)
            client.db.put_record(owner, "backfill", meal["id"], {"queued": True})
            count += 1
    return count


async def export(client, job):
    """Advance one export. A remote read resolves uncertain creates and deletes."""
    owner = job["owner"]
    value = json.loads(job["payload"])
    # 1. Read the connected account again. Reconnection can select a different Google account.
    identity = await client.request(owner, "GET", "users/me/identity")
    account = identity["healthUserId"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", account):
        raise ServiceError("Google returned an invalid Health account ID.")
    # 2. Save a stable remote name before writing so recovery can find an uncertain result.
    if "resource" not in value:
        record_id = "meal-" + hashlib.sha256((owner + job["id"]).encode()).hexdigest()[:40]
        value["resource"] = f"users/{account}/dataTypes/nutrition-log/dataPoints/{record_id}"
        try:
            value["previous"] = client.db.record(owner, "nutrition_export", value["meal_id"])[
                "resource"
            ]
        except LookupError:
            value["previous"] = None
        client.db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(value), job["id"]))
    resource = value["resource"]
    # A reconnect can select another Google account. Never modify its predecessor's records.
    prefix = f"users/{account}/dataTypes/nutrition-log/dataPoints/"
    if not resource.startswith(prefix) or (
        value.get("previous") and not value["previous"].startswith(prefix)
    ):
        raise ServiceError(
            "This export belongs to a different Health account. Reconnect that account."
        )
    # 3. Inspect any saved operation before another create or delete request.
    operation = value.get("pending_operation")
    if operation:
        pending = await client.request(owner, "GET", quote(operation, safe="/"))
        if not pending.get("done"):
            return False
        if pending.get("error"):
            raise ServiceError("Google rejected the nutrition operation.")
        value.pop("pending_operation")
        client.db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(value), job["id"]))
    # 4. Read before creating. The previous request may have succeeded before the connection ended.
    if value["operation"] != "delete":
        existing = await client.request(owner, "GET", resource, allow_missing=True)
        intended = nutrition_payload(value["meal"])
        if existing is None:
            parent = resource.rsplit("/dataPoints/", 1)[0]
            result = await client.request(
                owner, "POST", parent + "/dataPoints", json={"name": resource, **intended}
            )
            if result.get("error"):
                raise ServiceError("Google rejected the nutrition export.")
            if result.get("name") and not result.get("done"):
                value["pending_operation"] = result["name"]
                client.db.execute(
                    "UPDATE jobs SET payload=? WHERE id=?", (json.dumps(value), job["id"])
                )
            return False
        if existing.get("nutritionLog") != intended["nutritionLog"]:
            raise ServiceError(
                "The named nutrition record has different contents. Review it before retrying."
            )
    # 5. Remove the old revision only after the replacement exists with the expected contents.
    previous = value.get("previous")
    if previous:
        existing = await client.request(owner, "GET", previous, allow_missing=True)
        if existing is not None:
            parent = previous.rsplit("/dataPoints/", 1)[0]
            result = await client.request(
                owner, "POST", parent + "/dataPoints:batchDelete", json={"names": [previous]}
            )
            if result.get("error"):
                raise ServiceError("Google rejected the nutrition deletion.")
            if result.get("name") and not result.get("done"):
                value["pending_operation"] = result["name"]
                client.db.execute(
                    "UPDATE jobs SET payload=? WHERE id=?", (json.dumps(value), job["id"])
                )
            return False
    # 6. Save the local reference only after remote reconciliation completes.
    if value["operation"] == "delete":
        client.db.execute(
            "DELETE FROM records WHERE owner=? AND kind='nutrition_export' AND id=?",
            (owner, value["meal_id"]),
        )
    else:
        client.db.put_record(owner, "nutrition_export", value["meal_id"], {"resource": resource})
    return True
