"""Account access for authenticated browser and private Telegram identities."""

from .telegram_access import account_access as telegram_account_access

RESERVED_PREFIXES = ("telegram:", "telegram-group:", "terminal:")


def browser_account_access(settings, owner):
    """Require a configured browser identity outside other transport namespaces."""
    return owner in settings.users and not owner.startswith(RESERVED_PREFIXES)


def account_access(settings, db, owner):
    """Keep browser credentials separate from Telegram and terminal credentials."""
    return browser_account_access(settings, owner) or telegram_account_access(settings, db, owner)
