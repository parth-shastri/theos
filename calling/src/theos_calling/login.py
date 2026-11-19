"""Authorize the dedicated calling account interactively on the operator's host."""

import argparse
import asyncio
import getpass
import json
import os
import re
import time

from telethon import TelegramClient
from telethon.tl.types import User

from .settings import LoginSettings


async def authorize(settings, *, client_factory=None, prompt=None):
    """Resolve the receiving account after login without a placeholder recipient ID."""
    settings.prepare_directory()
    username = settings.recipient_username.strip().removeprefix("@")
    if username and not re.fullmatch(r"[A-Za-z0-9_]{1,64}", username):
        raise ValueError("Set a Telegram recipient username without a link.")
    if not username and not settings.recipients:
        raise ValueError("Set the receiving Telegram username or numeric user ID before login.")
    phone = settings.phone.get_secret_value()
    if phone and not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise ValueError("Set the calling account number with its country code.")
    receipt = settings.data_dir / "authorization.json"
    receipt.unlink(missing_ok=True)
    client = (client_factory or TelegramClient)(
        str(settings.session_path), settings.api_id, settings.api_hash.get_secret_value()
    )
    prompt = prompt or getpass.getpass
    try:
        await client.start(
            phone=phone or (lambda: prompt("Calling account phone number: ")),
            code_callback=lambda: prompt("Telegram login code: "),
            password=lambda: prompt("Telegram two-step verification password: "),
        )
        me = await client.get_me()
        if me is None or me.bot:
            raise ValueError("Use a regular Telegram account for calling.")
        if phone and str(me.phone).lstrip("+") != phone.lstrip("+"):
            raise ValueError("The saved Telegram session belongs to a different calling number.")
        await client.get_dialogs()
        targets = []
        for target in [*sorted(settings.recipients), *(["@" + username] if username else [])]:
            user = await client.get_entity(target)
            if not isinstance(user, User) or user.bot or user.deleted or user.id <= 0:
                raise ValueError("The call recipient must be a regular Telegram user.")
            if user.id == me.id:
                raise ValueError("Use a separate Telegram account to call your personal account.")
            targets.append(user.id)
        result = {
            "caller_id": me.id,
            "recipient_ids": sorted(set(targets)),
            "authorized_at": time.time(),
        }
        descriptor = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(result, output)
        print("Calling account authorized. Receiving account verified. No call was placed.")
        return result
    finally:
        await client.disconnect()
        if settings.session_path.exists():
            settings.session_path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Private gateway environment file")
    args = parser.parse_args()
    os.umask(0o077)
    settings = LoginSettings(_env_file=args.env_file)
    asyncio.run(authorize(settings))
