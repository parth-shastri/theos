"""Isolated assistant fixtures. No provider keys or live services are used."""

from contextlib import asynccontextmanager

import httpx
import pytest

from harness import AssistantMessage
from harness.testing import FakeModel
from theos.runtime import Runtime
from theos.settings import Settings
from theos.storage.database import Database


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        provider="fake",
        auto_titles=False,
        max_model_calls=12,
        max_compaction_calls=2,
        max_recovery_calls=1,
        delegate_max_model_calls=4,
        users={"alice": "a" * 32, "bob": "b" * 32},
        admins={"alice"},
    )


@pytest.fixture
def db(settings):
    database = Database(settings.data_dir)
    yield database
    database.close()


@pytest.fixture
def scripted_models():
    responses = []

    @asynccontextmanager
    async def factory(settings, model, reasoning):
        yield FakeModel(
            responses.pop(0) if responses else [AssistantMessage("Hello from the test model.")]
        )

    factory.responses = responses
    return factory


@pytest.fixture
async def runtime(settings, db, scripted_models):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    active = Runtime(settings, db, http, scripted_models)
    yield active
    await active.close()


async def call_tool(tools, tool_name, **arguments):
    from harness import RunContext

    selected = next(t for t in tools if t.name == tool_name)
    return await selected.execute(
        selected.input_model.model_validate(arguments), RunContext(deps=None)
    )


async def collect(turn):
    return [event async for event in turn.events()]
