"""Release gates must reject tags from another revision or with a mismatched version."""

import subprocess

import pytest

from scripts.check_release import check_release


@pytest.fixture
def repository(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-b", "rpi")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    git("add", ".")
    git("commit", "-m", "initial")
    revision = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/rpi", revision)
    git("tag", "-a", "rpi-v0.1.0", "-m", "release")
    return tmp_path, git, revision


def test_accepts_annotated_tag_at_rpi_tip(repository):
    root, _, revision = repository
    assert check_release("rpi-v0.1.0", root) == revision


@pytest.mark.parametrize("tag", ["v0.1.0", "rpi-v01.1.0", "rpi-v0.1.0-rc1", "../rpi"])
def test_rejects_invalid_release_names(repository, tag):
    with pytest.raises(ValueError, match="release tag"):
        check_release(tag, repository[0])


def test_rejects_mismatched_package_version(repository):
    with pytest.raises(ValueError, match="differs from package"):
        check_release("rpi-v0.2.0", repository[0])


def test_rejects_tag_when_rpi_has_advanced(repository):
    root, git, _ = repository
    (root / "another.txt").write_text("new commit")
    git("add", ".")
    git("commit", "-m", "advance")
    git("update-ref", "refs/remotes/origin/rpi", git("rev-parse", "HEAD"))
    git("checkout", "rpi-v0.1.0")
    with pytest.raises(ValueError, match="current origin/rpi"):
        check_release("rpi-v0.1.0", root)
