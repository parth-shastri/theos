"""Private Google Health connection, summary, and export tools."""

import time

from harness import tool


def health_tools(client, owner):
    """Build private account, summary, and nutrition export tools."""

    @tool
    async def health_connect():
        """Create an authorization link for Google Health."""
        return {"url": client.oauth.start(owner, "health")}

    @tool
    async def health_disconnect():
        """Disconnect Google Health and stop pending imports and exports."""
        return await client.oauth.disconnect(owner, "health")

    @tool
    async def get_health_summary(refresh: bool = False):
        """Read your latest seven-day health import, or request a refresh."""
        if refresh:
            return await client.import_summary(owner)
        return client.db.record(owner, "health", "summary")

    @tool
    async def get_meal_sync_status():
        """List nutrition export states, including uncertain writes."""
        return client.db.rows(
            "SELECT id,status,attempts,result,updated FROM jobs WHERE owner=? AND kind='nutrition' ORDER BY rowid DESC LIMIT 100",
            (owner,),
        )

    @tool
    async def retry_meal_sync():
        """Queue failed exports for reconciliation before any retry."""
        count = client.db.execute(
            "UPDATE jobs SET status='reconcile',attempts=0,due=? WHERE owner=? AND kind='nutrition' AND status='failed'",
            (time.time(), owner),
        ).rowcount
        return {"queued": count}

    @tool
    async def backfill_nutrition():
        """Queue historical meals that have no backfill marker."""
        client.oauth.read(owner, "health")
        return {"queued": client.backfill(owner)}

    return [
        health_connect,
        health_disconnect,
        get_health_summary,
        get_meal_sync_status,
        retry_meal_sync,
        backfill_nutrition,
    ]
