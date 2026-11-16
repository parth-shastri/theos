"""Deploy the pinned Langfuse Compose stack for local Theos trace testing."""

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


def create_local_config():
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
        return

    def token(size=32):
        return secrets.token_hex(size)

    postgres_password = token()
    minio_password = token()
    public_key = f"pk-lf-{token(20)}"
    secret_key = f"sk-lf-{token()}"
    admin_password = token()
    values = {
        "LANGFUSE_IMAGE_TAG": LANGFUSE_TAG.removeprefix("v"),
        "NEXTAUTH_URL": "http://localhost:3000",
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
        "Local URL: http://127.0.0.1:3000\n"
        f"Email: {values['LANGFUSE_INIT_USER_EMAIL']}\n"
        f"Password: {admin_password}\n"
        f"Project: {values['LANGFUSE_INIT_PROJECT_NAME']}\n"
        f"Public key: {public_key}\n"
        f"Secret key: {secret_key}\n"
    )
    access_path.chmod(0o600)


def wait_until_ready(timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:3000", timeout=3) as response:
                if response.status < 500:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError("Langfuse UI did not become ready at http://127.0.0.1:3000")


def main():
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

    create_local_config()
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
    wait_until_ready()
    print("Langfuse is ready at http://127.0.0.1:3000")
    print(f"Private access details: {access_path_for_user()}")
    print(f"Private OTLP headers: {LOCAL / 'theos-headers.json'}")


def access_path_for_user():
    return LOCAL / "access.txt"


if __name__ == "__main__":
    main()
