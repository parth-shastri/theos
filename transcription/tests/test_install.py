"""Check private configuration and replacement after launchd delays removal."""

import importlib.util
import plistlib
from pathlib import Path
from types import SimpleNamespace


def test_install_retries_registration_and_preserves_private_configuration(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "install_mlx", Path(__file__).parents[1] / "install.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    runtime = tmp_path / ".local/share/theos-transcription"
    model = runtime / "models/turbo"
    model.mkdir(parents=True)
    (model / "weights.safetensors").touch()
    key = "fixture" * 6
    key_file = tmp_path / "speech.env"
    key_file.write_text("SPEECH_API_KEY=" + key)
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(runtime)
    monkeypatch.setattr(
        installer.sys,
        "argv",
        [
            "install.py",
            "--host",
            "127.0.0.1",
            "--model-path",
            str(model),
            "--key-file",
            str(key_file),
        ],
    )
    registrations = []

    def run(command, **kwargs):
        if command[1] == "bootstrap":
            registrations.append(command)
            return SimpleNamespace(returncode=5 if len(registrations) == 1 else 0)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(installer.subprocess, "run", run)
    monkeypatch.setattr(installer.time, "sleep", lambda _: None)
    installer.main()
    environment = (runtime / ".env").read_bytes()
    installer.main()
    assert len(registrations) == 3
    assert (runtime / ".env.previous").read_bytes() == environment
    assert (runtime / ".env").stat().st_mode & 0o777 == 0o600
    plist = tmp_path / "Library/LaunchAgents" / (installer.LABEL + ".plist")
    assert plist.stat().st_mode & 0o777 == 0o600
    assert key.encode() not in plist.read_bytes()
    config = plistlib.loads(plist.read_bytes())
    assert config["KeepAlive"] is True
    assert config["EnvironmentVariables"]["HF_HUB_OFFLINE"] == "1"
    assert config["EnvironmentVariables"]["HF_HOME"].startswith(str(runtime))
