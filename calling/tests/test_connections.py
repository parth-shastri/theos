"""Accept only fresh private proofs and retain verified recipients across restarts."""

import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

from theos_calling.connections import Connections


@pytest.fixture
def connections(tmp_path):
    db = sqlite3.connect(tmp_path / "connections.sqlite3", isolation_level=None)
    db.row_factory = sqlite3.Row
    yield Connections(db, "k" * 32, SimpleNamespace(profile_url="https://t.me/theos_test"))
    db.close()


def message(result):
    return parse_qs(urlsplit(result["url"]).query)["text"][0]


async def test_proof_binds_expected_sender_and_is_single_use(connections):
    id = "a" * 32
    text = message(connections.start(id, 123))
    await connections.receive(456, text)
    assert not connections.permitted(456) and not connections.permitted(123)
    await connections.receive(123, text[:-1] + "z")
    assert connections.status(id)["status"] == "waiting"
    await connections.receive(123, text)
    assert connections.status(id) == {"status": "verified", "recipient": 123}
    await connections.receive(456, text)
    assert not connections.permitted(456)
    # A fresh wrapper uses the persisted binding without a contact lookup.
    restarted = Connections(connections.db, "k" * 32, connections.caller)
    assert restarted.permitted(123)
    restarted.disable(id)
    assert not restarted.permitted(123)
    await restarted.receive(123, text)
    assert not restarted.permitted(123)


async def test_expired_cancelled_and_unknown_proofs_cannot_bind(connections):
    id = "b" * 32
    text = message(connections.start(id, None))
    connections.db.execute("UPDATE connections SET expires=?", (time.time() - 1,))
    await connections.receive(123, text)
    assert connections.status(id)["status"] == "expired"
    assert not connections.permitted(123)
    await connections.receive(123, "connect " + "c" * 32 + " " + "d" * 64)
    with pytest.raises(HTTPException):
        connections.status("c" * 32)


async def test_browser_pairing_uses_the_sender_of_the_valid_challenge(connections):
    id = "e" * 32
    first = connections.start(id, None)
    assert first == connections.start(id, None)
    with pytest.raises(HTTPException):
        connections.start(id, 123)
    await connections.receive(456, message(first))
    assert connections.permitted(456)
