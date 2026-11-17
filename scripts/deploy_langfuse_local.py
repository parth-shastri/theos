"""Deploy the pinned Langfuse Compose stack for local Theos trace testing."""

import argparse
import base64
import secrets
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".theos" / "langfuse-local"
UPSTREAM = LOCAL / "upstream"
LANGFUSE_TAG = "v4.80.0"
NETWORK = "theos-observability"


def run(command, *, cwd=None, quiet=False):
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL if quiet else None,
    )


def create_local_config(port, public_url):
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    env_path = UPSTREAM / ".env"
    headers_path = LOCAL / "theos-headers.json"
    access_path = LOCAL / "access.txt"
    if env_path.exists():
        if not headers_path.exists() or not access_path.exists():
            raise RuntimeError(
                f"Existing {env_path} is missing its private key files. Restore them before deploy."
            )
        values = dict(
            line.split("=", 1)
            for line in env_path.read_text().splitlines()
            if line.startswith(("LANGFUSE_UI_PORT=", "NEXTAUTH_URL="))
        )
        existing_port = int(values.get("LANGFUSE_UI_PORT", 3000))
        if port is not None and port != existing_port:
            raise RuntimeError(f"Existing deployment uses port {existing_port}.")
        if public_url is not None and public_url != values.get("NEXTAUTH_URL"):
            raise RuntimeError("Existing deployment uses a different public URL.")
        return existing_port

    port = 3000 if port is None else port
    public_url = public_url or f"http://localhost:{port}"

    def token(size=32):
        return secrets.token_hex(size)

    postgres_password = token()
    minio_password = token()
    public_key = f"pk-lf-{token(20)}"
    secret_key = f"sk-lf-{token()}"
    admin_password = token()
    values = {
        "LANGFUSE_IMAGE_TAG": LANGFUSE_TAG.removeprefix("v"),
        "LANGFUSE_UI_PORT": port,
        "NEXTAUTH_URL": public_url,
        "NEXTAUTH_SECRET": token(),
        "DATABASE_URL": f"postgresql://postgres:{postgres_password}@postgres:5432/postgres",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_DB": "postgres",
        "SALT": token(),
        "ENCRYPTION_KEY": token(),
        "CLICKHOUSE_USER": "clickhouse",
        "CLICKHOUSE_PASSWORD": token(),
        "MINIO_ROOT_USER": "langfuse",
        "MINIO_ROOT_PASSWORD": minio_password,
        "LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID": "langfuse",
        "LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY": minio_password,
        "LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID": "langfuse",
        "LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY": minio_password,
        "LANGFUSE_S3_BATCH_EXPORT_ACCESS_KEY_ID": "langfuse",
        "LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY": minio_password,
        "REDIS_AUTH": token(),
        "TELEMETRY_ENABLED": "false",
        "LANGFUSE_INIT_ORG_ID": "theos-local",
        "LANGFUSE_INIT_ORG_NAME": "Theos-Local",
        "LANGFUSE_INIT_PROJECT_ID": "theos-local",
        "LANGFUSE_INIT_PROJECT_NAME": "Theos-Local",
        "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": public_key,
        "LANGFUSE_INIT_PROJECT_SECRET_KEY": secret_key,
        "LANGFUSE_INIT_USER_EMAIL": "local@theos.test",
        "LANGFUSE_INIT_USER_NAME": "Theos-Local-Operator",
        "LANGFUSE_INIT_USER_PASSWORD": admin_password,
    }
    env_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    env_path.chmod(0o600)
    headers = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    headers_path.write_text(
        f'{{\n  "Authorization": "Basic {headers}",\n  "x-langfuse-ingestion-version": "4"\n}}\n'
    )
    headers_path.chmod(0o600)
    access_path.write_text(
        f"URL: {public_url}\n"
        f"Email: {values['LANGFUSE_INIT_USER_EMAIL']}\n"
        f"Password: {admin_password}\n"
        f"Project: {values['LANGFUSE_INIT_PROJECT_NAME']}\n"
        f"Public key: {public_key}\n"
        f"Secret key: {secret_key}\n"
    )
    access_path.chmod(0o600)
    return port


def wait_until_ready(port, timeout=240):
    url = f"http://127.0.0.1:{port}/api/public/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(f"Langfuse did not become ready at {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, metavar="PORT")
    parser.add_argument("--public-url", help="Browser URL for an HTTPS reverse proxy")
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    if not (UPSTREAM / ".git").exists():
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                LANGFUSE_TAG,
                "https://github.com/langfuse/langfuse.git",
                str(UPSTREAM),
            ]
        )
    version = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=UPSTREAM,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if version != LANGFUSE_TAG:
        raise RuntimeError(f"Expected Langfuse {LANGFUSE_TAG}, found {version}")

    port = create_local_config(args.port, args.public_url)
    run(["docker", "info"], quiet=True)
    network = subprocess.run(
        ["docker", "network", "inspect", NETWORK],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if network.returncode:
        run(["docker", "network", "create", NETWORK], quiet=True)

    compose = [
        "docker",
        "compose",
        "--project-name",
        "langfuse-local",
        "--env-file",
        ".env",
        "-f",
        "docker-compose.yml",
        "-f",
        str(ROOT / "config" / "langfuse-local.compose.yaml"),
    ]
    run([*compose, "config", "--quiet"], cwd=UPSTREAM, quiet=True)
    run([*compose, "up", "-d", "--quiet-pull"], cwd=UPSTREAM)
    wait_until_ready(port)
    print(f"Langfuse is ready on loopback port {port}")
    print(f"Private access details: {access_path_for_user()}")
    print(f"Private OTLP headers: {LOCAL / 'theos-headers.json'}")


def access_path_for_user():
    return LOCAL / "access.txt"


if __name__ == "__main__":
    main()
