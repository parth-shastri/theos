"""Account access for authenticated browser and private Telegram identities."""

import time

from .telegram_access import account_access as telegram_account_access

RESERVED_PREFIXES = ("telegram:", "telegram-group:", "terminal:")


def browser_account_access(settings, owner, db=None):
    """Allow configured accounts or ready Telegram owners with browser credentials."""
    if owner in settings.users and not owner.startswith(RESERVED_PREFIXES):
        return True
    return bool(
        db is not None
        and telegram_account_access(settings, db, owner)
        and db.one(
            "SELECT 1 FROM browser_credentials WHERE owner=? "
            "AND (expires IS NULL OR expires>?) LIMIT 1",
            (owner, time.time()),
        )
    )


def account_access(settings, db, owner):
    """Keep browser credentials separate from Telegram and terminal credentials."""
    return browser_account_access(settings, owner) or telegram_account_access(settings, db, owner)
