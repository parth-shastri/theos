"""Configuration and transport boundaries for the operator's assistant name."""

from contextlib import asynccontextmanager
from html import escape
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from harness import AssistantMessage
from harness.testing import FakeModel
from theos.runtime.models import model_client
from theos.server import create_app
from theos.settings import Settings
from theos.transports.telegram.commands import command
from theos.transports.telegram.polling import Telegram

from .conftest import collect


def test_agent_environment_and_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        'AGENT_NAME="  Aster  "\nAGENT_MODEL=file-model\n'
        "AGENT_MEMORY__ENABLED=true\nAGENT_MEMORY__TIMEOUT=23\n"
    )
    monkeypatch.setenv("AGENT_MODEL", "environment-model")
    settings = Settings(_env_file=env)
    assert settings.name == "Aster"
    assert settings.model == "environment-model"
    assert settings.memory.enabled
    assert settings.memory.timeout == 23
    monkeypatch.setenv("AGENT_NAME", "Nova")
    assert Settings(_env_file=env).name == "Nova"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_invalid_agent_name(name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, name=name)


async def test_browser_name_is_escaped(runtime):
    runtime.settings.name = '<Nova & "friends">'
    app = create_app(runtime.settings, runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        page = await browser.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert f"<title>{escape(runtime.settings.name)} / Personal assistant</title>" in page.text
        assert f'<h1 id="agent-name">{escape(runtime.settings.name)}</h1>' in page.text
        assert runtime.settings.name not in page.text
        assert "{{AGENT_NAME}}" not in page.text


@pytest.mark.parametrize("action", ["/start", "/help"])
async def test_telegram_uses_agent_name(runtime, action):
    runtime.settings.name = "Nova"
    bot = Telegram(runtime)
    bot.send = AsyncMock()
    await command(bot, {"owner": "alice"}, action, "", 123, None)
    assert bot.send.call_args.args[1].startswith("I am Nova, your personal assistant.")


async def test_runtime_uses_agent_name(runtime):
    runtime.settings.name = "Nova"
    model = FakeModel([AssistantMessage("Hello")])

    @asynccontextmanager
    async def models(*args):
        yield model

    runtime.models = models
    session = runtime.db.create_session("alice", runtime.settings.model, "default")
    events = await collect(runtime.start("alice", session["id"], "Who are you?"))
    assert events[-1]["status"] == "completed"
    assert (
        model.requests[0]
        .messages[0]
        .content.startswith("You are Nova, a private personal assistant.")
    )


async def test_fake_provider_uses_agent_name(settings):
    settings.name = "Nova"
    async with model_client(settings, settings.model, settings.reasoning) as model:
        assert model.script[0].text.startswith("Nova is ready.")
