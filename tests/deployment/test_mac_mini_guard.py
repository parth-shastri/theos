"""Exercise host recovery without changing the local Docker engine."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def guard(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "mac_mini_guard", Path(__file__).parents[2] / "scripts/mac_mini_guard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DISK", type("Disk", (), {"is_mount": lambda self: True})())
    return module


def test_missing_ssd_never_starts_docker(guard, monkeypatch):
    monkeypatch.setattr(guard.DISK.__class__, "is_mount", lambda self: False)
    monkeypatch.setattr(guard, "command", lambda *args, **kwargs: pytest.fail(str(args)))
    guard.reconcile({}, 10000)


@pytest.mark.parametrize(
    "content", ["{partial", "[]", '{"failures":"invalid"}', '{"restarts":[null]}']
)
def test_damaged_state_after_power_loss_does_not_disable_recovery(guard, tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    assert guard.load_state(path) == {}


def test_engine_start_waits_before_retry_then_restarts(guard, monkeypatch):
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[0] == "info":
            raise RuntimeError("engine unavailable")
        return ""

    monkeypatch.setattr(guard, "command", command)
    state = {}
    guard.reconcile(state, 10000)
    guard.reconcile(state, 10060)
    assert calls == [("info", "--format", "{{.ServerVersion}}"), ("desktop", "start", "--detach")]
    guard.reconcile(state, 10121)
    assert calls[-1] == ("desktop", "restart", "--detach")
    assert state["restarts"] == [10121]


def test_read_only_storage_requires_two_failures_and_respects_cooldown(guard, monkeypatch):
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[0] == "create":
            raise RuntimeError("read-only file system")
        return ""

    monkeypatch.setattr(guard, "command", command)
    state = {}
    guard.reconcile(state, 10000)
    assert not state.get("restarts")
    guard.reconcile(state, 10061)
    assert state["restarts"] == [10061]
    guard.reconcile(state, 10200)
    guard.reconcile(state, 10261)
    assert sum(args[0:2] == ("desktop", "restart") for args in calls) == 1


def test_healthy_engine_starts_only_stopped_known_containers(guard, monkeypatch):
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[0:2] == ("ps", "-a"):
            return "mem0-dev-mem0-1 exited\ntheos-voice-kokoro-1 running\nother-project exited"
        if args[0] == "create":
            return "probe-id"
        return ""

    monkeypatch.setattr(guard, "command", command)
    state = {"failures": 1}
    guard.reconcile(state, 10000)
    assert ("start", "mem0-dev-mem0-1") in calls
    assert not any(args[0] == "start" and args[1] != "mem0-dev-mem0-1" for args in calls)
    assert state["last_healthy"] == 10000
    assert state["failures"] == 0


def test_three_restarts_per_hour_limit_survives_saved_state(guard, monkeypatch):
    monkeypatch.setattr(guard, "command", lambda *args, **kwargs: pytest.fail(str(args)))
    state = {"restarts": [7000, 8000, 9000]}
    guard.restart(state, 10000)
    assert state["restarts"] == [7000, 8000, 9000]
