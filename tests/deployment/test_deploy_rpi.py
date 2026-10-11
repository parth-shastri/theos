"""Exercise state restoration after pull, backup, startup, and readiness failures."""

import json
from types import SimpleNamespace

import pytest

from scripts.deploy_rpi import Deployer, DeploymentError, write_json

IMAGE = "ghcr.io/parth-shastri/theos@sha256:" + "a" * 64
REVISION = "b" * 40


@pytest.mark.parametrize("shared_skills", [False, True])
def test_compose_retains_optional_shared_skills_during_release_and_rollback(
    tmp_path, monkeypatch, shared_skills
):
    override = tmp_path / "compose.skills.yaml"
    if shared_skills:
        override.write_text("services: {}\n")
    deployer = Deployer(tmp_path, tmp_path / "candidate.yaml")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="ok\n")

    monkeypatch.setattr("scripts.deploy_rpi.subprocess.run", run)
    for name in ("candidate", "previous"):
        release = dict(image=IMAGE, volume=name, compose_file=str(tmp_path / f"{name}.yaml"))
        assert deployer.compose(release, "up", "-d", "theos") == "ok"
        command, options = calls[-1]
        expected = ["-f", release["compose_file"]]
        if shared_skills:
            expected.extend(["-f", str(override)])
        assert command[command.index("-f") :] == [*expected, "up", "-d", "theos"]
        assert options["env"]["AGENT_IMAGE"] == IMAGE
        assert options["env"]["AGENT_DATA_VOLUME"] == name


@pytest.fixture
def deployment(tmp_path):
    directory = tmp_path / "deployment"
    directory.mkdir()
    (directory / ".env").write_text("AGENT_PROVIDER=fake\n")
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    deployer = Deployer(directory, compose)
    calls = []
    deployer.docker = lambda *args: calls.append(("docker", *args)) or ""
    deployer.compose = lambda release, *args: calls.append((release["volume"], *args)) or ""
    deployer.healthy = lambda release: calls.append(("healthy", release["volume"]))
    return deployer, calls


def previous_release(deployer):
    previous = dict(
        image="sha256:" + "c" * 64,
        volume="previous-volume",
        tag="rpi-v0.0.9",
        revision="d" * 40,
        compose_file=str(deployer.compose_file),
    )
    write_json(deployer.current_path, previous)
    return previous


def test_success_commits_new_volume_and_retains_previous(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)
    result = deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert result["status"] == "deployed"
    current = json.loads(deployer.current_path.read_text())
    assert current["volume"] != previous["volume"]
    assert result["backup"].startswith("previous-volume:/data/backups/")
    assert ("previous-volume", "stop", "theos") in calls
    restore = next(c for c in calls if "/previous:ro" in " ".join(c))
    assert previous["image"] in restore
    assert not deployer.pending_path.exists()
    assert not any("rm" in c[:3] and "volume" in c[:3] for c in calls)


def test_failed_readiness_restores_previous_image_and_untouched_volume(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)

    def health(release):
        calls.append(("healthy", release["volume"]))
        if release["volume"] != previous["volume"]:
            raise DeploymentError("candidate unhealthy")

    deployer.healthy = health
    with pytest.raises(DeploymentError, match="status=rolled_back"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert json.loads(deployer.current_path.read_text()) == previous
    assert ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos") in calls
    assert json.loads(deployer.result_path.read_text())["status"] == "rolled_back"
    assert not deployer.pending_path.exists()


def test_failed_pull_never_stops_previous_service(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)
    docker = deployer.docker

    def fail_pull(*args):
        if args[0] == "pull":
            raise DeploymentError("pull failed")
        return docker(*args)

    deployer.docker = fail_pull
    with pytest.raises(DeploymentError, match="status=failed"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert json.loads(deployer.current_path.read_text()) == previous
    assert not any("stop" in call for call in calls)


def test_failed_snapshot_restarts_previous_service(deployment):
    deployer, calls = deployment
    previous_release(deployer)

    def fail_snapshot(previous, candidate):
        raise DeploymentError("backup failed")

    deployer.snapshot = fail_snapshot
    with pytest.raises(DeploymentError, match="status=rolled_back"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos") in calls


def test_failed_rollback_keeps_journal_for_recovery(deployment):
    deployer, _ = deployment
    previous_release(deployer)

    def fail_health(release):
        raise DeploymentError("unhealthy")

    deployer.healthy = fail_health
    with pytest.raises(DeploymentError, match="status=rollback_failed"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert deployer.pending_path.exists()
    assert json.loads(deployer.result_path.read_text())["status"] == "rollback_failed"


def test_interrupted_release_recovers_before_another_deploy(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)
    candidate = dict(previous, volume="interrupted-volume")
    write_json(deployer.pending_path, dict(candidate=candidate, previous=previous))
    deployer.recover_interrupted()
    assert calls[0] == ("interrupted-volume", "stop", "theos")
    assert ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos") in calls
    assert json.loads(deployer.current_path.read_text()) == previous


def test_refuses_unmanaged_service(deployment):
    deployer, _ = deployment
    deployer.docker = lambda *args: "existing-container"
    with pytest.raises(DeploymentError, match="unmanaged"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)


def test_failed_first_install_stops_candidate(deployment):
    deployer, calls = deployment

    def fail_health(release):
        raise DeploymentError("unhealthy")

    deployer.healthy = fail_health
    with pytest.raises(DeploymentError, match="status=failed"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert any("stop" in call for call in calls)
    assert not deployer.current_path.exists()


def test_rejects_mutable_image_reference(deployment):
    with pytest.raises(DeploymentError, match="immutable"):
        deployment[0].deploy("ghcr.io/parth-shastri/theos:latest", "rpi-v0.1.0", REVISION)


def test_failed_telegram_preflight_never_stops_previous_service(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)

    def rejected(release, *, preflight=False):
        assert preflight
        raise DeploymentError("Telegram rejected the token")

    deployer.telegram_ready = rejected
    with pytest.raises(DeploymentError, match="status=failed"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert json.loads(deployer.current_path.read_text()) == previous
    assert not any("stop" in call for call in calls)
    assert not deployer.pending_path.exists()


def test_failed_active_telegram_check_rolls_back(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)

    def rejected(release, *, preflight=False):
        if not preflight:
            raise DeploymentError("Telegram connection failed after activation")

    deployer.telegram_ready = rejected
    with pytest.raises(DeploymentError, match="status=rolled_back"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert json.loads(deployer.current_path.read_text()) == previous
    assert ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos") in calls
    assert not deployer.pending_path.exists()


def test_telegram_checks_use_candidate_environment_and_active_container(deployment):
    deployer, calls = deployment
    previous_release(deployer)
    result = deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    volume = result["current"]["volume"]
    checker = ("theos", "python", "-m", "theos.operations.telegram_check")
    preflight = (volume, "run", "--rm", "--no-deps", "-T", *checker)
    active = (volume, "exec", "-T", *checker)
    assert calls.index(preflight) < calls.index(("previous-volume", "stop", "theos"))
    assert calls.index(("healthy", volume)) < calls.index(active)
