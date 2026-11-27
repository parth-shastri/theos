"""Owner-scoped chat setup and return destinations for account authorization."""

import hashlib
import re
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .preferences.tools import preferences


def record(db, owner, kind, key, default=None):
    try:
        return db.record(owner, kind, key)
    except LookupError:
        return dict(default or {})


def timezone_choices(value):
    """Resolve exact zones or cities; leave ambiguous cities for the user to choose."""
    value = re.sub(
        r"(?i)^(?:i(?:'m|’m| am| live) in|my (?:timezone|time zone|city) is|use)\s+",
        "",
        value.strip(),
    ).strip(" .")
    try:
        ZoneInfo(value)
        return [value]
    except (ZoneInfoNotFoundError, ValueError):
        pass
    aliases = {
        "delhi": "Asia/Kolkata",
        "new delhi": "Asia/Kolkata",
        "mumbai": "Asia/Kolkata",
        "bengaluru": "Asia/Kolkata",
        "bangalore": "Asia/Kolkata",
        "india": "Asia/Kolkata",
    }
    if value.casefold() in aliases:
        return [aliases[value.casefold()]]
    city = value.casefold().replace(" ", "_")
    return sorted(
        zone
        for zone in available_timezones()
        if zone.casefold() == city or zone.rsplit("/", 1)[-1].casefold() == city
    )


def validate_profile(name, value):
    value = " ".join(value.split())
    if name == "display_name":
        if not 1 <= len(value) <= 200:
            raise ValueError("Choose a name from 1 to 200 characters.")
    elif name == "timezone":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(
                "Choose a timezone or send a city, such as London or Mumbai."
            ) from error
    else:
        raise ValueError("Choose a name or timezone to change.")
    return value


def state(settings, db, owner):
    """Honor completed legacy profiles without tying readiness to optional accounts."""
    saved = record(db, owner, "onboarding", "profile")
    profile = preferences(db, owner, settings.timezone)
    if not saved:
        enrollment = db.one("SELECT state FROM telegram_enrollments WHERE owner=?", (owner,))
        legacy = record(db, owner, "onboarding", "connections")
        complete = bool((enrollment and enrollment["state"] == "ready") or legacy.get("completed"))
        step = (
            enrollment["state"]
            if enrollment and not complete
            else ("name" if not profile.get("display_name") else "timezone")
        )
        saved = {"step": "ready" if complete else step, "revision": 0, "pending_task": ""}
    return {
        **saved,
        "display_name": profile.get("display_name", ""),
        "timezone": profile.get("timezone", settings.timezone),
        "needed": saved["step"] != "ready",
    }


def update(settings, db, owner, action, value="", revision=None):
    """Apply one validated chat step. Free text is confirmed before becoming a profile."""
    current = state(settings, db, owner)
    if revision is not None and current["revision"] != revision:
        raise ValueError("This setup step changed. Use the latest question.")
    profile = preferences(db, owner, settings.timezone)
    step = current["step"]
    current.pop("notice", None)
    if action == "restart":
        current.update(step="name", candidate="")
    elif action == "consume" and step == "ready":
        current["pending_task"] = ""
    elif action in {"skip", "finish"}:
        current["step"] = (
            "timezone" if step in {"name", "confirm_name"} and action == "skip" else "ready"
        )
        current.pop("candidate", None)
    elif action == "keep":
        if step in {"name", "confirm_name"}:
            current["step"] = "timezone"
        else:
            current["step"] = "ready"
    elif action == "confirm":
        if not current.get("candidate"):
            raise ValueError("Answer the current question first.")
        key = "display_name" if step == "confirm_name" else "timezone"
        profile[key] = validate_profile(key, current.pop("candidate"))
        current["step"] = "timezone" if key == "display_name" else "ready"
    elif action == "change":
        current["step"] = "name" if step == "confirm_name" else "timezone"
        current.pop("candidate", None)
    elif action == "reply":
        text = value.strip()
        if not text or len(text) > 8000:
            raise ValueError("Send a short reply, or choose Skip for now.")
        if text.casefold() in {"yes", "yes please", "correct", "confirm"} and current.get(
            "candidate"
        ):
            return update(settings, db, owner, "confirm", revision=revision)
        if text.casefold() in {"no", "change", "not that"} and current.get("candidate"):
            return update(settings, db, owner, "change", revision=revision)
        if text.casefold() in {"skip", "skip for now", "later"}:
            return update(settings, db, owner, "skip", revision=revision)
        if text.casefold() in {"cancel", "done", "start chatting"}:
            return update(settings, db, owner, "finish", revision=revision)
        if text.casefold() in {"help", "/help"}:
            current["notice"] = (
                "You can answer, correct a detail, or skip setup and start chatting."
            )
        elif (
            re.match(
                r"(?i)^(help|can you|could you|please|remind|plan|find|search|what|how|why|connect|show|book|schedule|send|buy|order|write|draft|create|check|summarize|analyse|analyze|i want|i need|i'd like|let's)\b",
                text,
            )
            or "?" in text
        ):
            pending = "\n\n".join(filter(None, (current.get("pending_task"), text)))
            if len(pending) > 32000:
                raise ValueError(
                    "Your earlier requests are saved. Choose Start chatting to continue them before adding another."
                )
            current["pending_task"] = pending
            current["notice"] = (
                "I saved your request. Finish this step or choose Start chatting to continue it."
            )
        elif step in {"name", "confirm_name"}:
            name = re.sub(r"(?i)^(call me|my name is|i am|i'm)\s+", "", text)
            current.update(candidate=validate_profile("display_name", name), step="confirm_name")
        elif step in {"timezone", "confirm_timezone"}:
            choices = timezone_choices(text)
            if not choices:
                raise ValueError(
                    "I could not find that timezone. Send a city such as London or Mumbai, or a zone such as Asia/Kolkata."
                )
            if len(choices) > 1:
                current.update(choices=choices[:12], notice="Choose the timezone for your city.")
            else:
                current.update(candidate=choices[0], step="confirm_timezone", choices=[])
        else:
            raise ValueError("Your profile is ready. Use Settings to change it.")
    else:
        raise ValueError("This setup action is unavailable. Use the latest question.")
    current["revision"] += 1
    # Profile, enrollment, and progress commit together so either channel sees one step.
    with db.transaction():
        db.put_record(owner, "preferences", "settings", profile)
        if current["step"] == "ready":
            db.execute("UPDATE telegram_enrollments SET state='ready' WHERE owner=?", (owner,))
        elif current["step"] in {"timezone", "confirm_timezone"}:
            db.execute("UPDATE telegram_enrollments SET state='timezone' WHERE owner=?", (owner,))
        db.put_record(
            owner,
            "onboarding",
            "profile",
            {
                key: val
                for key, val in current.items()
                if key not in {"id", "needed", "display_name", "timezone"}
            },
        )
    return state(settings, db, owner)


def remember_connection(db, owner, service, session_id, source="chat"):
    if source not in {"chat", "connections", "telegram"}:
        raise ValueError("Choose a valid connection destination.")
    if session_id:
        session = db.session(owner, session_id)
        if source != "telegram" and session["channel"] != "browser":
            raise ValueError("Choose a browser conversation to return to.")
    db.put_record(owner, "connection_return", service, {"session_id": session_id, "source": source})


def connection_return(db, owner, service):
    saved = record(db, owner, "connection_return", service)
    session = saved.get("session_id")
    if session:
        db.session(owner, session)
    if saved.get("source") == "chat":
        return "/?" + urlencode(
            {**({"conversation": session} if session else {}), "connected": service}
        )
    if saved.get("source") == "telegram":
        return "/?" + urlencode({"telegram_connected": service})
    return "/?connections=1"


def bind_connection(db, owner, service, url):
    """Bind the return destination to the exact consent state, never another attempt."""
    state = parse_qs(urlsplit(url).query).get("state", [""])[0]
    if state:
        saved = record(db, owner, "connection_return", service)
        digest = hashlib.sha256(state.encode()).hexdigest()
        db.put_record(
            owner,
            "authorization_return",
            digest,
            {
                "destination": connection_return(db, owner, service),
                "service": service,
                "source": saved.get("source", "connections"),
            },
        )


def authorization_return(db, owner, service, state):
    digest = hashlib.sha256(state.encode()).hexdigest()
    saved = record(db, owner, "authorization_return", digest)
    return saved if saved.get("service") == service else {"destination": "/?connections=1"}


def bind_tool_returns(tools, db, session):
    """Keep account links created by model tools in their originating conversation."""
    if session["channel"] not in {"browser", "telegram-private"}:
        return tools
    result = []
    for selected in tools:
        service = {
            "gmail_connect": "gmail",
            "calendar_connect": "calendar",
            "health_connect": "health",
        }.get(selected.name)
        if service is None:
            result.append(selected)
            continue

        async def execute(args, ctx, original=selected.execute, service=service):
            source = "chat" if session["channel"] == "browser" else "telegram"
            remember_connection(db, session["owner"], service, session["id"], source)
            value = await original(args, ctx)
            if isinstance(value, dict) and value.get("url"):
                bind_connection(db, session["owner"], service, value["url"])
            return value

        result.append(replace(selected, execute=execute))
    return result
