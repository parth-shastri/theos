"""Private Zepto OAuth storage and Telegram handoff acceptance checks."""

import asyncio
import json
import time

import pytest
from cryptography.fernet import Fernet
from mcp.shared.auth import OAuthToken
from pydantic import SecretStr, ValidationError

from theos.services.zepto.auth import PendingConnection, Zepto, ZeptoTokenStorage
from theos.settings import Settings
from theos.transports.telegram.polling import Telegram

from .test_interfaces import onboard, telegram_message


def configure_zepto(runtime):
    runtime.settings.telegram_users = {123, 456}
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())


def test_zepto_configuration_requires_encryption_key(tmp_path):
    with pytest.raises(ValidationError, match="valid Fernet token encryption key"):
        Settings(
            _env_file=None,
            data_dir=tmp_path,
            zepto_url="https://shopping.test/mcp",
        )


async def test_zepto_credentials_are_encrypted_owner_scoped_and_restart_safe(runtime):
    configure_zepto(runtime)
    owner = "telegram:123"
    token = OAuthToken(
        access_token="access-secret",
        refresh_token="refresh-secret",
        token_type="Bearer",
        expires_in=3600,
    )
    await ZeptoTokenStorage(runtime.settings, runtime.db, owner).set_tokens(token)

    row = runtime.db.one(
        "SELECT encrypted FROM credentials WHERE owner=? AND service='zepto'", (owner,)
    )
    assert "access-secret" not in row["encrypted"]
    assert "refresh-secret" not in row["encrypted"]

    restored = ZeptoTokenStorage(runtime.settings, runtime.db, owner)
    assert await restored.get_tokens() == token
    assert await restored.get_expiry() > time.time()
    assert (
        await ZeptoTokenStorage(runtime.settings, runtime.db, "telegram:456").get_tokens() is None
    )
    assert Zepto(runtime.settings, runtime.db, None).connected(owner)
    assert not Zepto(runtime.settings, runtime.db, None).connected("telegram:456")


async def test_zepto_telegram_handoff_encrypts_inbox_and_never_creates_chat_history(
    runtime, monkeypatch
):
    configure_zepto(runtime)
    telegram = Telegram(runtime)
    sent = []
    api_calls = []
    return_urls = []

    async def api(method, payload=None, files=None):
        api_calls.append((method, payload))
        return {"message_id": len(api_calls)}

    async def send(chat, text, topic=None, markup=None):
        sent.append(text)

    async def finish(owner, return_url):
        assert owner == "telegram:123"
        return_urls.append(return_url)

    telegram.api = api
    telegram.send = send
    monkeypatch.setattr(runtime.zepto, "finish_from_telegram", finish)
    await onboard(telegram)

    return_url = "http://localhost/callback?code=one-time-code&state=oauth-state"
    update = telegram_message("/zepto_finish " + return_url)
    update["update_id"] = 77
    telegram.save_updates([update])

    saved = json.loads(
        runtime.db.one("SELECT payload FROM telegram_updates WHERE id=77")["payload"]
    )
    saved_message = saved["message"]
    assert saved_message["text"] == "/zepto_finish"
    assert "one-time-code" not in json.dumps(saved)
    assert "oauth-state" not in json.dumps(saved)
    encrypted_return = saved_message["_theos_zepto_return"]
    cipher = Fernet(runtime.settings.token_encryption_key.get_secret_value().encode())
    assert cipher.decrypt(encrypted_return.encode()).decode() == return_url

    await telegram.process([saved])

    after = json.loads(
        runtime.db.one("SELECT payload FROM telegram_updates WHERE id=77")["payload"]
    )
    assert after["message"]["text"] == "/zepto_finish"
    assert "_theos_zepto_return" not in after["message"]
    assert return_urls == [return_url]
    assert any("return was accepted" in message for message in sent)
    assert any(method == "deleteMessage" for method, _ in api_calls)
    assert runtime.db.one("SELECT COUNT(*) AS total FROM sessions")["total"] == 0


async def test_zepto_handoff_requires_the_same_owner_and_state(runtime):
    configure_zepto(runtime)
    future = asyncio.get_running_loop().create_future()
    flow = PendingConnection(
        owner="telegram:123",
        redirect_uri="http://localhost/callback",
        callback=future,
        send_link=lambda _: None,
        send_status=lambda _: None,
        created=time.time(),
        state="expected-state",
    )
    runtime.zepto.pending[flow.owner] = flow

    with pytest.raises(ValueError, match="does not match"):
        await runtime.zepto.finish_from_telegram(
            "telegram:123", "http://localhost/callback?code=code&state=wrong-state"
        )
    with pytest.raises(ValueError, match="No Zepto setup"):
        await runtime.zepto.finish_from_telegram(
            "telegram:456", "http://localhost/callback?code=code&state=expected-state"
        )
    assert not future.done()

    await runtime.zepto.finish_from_telegram(
        "telegram:123", "http://localhost/callback?code=one-time-code&state=expected-state"
    )
    assert await future == ("one-time-code", "expected-state")
