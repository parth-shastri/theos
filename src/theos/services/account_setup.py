"""Owner-scoped optional account setup shared by the browser and Telegram."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .preferences.tools import preferences

ACCOUNT_LABELS = (
    ("gmail", "Gmail"),
    ("calendar", "Google Calendar"),
    ("zepto", "Zepto"),
    ("health", "Google Health"),
    ("slack", "Slack"),
    ("github", "GitHub"),
)


def setup_status(settings, db, owner, zepto):
    """Offer configured, unconnected accounts without repeating completed setup."""
    try:
        complete = db.record(owner, "onboarding", "connections").get("completed", False)
    except LookupError:
        complete = False
    available = []
    configured = False
    for service, label in ACCOUNT_LABELS:
        enabled = (
            bool(settings.zepto_url) if service == "zepto" else getattr(settings, service).enabled
        )
        configured = configured or enabled
        connected = (
            zepto.connected(owner)
            if service == "zepto"
            else bool(
                db.one("SELECT 1 FROM credentials WHERE owner=? AND service=?", (owner, service))
            )
        )
        if enabled and not connected:
            available.append({"id": service, "name": label})
    profile = preferences(db, owner, settings.timezone)
    return {
        "needed": bool(
            (available or (configured and not profile.get("display_name"))) and not complete
        ),
        "accounts": available,
        "display_name": profile.get("display_name", ""),
        "timezone": profile.get("timezone", settings.timezone),
    }


def complete_setup(settings, db, owner, display_name=None, timezone=None):
    """Save optional profile edits and dismiss connector setup for this owner."""
    current = preferences(db, owner, settings.timezone)
    if display_name is not None:
        name = " ".join(display_name.split())
        if not 1 <= len(name) <= 200:
            raise ValueError("Send a name from 1 to 200 characters.")
        current["display_name"] = name
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Use a timezone such as Asia/Kolkata or UTC.") from error
        current["timezone"] = timezone
    with db.transaction():
        if display_name is not None or timezone is not None:
            db.put_record(owner, "preferences", "settings", current)
        db.put_record(owner, "onboarding", "connections", {"completed": True})
    return {
        "display_name": current.get("display_name", ""),
        "timezone": current.get("timezone", settings.timezone),
    }
