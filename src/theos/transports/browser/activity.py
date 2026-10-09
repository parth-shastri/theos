"""Complete dashboard chart aggregates within a bounded UTC date range."""

from datetime import UTC, datetime, timedelta


def activity_summary(db, days=30, *, now=None, owner=None):
    """Aggregate model usage and main-agent tool starts without table row limits."""
    if days not in (7, 30, 90):
        raise ValueError("Choose a 7, 30, or 90 day activity range.")
    now = now or datetime.now(UTC)
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    bounds = (start.timestamp(), now.timestamp())
    scope = " AND owner=?" if owner is not None else ""
    parameters = (*bounds, owner) if owner is not None else bounds
    recorded = {
        row["date"]: row
        for row in db.rows(
            "SELECT date(created,'unixepoch') AS date,COUNT(*) AS requests,"
            "COUNT(*)-COUNT(cost) AS unpriced_requests,SUM(cost) AS cost,"
            "SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens "
            "FROM usage WHERE created>=? AND created<=?"
            + scope
            + " GROUP BY date(created,'unixepoch')",
            parameters,
        )
    }
    daily = []
    for offset in range(days):
        date = (start + timedelta(days=offset)).date().isoformat()
        daily.append(
            recorded.get(
                date,
                {
                    "date": date,
                    "requests": 0,
                    "unpriced_requests": 0,
                    "cost": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
        )
    requests = sum(row["requests"] for row in daily)
    unpriced = sum(row["unpriced_requests"] for row in daily)
    return {
        "days": days,
        "timezone": "UTC",
        "daily": daily,
        "totals": {
            "requests": requests,
            "unpriced_requests": unpriced,
            "cost": None
            if requests and unpriced == requests
            else sum(row["cost"] or 0 for row in daily),
            "input_tokens": sum(row["input_tokens"] for row in daily),
            "output_tokens": sum(row["output_tokens"] for row in daily),
        },
        "models": db.rows(
            "SELECT model,COUNT(*) AS requests,SUM(input_tokens) AS input_tokens,"
            "SUM(output_tokens) AS output_tokens FROM usage WHERE created>=? AND created<=?"
            + scope
            + " GROUP BY model ORDER BY SUM(input_tokens)+SUM(output_tokens) DESC,model",
            parameters,
        ),
        "tools": db.rows(
            "SELECT tool,COUNT(*) AS calls FROM traces WHERE created>=? AND created<=?"
            + scope
            + " AND event='ToolStarted' AND tool IS NOT NULL GROUP BY tool ORDER BY COUNT(*) DESC,tool",
            parameters,
        ),
    }
