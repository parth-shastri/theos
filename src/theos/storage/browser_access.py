"""Durable browser credentials and Telegram-confirmed sign-in requests."""

import hashlib
import hmac
import secrets
import time

from .telegram_access import account_access

SIGNIN_SECONDS = 600
SESSION_SECONDS = 7 * 86400
SESSION_IDLE_SECONDS = 12 * 3600


def fingerprint(secret):
    """Store digests of random credentials, never their original values."""
    return hashlib.sha256(secret.encode()).hexdigest()


def token_owner(settings, db, token):
    """Resolve configured or generated access tokens without accepting a user ID."""
    if not token:
        return None
    owner = None
    for user, secret in settings.users.items():
        if hmac.compare_digest(token.encode(), secret.get_secret_value().encode()):
            owner = user
    return owner or credential_owner(settings, db, token, "token")


def issue_session(settings, db, owner, token=None):
    """Create an opaque device session and bind configured accounts to token rotation."""
    secret = secrets.token_urlsafe(32)
    now = time.time()
    db.ensure_user(owner)
    db.execute("DELETE FROM browser_credentials WHERE expires<=?", (now,))
    db.execute(
        "INSERT INTO browser_credentials VALUES (?,?,?,?,?)",
        (fingerprint(secret), owner, "session", now, now + SESSION_SECONDS),
    )
    db.execute(
        "INSERT INTO browser_session_metadata VALUES (?,?,?)",
        (
            fingerprint(secret),
            now,
            fingerprint(token) if owner in settings.users and token else None,
        ),
    )
    return secret


def check_login_limit(db, source):
    """Bound failed authentication attempts with persistent, content-free records."""
    now = time.time()
    bucket = fingerprint(source)
    db.execute("DELETE FROM browser_login_attempts WHERE attempted<=?", (now - 900,))
    count = db.one("SELECT COUNT(*) AS n FROM browser_login_attempts WHERE bucket=?", (bucket,))
    return count["n"] < 20


def record_login_failure(db, source):
    db.execute(
        "INSERT INTO browser_login_attempts VALUES (?,?)", (fingerprint(source), time.time())
    )


def require_enrolled(settings, db, owner):
    """Require a ready Telegram profile and current deployment authorization."""
    row = db.one("SELECT state FROM telegram_enrollments WHERE owner=?", (owner,))
    if not row or row["state"] != "ready" or not account_access(settings, db, owner):
        raise PermissionError("Complete /start in Telegram before opening the web UI.")


def invite(settings, db, owner):
    """Replace unfinished sign-in requests without changing existing credentials."""
    require_enrolled(settings, db, owner)
    secret = secrets.token_urlsafe(32)
    now = time.time()
    with db.transaction():
        db.execute("DELETE FROM browser_signins WHERE expires<=? OR owner=?", (now, owner))
        db.execute(
            "INSERT INTO browser_signins(id,owner,invite_hash,state,created,expires) "
            "VALUES (?,?,?,'invited',?,?)",
            (secrets.token_hex(16), owner, fingerprint(secret), now, now + SIGNIN_SECONDS),
        )
    return secret


def begin(settings, db, secret):
    """Bind a single-use invitation to one browser before Telegram confirmation."""
    browser = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    with db.transaction():
        row = db.one("SELECT * FROM browser_signins WHERE invite_hash=?", (fingerprint(secret),))
        if not row or row["state"] != "invited" or row["expires"] <= time.time():
            raise ValueError("This link is expired or already opened. Send /web in Telegram.")
        require_enrolled(settings, db, row["owner"])
        db.execute(
            "UPDATE browser_signins SET browser_hash=?,code=?,state='pending' WHERE id=?",
            (fingerprint(browser), code, row["id"]),
        )
    return {**row, "code": code, "state": "pending"}, browser


def request_for_browser(settings, db, browser):
    """A browser cookie identifies a request. The display code grants no access."""
    row = db.one("SELECT * FROM browser_signins WHERE browser_hash=?", (fingerprint(browser),))
    if not row or row["expires"] <= time.time():
        raise ValueError("This sign-in expired. Send /web in Telegram for a new link.")
    require_enrolled(settings, db, row["owner"])
    return row


def confirm(settings, db, owner, request_id, approved):
    """Only the enrolled Telegram owner can confirm their pending browser."""
    require_enrolled(settings, db, owner)
    with db.transaction():
        row = db.one("SELECT * FROM browser_signins WHERE id=? AND owner=?", (request_id, owner))
        if not row or row["state"] != "pending" or row["expires"] <= time.time():
            raise ValueError("This sign-in is unavailable or belongs to another user.")
        db.execute(
            "UPDATE browser_signins SET state=? WHERE id=?",
            ("approved" if approved else "denied", request_id),
        )
    return row["code"]


def complete(settings, db, browser):
    """Consume approval and issue a session plus a replaceable personal token."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db.transaction():
        row = request_for_browser(settings, db, browser)
        if row["state"] != "approved":
            raise ValueError("Confirm this browser in Telegram before continuing.")
        db.execute("UPDATE browser_signins SET state='used' WHERE id=?", (row["id"],))
        # A new saved token replaces the old one. Existing device sessions remain valid.
        db.execute(
            "DELETE FROM browser_credentials WHERE owner=? AND kind='token'", (row["owner"],)
        )
        db.execute("DELETE FROM browser_credentials WHERE expires<=?", (now,))
        db.execute(
            "INSERT INTO browser_credentials VALUES (?,?,?,?,?)",
            (fingerprint(token), row["owner"], "token", now, None),
        )
        session = issue_session(settings, db, row["owner"])
    return row["owner"], token, session


def credential_owner(settings, db, secret, kind):
    """Resolve a credential without accepting an owner or role from a client."""
    row = db.one(
        "SELECT * FROM browser_credentials WHERE token_hash=? AND kind=?",
        (fingerprint(secret), kind),
    )
    if not row or (row["expires"] is not None and row["expires"] <= time.time()):
        return None
    if kind == "session":
        metadata = db.one(
            "SELECT * FROM browser_session_metadata WHERE token_hash=?", (row["token_hash"],)
        )
        if not metadata or time.time() - metadata["last_used"] > SESSION_IDLE_SECONDS:
            return None
        if row["owner"] in settings.users:
            current = fingerprint(settings.users[row["owner"]].get_secret_value())
            if not metadata["credential_hash"] or not hmac.compare_digest(
                current, metadata["credential_hash"]
            ):
                return None
            db.execute(
                "UPDATE browser_session_metadata SET last_used=? WHERE token_hash=?",
                (time.time(), row["token_hash"]),
            )
            return row["owner"]
        # A removed configured account cannot become a Telegram identity.
        if metadata["credential_hash"]:
            return None
    try:
        require_enrolled(settings, db, row["owner"])
    except PermissionError:
        return None
    if kind == "session":
        db.execute(
            "UPDATE browser_session_metadata SET last_used=? WHERE token_hash=?",
            (time.time(), row["token_hash"]),
        )
    return row["owner"]


def revoke(db, owner):
    """End all generated browser access without deleting personal records."""
    with db.transaction():
        db.execute("DELETE FROM browser_credentials WHERE owner=?", (owner,))
        db.execute("DELETE FROM browser_signins WHERE owner=?", (owner,))
