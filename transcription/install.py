"""Install the native login agent from its internal-disk runtime directory."""

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

LABEL = "com.parthshastri.theos-transcription"


def write_private(path, content):
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".previous"))
    temporary = path.with_suffix(path.suffix + ".tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(content)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Loopback or the host's private Tailscale IP")
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--key-name", default="SPEECH_API_KEY")
    args = parser.parse_args()
    runtime = Path.home() / ".local/share/theos-transcription"
    if sys.platform != "darwin" or Path.cwd().resolve() != runtime.resolve():
        raise SystemExit(
            "Run this installer from ~/.local/share/theos-transcription on the Mac mini."
        )
    if not (args.model_path / "weights.safetensors").is_file():
        raise SystemExit("Download the pinned model before installing the login agent.")
    if args.model_path.resolve().is_relative_to(Path("/Volumes")):
        raise SystemExit(
            "Copy the active model to internal storage before installing the login agent."
        )
    key = dotenv_values(args.key_file).get(args.key_name, "")
    if not key or len(key) < 32 or any(c in key for c in '\n\r"\\'):
        raise SystemExit("Supply an existing speech key with at least 32 characters.")
    values = {
        "AGENT_MLX_KEY": key,
        "AGENT_MLX_HOST": args.host,
        "AGENT_MLX_PORT": "8002",
        "AGENT_MLX_MODEL_PATH": str(args.model_path.resolve()),
        "AGENT_MLX_FFMPEG": "/opt/homebrew/bin/ffmpeg",
    }
    write_private(runtime / ".env", "".join(f'{k}="{v}"\n' for k, v in values.items()).encode())
    logs = Path.home() / "Library/Logs/Theos"
    logs.mkdir(parents=True, exist_ok=True)
    agents = Path.home() / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / (LABEL + ".plist")
    write_private(
        plist,
        plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": [str(runtime / ".venv/bin/theos-transcription")],
                "WorkingDirectory": str(runtime),
                "EnvironmentVariables": {
                    "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                    "PYTHONUNBUFFERED": "1",
                    "HF_HUB_OFFLINE": "1",
                    "HF_HOME": str(runtime / "cache/huggingface"),
                },
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": 15,
                "StandardOutPath": str(logs / "transcription.stdout.log"),
                "StandardErrorPath": str(logs / "transcription.stderr.log"),
            }
        ),
    )
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    subprocess.run(["launchctl", "enable", domain + "/" + LABEL], check=True)
    # Launchd can retain the old registration briefly after a successful bootout.
    for _ in range(10):
        result = subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise SystemExit("Login agent registration failed. Inspect launchctl before retrying.")
    print("Installed MLX transcription agent:", plist)


if __name__ == "__main__":
    main()
