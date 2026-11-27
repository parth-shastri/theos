"""Owner-scoped optional account setup shared by the browser and Telegram."""

from typing import Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from harness import tool
from theos.storage.account_access import account_access

from . import journeys
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
    available = []
    for service, label in ACCOUNT_LABELS:
        enabled = (
            bool(settings.zepto_url) if service == "zepto" else getattr(settings, service).enabled
        )
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
    calling = settings.telegram_calls.configured and bool(settings.kokoro_url.strip())
    return {
        "needed": journeys.state(settings, db, owner)["needed"],
        "accounts": available,
        "display_name": profile.get("display_name", ""),
        "timezone": profile.get("timezone", settings.timezone),
        "calling": calling,
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
        progress = journeys.state(settings, db, owner)
        db.put_record(
            owner,
            "onboarding",
            "profile",
            {
                "step": "ready",
                "revision": progress["revision"] + 1,
                "pending_task": progress.get("pending_task", ""),
            },
        )
    return {
        "display_name": current.get("display_name", ""),
        "timezone": current.get("timezone", settings.timezone),
    }


def connection_tools(settings, db, session):
    """Offer native setup for configured services before their accounts are connected."""
    owner = session["owner"]
    if session["channel"] not in {"browser", "telegram-private"}:
        return []
    available = [
        service
        for service, _ in ACCOUNT_LABELS
        if (bool(settings.zepto_url) if service == "zepto" else getattr(settings, service).enabled)
    ]
    if not available:
        return []

    @tool
    async def connect_account(service: Literal[tuple(available)]):
        """Offer optional account setup in this conversation. Explain why the user's task needs access, let them authorize, then continue only when they return. Never ask for passwords or authorization codes in ordinary chat."""
        if not account_access(settings, db, owner):
            raise PermissionError("Use an authorized private conversation to connect accounts.")
        # Recheck configuration even for a tool built before the deployment changed.
        enabled = (
            bool(settings.zepto_url) if service == "zepto" else getattr(settings, service).enabled
        )
        if not enabled:
            raise ValueError("This account is unavailable on this deployment.")
        if session["channel"] == "browser" and settings.web_url:
            return {
                "service": service,
                "url": settings.web_url
                + "/?"
                + urlencode({"conversation": session["id"], "connect": service}),
                "message": "Open the account controls in this conversation. Return after sign-in to continue your task.",
            }
        command = (
            "/" + service if session["channel"] == "telegram-private" else "Connect " + service
        )
        return {
            "service": service,
            "command": command,
            "message": "Use this command to open the account controls, then return to your task.",
        }

    return [connect_account]
