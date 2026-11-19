"""Authorize locally, resolve the explicit recipient, and reject the wrong account."""

import json

import pytest
from pydantic import ValidationError
from telethon.tl.types import Chat, User

from theos_calling.login import authorize
from theos_calling.settings import LoginSettings, Settings


@pytest.fixture
def settings(tmp_path):
    return LoginSettings(
        _env_file=None,
        api_id=12345,
        api_hash="a" * 32,
        data_dir=tmp_path / "calling",
        phone="+12025550100",
        recipient_username="@receiver",
    )


class Client:
    def __init__(self, settings, *, me=None, recipient=None):
        self.settings = settings
        self.me = me or User(id=100, phone="12025550100", bot=False)
        self.recipient = recipient or User(id=200, username="receiver", bot=False)
        self.requested = []
        self.closed = False

    async def start(self, *, phone, code_callback, password):
        assert phone == "+12025550100"
        self.settings.session_path.touch(mode=0o600)

    async def get_me(self):
        return self.me

    async def get_dialogs(self):
        pass

    async def get_entity(self, target):
        self.requested.append(target)
        return self.recipient

    async def disconnect(self):
        self.closed = True


async def test_login_resolves_username_without_a_placeholder_id(settings):
    client = Client(settings)
    result = await authorize(settings, client_factory=lambda *args: client)
    assert client.requested == ["@receiver"]
    assert result["caller_id"] == 100 and result["recipient_ids"] == [200]
    receipt = settings.data_dir / "authorization.json"
    assert json.loads(receipt.read_text()) == result
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert settings.session_path.stat().st_mode & 0o777 == 0o600
    assert client.closed
    # The HTTP gateway still requires explicit numeric recipients and a shared key.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **settings.model_dump())


@pytest.mark.parametrize(
    "case", ["self", "wrong_phone", "bot", "recipient_bot", "deleted", "group"]
)
async def test_login_does_not_approve_the_wrong_account_or_recipient(settings, case):
    client = Client(settings)
    if case == "self":
        client.recipient = User(id=100)
    elif case == "wrong_phone":
        client.me.phone = "12025550101"
    elif case == "bot":
        client.me.bot = True
    elif case == "recipient_bot":
        client.recipient.bot = True
    elif case == "deleted":
        client.recipient.deleted = True
    elif case == "group":
        client.recipient = Chat(
            id=300, title="group", photo=None, participants_count=2, date=None, version=1
        )
    with pytest.raises(ValueError):
        await authorize(settings, client_factory=lambda *args: client)
    assert not (settings.data_dir / "authorization.json").exists()
    assert client.closed


@pytest.mark.parametrize("case", ["missing_recipient", "link", "phone"])
async def test_login_rejects_bad_setup_before_contacting_telegram(settings, case):
    if case == "missing_recipient":
        settings.recipient_username = ""
    elif case == "link":
        settings.recipient_username = "https://t.me/receiver"
    else:
        settings.phone = "invalid number"
    contacted = []

    def factory(*args):
        contacted.append(True)
        raise AssertionError("Telegram must not be contacted.")

    # SecretStr assignment normally comes from Pydantic's settings parser.
    if case == "phone":
        from pydantic import SecretStr

        settings.phone = SecretStr("invalid number")
    with pytest.raises(ValueError):
        await authorize(settings, client_factory=factory)
    assert not contacted
