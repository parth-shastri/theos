"""Exercise state restoration after pull, backup, startup, and readiness failures."""

import json
from pathlib import Path
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
    deployer.docker = lambda *args, **kwargs: calls.append(("docker", *args)) or ""

    def compose(release, *args):
        calls.append((release["volume"], *args))
        if args == ("config", "--format", "json"):
            return json.dumps({"services": {"theos": {"environment": {}}}})
        return ""

    deployer.compose = compose
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


def retained_release(number):
    revision = f"{number:040x}"
    return dict(
        tag=f"rpi-v1.0.{number}",
        revision=revision,
        volume=f"theos-rpi-{revision[:12]}-{number:08x}",
    )


def test_retention_keeps_active_and_two_previous_verified_releases(deployment):
    deployer, calls = deployment
    first, second, third, fourth = [retained_release(n) for n in range(1, 5)]
    deployer.docker = lambda *args: (
        "\n".join(item["volume"] for item in (first, second, third, fourth))
        if args == ("volume", "ls", "-q")
        else calls.append(("docker", *args)) or ""
    )
    deployer.retain_releases(
        third, second, {"status": "deployed", "current": second, "previous": first}
    )
    assert json.loads(deployer.history_path.read_text()) == [first, second, third]
    deployer.retain_releases(fourth, third, {})
    assert ("docker", "volume", "rm", first["volume"]) in calls
    assert not any(
        ("docker", "volume", "rm", item["volume"]) in calls for item in (second, third, fourth)
    )
    assert json.loads(deployer.history_path.read_text()) == [second, third, fourth]


def test_retention_keeps_in_use_and_untracked_volumes(deployment):
    deployer, calls = deployment
    first, second, third, fourth = [retained_release(n) for n in range(1, 5)]
    write_json(deployer.history_path, [first, second, third])

    def docker(*args):
        calls.append(args)
        if args == ("volume", "ls", "-q"):
            return first["volume"] + "\nuntracked-data"
        if args == ("ps", "-aq", "--filter", f"volume={first['volume']}"):
            return "existing-container"
        return ""

    deployer.docker = docker
    deployer.retain_releases(fourth, third, {})
    assert not any(args[:2] == ("volume", "rm") for args in calls)
    assert json.loads(deployer.history_path.read_text()) == [first, second, third, fourth]


def test_retention_fails_closed_for_inconsistent_history(deployment):
    deployer, calls = deployment
    first, second, third = [retained_release(n) for n in range(1, 4)]
    write_json(deployer.history_path, [first])
    with pytest.raises(DeploymentError, match="inconsistent release history"):
        deployer.retain_releases(third, second, {})
    assert json.loads(deployer.history_path.read_text()) == [first]
    assert calls == []


def test_retention_keeps_history_for_retry_after_removal_failure(deployment):
    deployer, _ = deployment
    first, second, third, fourth = [retained_release(n) for n in range(1, 5)]
    write_json(deployer.history_path, [first, second, third])

    def docker(*args):
        if args == ("volume", "ls", "-q"):
            return first["volume"]
        if args[:2] == ("volume", "rm"):
            raise DeploymentError("volume removal failed")
        return ""

    deployer.docker = docker
    with pytest.raises(DeploymentError, match="volume removal failed"):
        deployer.retain_releases(fourth, third, {})
    assert json.loads(deployer.history_path.read_text()) == [first, second, third, fourth]


def test_retention_failure_does_not_roll_back_successful_deployment(deployment):
    deployer, calls = deployment
    previous_release(deployer)

    def fail_retention(*args):
        raise DeploymentError("cleanup unavailable")

    deployer.retain_releases = fail_retention
    result = deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert result["status"] == "deployed"
    assert result["retention_warning"] == "cleanup unavailable"
    assert json.loads(deployer.current_path.read_text()) == result["current"]
    assert not any(call[:2] == ("previous-volume", "up") for call in calls)


def test_success_commits_new_volume_and_retains_previous(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)
    result = deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    assert result["status"] == "deployed"
    current = json.loads(deployer.current_path.read_text())
    assert current["volume"] != previous["volume"]
    assert result["backup"].startswith("previous-volume:/data/backups/")
    assert ("previous-volume", "stop", "theos") in calls
    backup = next(c for c in calls if "theos-backup-" in " ".join(c))
    assert IMAGE in backup and previous["image"] not in backup
    restore = next(c for c in calls if "/previous:ro" in " ".join(c))
    assert previous["image"] in restore
    assert not deployer.pending_path.exists()
    assert ("docker", "volume", "rm", current["volume"] + "-preflight") in calls
    assert ("docker", "volume", "rm", current["volume"]) not in calls
    assert ("docker", "volume", "rm", previous["volume"]) not in calls


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
    assert not deployer.history_path.exists()
    assert ("docker", "volume", "rm", "previous-volume") not in calls


def test_timed_out_helper_is_removed_before_rollback_opens_previous_volume(deployment):
    deployer, calls = deployment
    previous_release(deployer)
    original = deployer.docker
    running = False

    def docker(*args, **kwargs):
        nonlocal running
        if args[0] == "run" and "--name" in args:
            assert kwargs["timeout"] == 3600
            running = True
            raise DeploymentError("backup helper timed out")
        if args[:2] == ("ps", "-aq") and "name=^/theos-backup-" in args[-1]:
            return "helper-id" if running else ""
        if args == ("rm", "-f", "helper-id"):
            running = False
        return original(*args, **kwargs)

    deployer.docker = docker
    with pytest.raises(DeploymentError, match="status=rolled_back"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION)
    removed = calls.index(("docker", "rm", "-f", "helper-id"))
    reopened = calls.index(
        ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos")
    )
    assert removed < reopened
    assert not running
    assert not deployer.pending_path.exists()


def test_interrupted_helper_is_removed_before_the_interrupt_propagates(deployment):
    deployer, _ = deployment
    removed = []

    def docker(*args, **kwargs):
        if args[0] == "run":
            raise KeyboardInterrupt()
        if args[0] == "ps":
            return "interrupted-helper"
        removed.append(args)
        return ""

    deployer.docker = docker
    with pytest.raises(KeyboardInterrupt):
        deployer.run_helper("theos-backup-test", "image", timeout=1800)
    assert removed == [("rm", "-f", "interrupted-helper")]


def test_snapshot_has_separate_bounded_backup_and_restore_deadlines(deployment):
    deployer, _ = deployment
    previous = previous_release(deployer)
    calls = []

    def docker(*args, **kwargs):
        if args[0] == "run":
            calls.append((args, kwargs))
        return ""

    deployer.docker = docker
    deployer.compose = lambda *_: json.dumps({"services": {"theos": {"environment": {}}}})
    deployer.snapshot(
        previous, dict(revision=REVISION, tag="rpi-v0.1.0", volume="candidate", image=IMAGE)
    )
    assert [kwargs["timeout"] for _, kwargs in calls] == [3600, 900, 3600]
    assert all("--no-healthcheck" in args and "--name" in args for args, _ in calls)
    assert "--env-file" in calls[0][0]
    assert "--network" not in calls[0][0]
    assert "--network" in calls[1][0] and "none" in calls[1][0]
    assert "--env-file" in calls[2][0] and IMAGE in calls[2][0]


@pytest.mark.parametrize("fail", [False, True])
def test_backup_helpers_use_private_resolved_storage_and_always_remove_it(deployment, fail):
    deployer, _ = deployment
    previous = previous_release(deployer)
    storage = {
        "AGENT_STORAGE__ENDPOINT": "https://r2.example.invalid",
        "AGENT_STORAGE__BUCKET": "private-test",
        "AGENT_STORAGE__ACCESS_KEY": "test-access",
        "AGENT_STORAGE__SECRET_KEY": "test-secret",
        "AGENT_STORAGE__CHECKPOINT_KEEP": "3",
    }
    environment = {
        **storage,
        "AGENT_TRACING__HEADERS": '{"secret":"unrelated"}',
        "AGENT_API_KEY": "unrelated",
        "AGENT_STORAGE__GC_GRACE_SECONDS": "60",
    }
    deployer.compose = lambda *_: json.dumps({"services": {"theos": {"environment": environment}}})
    paths = []

    def helper(name, *args, **kwargs):
        if "--env-file" in args:
            path = Path(args[args.index("--env-file") + 1])
            paths.append(path)
            assert path.stat().st_mode & 0o777 == 0o600
            assert dict(line.split("=", 1) for line in path.read_text().splitlines()) == storage
            if fail:
                raise DeploymentError("synthetic helper failure")
        return "r2:theos/backups/synthetic.tar.gz"

    deployer.run_helper = helper
    candidate = dict(revision=REVISION, tag="rpi-v0.1.0", volume="candidate", image=IMAGE)
    if fail:
        with pytest.raises(DeploymentError, match="synthetic helper failure"):
            deployer.snapshot(previous, candidate)
    else:
        assert deployer.snapshot(previous, candidate) == "r2:theos/backups/synthetic.tar.gz"
    assert paths and all(not path.exists() for path in paths)


def test_backup_helpers_reject_multiline_storage_without_retaining_private_file(deployment):
    deployer, _ = deployment
    environment = {"AGENT_STORAGE__SECRET_KEY": "first\nsecond"}
    deployer.compose = lambda *_: json.dumps({"services": {"theos": {"environment": environment}}})
    with pytest.raises(DeploymentError, match="single-line"):
        deployer.snapshot(previous_release(deployer), {})
    assert not list(deployer.directory.glob(".backup-storage-*"))


def test_helper_completion_during_cleanup_does_not_prevent_rollback(deployment):
    deployer, _ = deployment

    def docker(*args, **kwargs):
        if args[0] == "run":
            raise DeploymentError("timed out")
        if args[0] == "ps":
            return "exiting-helper" if args[-1].startswith("name=") else ""
        raise DeploymentError("container already removed")

    deployer.docker = docker
    with pytest.raises(DeploymentError, match="timed out"):
        deployer.run_helper("theos-backup-test", "image", timeout=1800)


def test_restart_recovers_orphan_helper_before_reopening_previous_database(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)
    candidate = dict(previous, volume="interrupted-volume", revision=REVISION)
    write_json(deployer.pending_path, dict(candidate=candidate, previous=previous))
    original = deployer.docker
    running = True

    def docker(*args, **kwargs):
        nonlocal running
        if args[0] == "ps" and "name=^/theos-backup-" in args[-1]:
            return "orphan-helper" if running else ""
        if args == ("rm", "-f", "orphan-helper"):
            running = False
        return original(*args, **kwargs)

    deployer.docker = docker
    deployer.recover_interrupted()
    removed = calls.index(("docker", "rm", "-f", "orphan-helper"))
    reopened = calls.index(
        ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos")
    )
    assert removed < reopened
    assert not running
    assert not deployer.pending_path.exists()


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


def test_failed_preflight_removes_only_its_disposable_volume(deployment):
    deployer, calls = deployment
    release = {"volume": "candidate-volume"}

    def fail_check(release, *args):
        calls.append((release["volume"], *args))
        raise DeploymentError("check failed")

    deployer.compose = fail_check
    with pytest.raises(DeploymentError, match="Telegram connection check failed"):
        deployer.telegram_ready(release, preflight=True)
    assert ("docker", "volume", "create", "candidate-volume-preflight") in calls
    assert ("docker", "volume", "rm", "candidate-volume-preflight") in calls
    assert ("docker", "volume", "rm", "candidate-volume") not in calls


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
    preflight_volume = volume + "-preflight"
    preflight = (preflight_volume, "run", "--rm", "--no-deps", "-T", *checker)
    active = (volume, "exec", "-T", *checker)
    assert calls.index(("docker", "volume", "create", preflight_volume)) < calls.index(preflight)
    assert calls.index(preflight) < calls.index(("docker", "volume", "rm", preflight_volume))
    assert calls.index(preflight) < calls.index(("previous-volume", "stop", "theos"))
    assert calls.index(("healthy", volume)) < calls.index(active)


def test_frontend_release_pins_and_starts_both_services(deployment):
    deployer, calls = deployment
    web_image = "ghcr.io/parth-shastri/theos-web@sha256:" + "e" * 64
    result = deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION, web_image)
    current = result["current"]
    assert current["web_image"] == web_image
    assert ("docker", "pull", web_image) in calls
    assert (current["volume"], "up", "--no-build", "--pull", "never", "-d", "theos", "web") in calls


def test_failed_frontend_restores_both_previous_services(deployment):
    deployer, calls = deployment
    previous = previous_release(deployer)
    previous["web_image"] = "ghcr.io/parth-shastri/theos-web@sha256:" + "f" * 64
    write_json(deployer.current_path, previous)

    def health(release):
        if release["volume"] != previous["volume"]:
            raise DeploymentError("frontend unhealthy")

    deployer.healthy = health
    with pytest.raises(DeploymentError, match="rolled_back"):
        deployer.deploy(
            IMAGE, "rpi-v0.1.0", REVISION, "ghcr.io/parth-shastri/theos-web@sha256:" + "e" * 64
        )
    result = json.loads(deployer.result_path.read_text())
    assert result["current"] == previous
    assert ("previous-volume", "up", "--no-build", "--pull", "never", "-d", "theos", "web") in calls
    assert any(call[1:] == ("stop", "theos", "web") for call in calls)


def test_mutable_frontend_image_is_rejected_before_deployment(deployment):
    deployer, calls = deployment
    with pytest.raises(DeploymentError, match="frontend image digest"):
        deployer.deploy(IMAGE, "rpi-v0.1.0", REVISION, "ghcr.io/parth-shastri/theos-web:latest")
    assert not calls
