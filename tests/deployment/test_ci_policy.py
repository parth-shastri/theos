"""CI must retain destination coverage and reject failed or missing checks."""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from scripts.ci_policy import EXTENDED, STANDARD, main, select_architectures

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repository(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-b", "dev")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    git("add", ".")
    git("commit", "-m", "initial")
    base = git("rev-parse", "HEAD")

    def commit(path, content="changed\n"):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
        git("add", ".")
        git("commit", "-m", "change")
        return git("rev-parse", "HEAD")

    return tmp_path, git, base, commit


def push(branch, before="0" * 40, after="1" * 40):
    return {"ref": f"refs/heads/{branch}", "before": before, "after": after}


def pull_request(branch, base="0" * 40, head="1" * 40):
    return {"pull_request": {"base": {"ref": branch, "sha": base}, "head": {"sha": head}}}


@pytest.mark.parametrize(
    "event_name, event", [("push", push("main")), ("pull_request", pull_request("main"))]
)
def test_main_requires_all_standard_architectures(event_name, event):
    assert select_architectures(event_name, event) == STANDARD


@pytest.mark.parametrize(
    "event_name, event", [("push", push("rpi")), ("pull_request", pull_request("rpi"))]
)
def test_rpi_requires_only_arm64(event_name, event):
    assert select_architectures(event_name, event) == ["arm64"]


@pytest.mark.parametrize("extended, expected", [(False, STANDARD), (True, EXTENDED)])
def test_manual_run_can_validate_every_architecture(extended, expected):
    assert select_architectures("workflow_dispatch", {}, extended=extended) == expected


@pytest.mark.parametrize("event_name", ["push", "pull_request"])
@pytest.mark.parametrize(
    "path, expected",
    [
        ("src/theos/server.py", []),
        ("docs/releases.md", []),
        ("Dockerfile", ["arm64"]),
        (".dockerignore", ["arm64"]),
        ("pyproject.toml", ["arm64"]),
        ("uv.lock", ["arm64"]),
        ("compose.dev.yaml", ["arm64"]),
        (".github/workflows/theos.yml", ["arm64"]),
        ("scripts/deploy_rpi.py", ["arm64"]),
        ("tests/deployment/test_ci_policy.py", ["arm64"]),
    ],
)
def test_dev_builds_only_when_build_files_change(repository, event_name, path, expected):
    root, _, base, commit = repository
    head = commit(path)
    event = push("dev", base, head) if event_name == "push" else pull_request("dev", base, head)
    assert select_architectures(event_name, event, root=root) == expected


def test_push_checks_every_commit_in_the_batch(repository):
    root, _, base, commit = repository
    commit("uv.lock")
    head = commit("README.md")
    assert select_architectures("push", push("dev", base, head), root=root) == ["arm64"]


def test_pr_excludes_build_changes_only_on_the_destination(repository):
    root, git, base, commit = repository
    git("switch", "-c", "feature/example")
    head = commit("README.md")
    git("switch", "dev")
    base = commit("Dockerfile")
    assert select_architectures("pull_request", pull_request("dev", base, head), root=root) == []


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_removal_of_a_build_file_retains_container_checks(repository, operation):
    root, git, base, _ = repository
    if operation == "rename":
        git("mv", "Dockerfile", "old-container.txt")
    else:
        git("rm", "Dockerfile")
    git("commit", "-m", operation)
    event = pull_request("dev", base, git("rev-parse", "HEAD"))
    assert select_architectures("pull_request", event, root=root) == ["arm64"]


@pytest.mark.parametrize("before", ["0" * 40, "1" * 40, "--invalid"])
def test_missing_or_invalid_history_retains_arm64(repository, before):
    root, _, _, commit = repository
    head = commit("README.md")
    assert select_architectures("push", push("dev", before, head), root=root) == ["arm64"]


def test_release_uses_its_separate_image_acceptance():
    event = {"ref": "refs/tags/rpi-v0.1.4"}
    assert select_architectures("push", event, release_image=True) == []


@pytest.mark.parametrize(
    "event_name, event", [("push", push("main")), ("pull_request", pull_request("rpi"))]
)
def test_separate_release_image_cannot_skip_branch_container_checks(event_name, event):
    with pytest.raises(ValueError, match="Only a Pi release"):
        select_architectures(event_name, event, release_image=True)


@pytest.mark.parametrize(
    "event_name, event", [("push", push("topic")), ("push", {"ref": "refs/tags/rpi-v0.1.4"})]
)
def test_unconfigured_events_cannot_report_success(event_name, event):
    with pytest.raises(ValueError):
        select_architectures(event_name, event)


def test_event_file_writes_a_valid_matrix_without_erasing_other_outputs(tmp_path, monkeypatch):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(push("rpi")))
    output_file = tmp_path / "outputs"
    output_file.write_text("existing=value\n")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.delenv("CI_RELEASE_IMAGE", raising=False)
    main()
    assert output_file.read_text() == 'existing=value\narchitectures=["arm64"]\n'


@pytest.mark.parametrize(
    "quality, tests, container, architectures, accepted",
    [
        ("success", "success", "skipped", "[]", True),
        ("success", "success", "success", '["arm64"]', True),
        ("success", "success", "skipped", '["arm64"]', False),
        ("success", "success", "failure", '["arm64"]', False),
        ("success", "success", "cancelled", '["arm64"]', False),
        ("failure", "success", "skipped", "[]", False),
        ("cancelled", "success", "skipped", "[]", False),
        ("success", "failure", "skipped", "[]", False),
        ("success", "skipped", "skipped", "[]", False),
        ("success", "success", "success", "", False),
    ],
)
def test_actual_workflow_gate_rejects_failed_or_missing_checks(
    quality, tests, container, architectures, accepted
):
    workflow = (ROOT / ".github/workflows/theos.yml").read_text()
    gate = textwrap.dedent(workflow.split("  passed:\n", 1)[1].split("        run: |\n", 1)[1])
    result = subprocess.run(
        ["bash", "-e", "-c", gate],
        env={
            **os.environ,
            "QUALITY": quality,
            "TESTS": tests,
            "CONTAINER": container,
            "ARCHITECTURES": architectures,
        },
        check=False,
    )
    assert (result.returncode == 0) is accepted
