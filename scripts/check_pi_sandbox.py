"""Probe fixed-lifetime creation and cached expiry in disposable remote sandboxes."""

import subprocess
from pathlib import Path


def main():
    containers = subprocess.check_output(
        [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.service=theos",
            "--format",
            "{{.ID}}",
        ],
        text=True,
    ).split()
    if len(containers) != 1:
        raise RuntimeError("Require exactly one active Theos application container.")
    source = (
        Path(__file__).resolve().parents[1] / "src/theos/services/sandbox/client.py"
    ).read_text()
    program = (
        "import asyncio, logging, sys\nlogging.disable(logging.CRITICAL)\nnamespace = {}\nexec("
        + repr(source)
        + ", namespace)\n"
        + """
from theos.settings import Settings
from datetime import datetime

class Records:
    def __init__(self): self.rows = {}
    def record(self, owner, kind, key):
        if (owner, kind, key) not in self.rows: raise LookupError()
        return self.rows[owner, kind, key]
    def put_record(self, owner, kind, key, value): self.rows[owner, kind, key] = value
    def delete_record(self, owner, kind, key): self.rows.pop((owner, kind, key), None)

async def probe():
    client = None
    try:
        settings = Settings(_env_file=None)
        settings.sandbox.timeout_seconds = 3600
        store = Records()
        client = namespace['Sandboxes'](settings, store, None)
        first = await client.get('release-probe', 'disposable')
        saved = store.record('release-probe', 'sandbox', 'disposable')
        lifetime = (datetime.fromisoformat(saved['expires_at']) - datetime.fromisoformat(saved['created_at'])).total_seconds()
        assert 3590 <= lifetime <= 3600
        deadline = saved['expires_at']
        assert (await client.get('release-probe', 'disposable')).id == first.id
        assert store.record('release-probe', 'sandbox', 'disposable')['expires_at'] == deadline
        await first.kill()
        second = await client.get('release-probe', 'disposable')
        assert second.id != first.id
        result = await second.commands.run('printf sandbox-probe')
        assert not result.error
        print('Sandbox live probe passed: one-hour creation lifetime, fixed expiry, cached missing instance replaced.')
    except Exception as error:
        print('Sandbox live probe failed:', type(error).__name__)
        return 1
    finally:
        if client is not None:
            await client.destroy('release-probe', 'disposable')
            await client.close()
    return 0

sys.exit(asyncio.run(probe()))
"""
    )
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            containers[0],
            "python",
            "-c",
            "import sys; exec(sys.stdin.read())",
        ],
        input=program,
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
