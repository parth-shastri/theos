"""Authorize the dedicated calling account interactively on the operator's host."""

import argparse
import asyncio
import getpass
import os

from telethon import TelegramClient

from .settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Private gateway environment file")
    args = parser.parse_args()
    os.umask(0o077)
    settings = Settings(_env_file=args.env_file)
    settings.prepare_directory()

    async def authorize():
        client = TelegramClient(
            str(settings.session_path), settings.api_id, settings.api_hash.get_secret_value()
        )
        try:
            await client.start(
                phone=lambda: getpass.getpass("Calling account phone number: "),
                code_callback=lambda: getpass.getpass("Telegram login code: "),
                password=lambda: getpass.getpass("Telegram two-step verification password: "),
            )
            me = await client.get_me()
            if me.bot or me.id in settings.recipients:
                raise ValueError("Use a separate regular Telegram account for calling.")
            await client.get_dialogs()
            for recipient in settings.recipients:
                await client.get_input_entity(recipient)
            print("Calling account authorized. No call was placed.")
        finally:
            await client.disconnect()
            if settings.session_path.exists():
                settings.session_path.chmod(0o600)

    asyncio.run(authorize())
