"""Password strength, salted password hashes, and browser account binding."""

import hashlib
import hmac
import secrets
from unicodedata import normalize

from zxcvbn import zxcvbn

from . import browser_access

MIN_LENGTH = 15
MAX_LENGTH = 128
DUMMY_SALT = secrets.token_bytes(16)


def derive(password, salt):
    """Use the OWASP scrypt profile with 32 MiB of working memory."""
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 * 1024**2, dklen=32
    )


def canonical(password):
    return normalize("NFC", password)


def create(password, confirmation, user_inputs):
    password = canonical(password)
    if password != canonical(confirmation):
        raise ValueError("The passwords do not match.")
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise ValueError(f"Use {MIN_LENGTH} to {MAX_LENGTH} characters.")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in password):
        raise ValueError("Use printable characters and spaces in your password.")
    if zxcvbn(password, user_inputs=user_inputs, max_length=MAX_LENGTH)["score"] < 3:
        raise ValueError("Choose a harder-to-guess password. Try several unrelated words.")
    salt = secrets.token_bytes(16)
    return salt, derive(password, salt)


def verify(password, row):
    password = canonical(password)
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        return False
    digest = derive(password, row["salt"] if row else DUMMY_SALT)
    return hmac.compare_digest(digest, row["digest"] if row else bytes(32)) and row is not None


def for_owner(settings, db, owner):
    row = db.one("SELECT * FROM browser_passwords WHERE owner=?", (owner,))
    if row is None:
        return None
    configured = settings.users.get(owner)
    if configured is not None:
        current = browser_access.fingerprint(configured.get_secret_value())
        return row if row["configured_token_hash"] == current else None
    if row["configured_token_hash"] is not None:
        return None
    try:
        browser_access.require_enrolled(settings, db, owner)
    except PermissionError:
        return None
    return row


def save(settings, db, owner, salt, digest):
    token = settings.users.get(owner)
    token_hash = browser_access.fingerprint(token.get_secret_value()) if token is not None else None
    db.execute(
        "INSERT INTO browser_passwords VALUES (?,?,?,?) ON CONFLICT(owner) DO UPDATE SET "
        "salt=excluded.salt, digest=excluded.digest, "
        "configured_token_hash=excluded.configured_token_hash",
        (owner, salt, digest, token_hash),
    )


def revoke_other_sessions(db, owner, session):
    db.execute(
        "DELETE FROM browser_credentials WHERE owner=? AND token_hash<>? AND token_hash IN "
        "(SELECT token_hash FROM browser_session_metadata WHERE password_login=1)",
        (owner, browser_access.fingerprint(session)),
    )
