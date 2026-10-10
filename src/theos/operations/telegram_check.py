"""Check Telegram authentication and polling configuration without reading updates."""

import argparse
import os
import re
from pathlib import Path

import httpx


class TelegramCheckError(RuntimeError):
    """A configured bot cannot use the Telegram polling transport."""


def check_telegram(token, client):
    """Use read-only methods. Never consume updates or send a test message."""
    if not token:
        return False
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise TelegramCheckError("AGENT_TELEGRAM_TOKEN has an invalid format.")
    for method in ("getMe", "getWebhookInfo"):
        try:
            response = client.get(f"https://api.telegram.org/bot{token}/{method}", timeout=10)
            response.raise_for_status()
            body = response.json()
            if body.get("ok") is not True or not isinstance(body.get("result"), dict):
                raise ValueError("Invalid Bot API response")
            result = body["result"]
            if method == "getMe":
                if result.get("is_bot") is not True or type(result.get("id")) is not int:
                    raise ValueError("Invalid bot identity")
            elif not isinstance(result.get("url"), str):
                raise ValueError("Invalid webhook response")
            elif result["url"]:
                raise TelegramCheckError(
                    "Telegram has an active webhook. Remove it before using polling."
                )
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403}:
                raise TelegramCheckError(
                    "Telegram rejected AGENT_TELEGRAM_TOKEN. Get the current token from BotFather."
                ) from None
            raise TelegramCheckError(
                f"Telegram connection check failed with HTTP {error.response.status_code}."
            ) from None
        except httpx.HTTPError:
            raise TelegramCheckError(
                "Cannot reach Telegram. Check outbound HTTPS access."
            ) from None
        except (ValueError, TypeError, AttributeError):
            raise TelegramCheckError(
                "Telegram returned an invalid connection-check response."
            ) from None
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, help="Read the token from a private environment file"
    )
    args = parser.parse_args()
    token = os.environ.get("AGENT_TELEGRAM_TOKEN", "")
    if args.env_file:
        from dotenv import dotenv_values

        if not args.env_file.is_file():
            parser.exit(1, "The private environment file does not exist.\n")
        token = dotenv_values(args.env_file).get("AGENT_TELEGRAM_TOKEN") or ""
    try:
        with httpx.Client() as client:
            enabled = check_telegram(token, client)
    except TelegramCheckError as error:
        parser.exit(1, f"{error}\n")
    print(
        "Telegram authentication and polling checks passed." if enabled else "Telegram is disabled."
    )


if __name__ == "__main__":
    main()
