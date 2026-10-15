"""Set the sandbox creation lifetime without exposing or replacing other secrets."""

import argparse
import os
import re
import tempfile
from pathlib import Path


def prepare(path):
    content = path.read_text()
    pattern = r"^(?:export\s+)?AGENT_SANDBOX__TIMEOUT_SECONDS\s*=.*$"
    updated, count = re.subn(
        pattern, "AGENT_SANDBOX__TIMEOUT_SECONDS=3600", content, flags=re.MULTILINE
    )
    if not count:
        updated = content.rstrip("\n") + "\nAGENT_SANDBOX__TIMEOUT_SECONDS=3600\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".theos-env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    prepare(parser.parse_args().env_file)
    print("Pi environment prepared: sandbox lifetime 3600 seconds. Other settings retained.")
