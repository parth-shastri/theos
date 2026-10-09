# Docker image

The [Dockerfile](../../Dockerfile) uses two stages based on `python:3.13-slim`.
The builder installs dependencies and the application.
The runtime contains the installed application and its virtual environment.

## Build context

The [.dockerignore](../../.dockerignore) allows the package metadata, lockfile, license, README, and four source packages.
It excludes environment files, local databases, caches, and unrelated workspace content.
The Dockerfile copies only the inputs needed for installation.

## Builder

The builder installs `uv==0.9.26` through pip.
It copies `pyproject.toml` and `uv.lock` before application source.
This order lets Docker reuse the dependency layer after a source change.
A BuildKit cache mount retains uv downloads between builds.

The dependency installation uses:

```sh
uv sync --locked --no-install-project --no-dev --extra server
```

After copying the source, the builder installs the package with:

```sh
uv sync --locked --no-editable --no-dev --extra server
```

The builder sets `UV_LINK_MODE=copy`, `UV_COMPILE_BYTECODE=1`, and `UV_PYTHON_DOWNLOADS=never`.
It uses the base image Python interpreter.

## Runtime

The runtime creates the `theos` user and group with ID `10001`.
It creates `/data` with that ownership.
It copies `/app` from the builder with the same ownership.
The server starts as that user without a root entrypoint.

| Variable | Value |
| --- | --- |
| `VIRTUAL_ENV` | `/app/.venv` |
| `PATH` prefix | `/app/.venv/bin` |
| `PYTHONUNBUFFERED` | `1` |
| `PYTHONDONTWRITEBYTECODE` | `1` |
| `AGENT_HOST` | `0.0.0.0` |
| `AGENT_PORT` | `8080` |
| `AGENT_DATA_DIR` | `/data` |

The command is `python -m theos.server`.
The image healthcheck calls `/ready` every 30 seconds.
It allows a 20-second startup period, a five-second timeout, and three failed attempts.

## Build and inspect

```sh
docker build --tag theos:local .
docker image inspect theos:local
```

The [acceptance workflow](../../.github/workflows/theos.yml) builds Linux amd64 and arm64 images.
Its container checks cover startup, fake chat, persistence after restart, user ID, and resource snapshots.
They do not prove live model or integration access.

## External dependencies

The image does not run a memory server, vector database, sandbox server, or speech model.
The application calls those services through configured endpoints.
Browser automation also needs `agent-browser` and browser dependencies inside the remote sandbox image.
See [external services](../services.md) and [sandbox](../sandbox.md).
