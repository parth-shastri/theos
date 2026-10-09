"""SQL authorization for Telegram enrollment and private account connections."""

import hashlib
import hmac
from copy import deepcopy


def code_fingerprint(settings):
    """Keep the configured access code out of database records."""
    code = settings.telegram_access_code.get_secret_value()
    return hashlib.sha256(code.encode()).hexdigest() if code else ""


def has_access(settings, db, owner):
    """Check the optional sender restriction and the current SQL authorization."""
    if not owner.startswith("telegram:") or not owner[9:].isdigit():
        return False
    user_id = int(owner[9:])
    if user_id <= 0 or (settings.telegram_users and user_id not in settings.telegram_users):
        return False
    fingerprint = code_fingerprint(settings)
    if not fingerprint:
        return True
    row = db.one("SELECT code_fingerprint FROM telegram_access WHERE owner=?", (owner,))
    return bool(row and hmac.compare_digest(row["code_fingerprint"], fingerprint))


def account_access(settings, db, owner):
    """Require completed enrollment before exposing private account tools."""
    if not has_access(settings, db, owner):
        return False
    row = db.one("SELECT state FROM telegram_enrollments WHERE owner=?", (owner,))
    if row:
        return row["state"] == "ready"
    # Preserve explicitly configured legacy accounts when code access is disabled.
    return not code_fingerprint(settings) and int(owner[9:]) in settings.telegram_users


def prepare_update(settings, update):
    """Replace /start credentials with a verified fingerprint before inbox storage."""
    result = deepcopy(update)
    message = result.get("message", {})
    text = message.get("text", "").strip()
    command, _, argument = text.partition(" ")
    if command.split("@")[0] != "/start" or not argument:
        return result
    code = settings.telegram_access_code.get_secret_value()
    valid = bool(code) and hmac.compare_digest(argument.strip().encode(), code.encode())
    message["text"] = command
    message.pop("entities", None)
    message["_theos_access_attempt"] = True
    message["_theos_access_fingerprint"] = code_fingerprint(settings) if valid else ""
    return result
