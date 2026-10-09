# Development

## Requirements

Use Python 3.12 or later and uv.
The container uses Python 3.13.
The application uses `fcntl` for its process lock, so local execution needs a compatible Unix environment.
Use Docker on other hosts.
The JavaScript syntax check below needs Node.

## Local application

1. Install the locked dependencies.

   ```sh
   uv sync --locked --extra server --extra terminal
   ```

2. Copy the minimal settings if `.env` does not exist.

   ```sh
   cp .env.minimal .env
   chmod 600 .env
   ```

3. Set `AGENT_NAME` and the browser credentials in `.env`.
4. Set `AGENT_PROVIDER=fake` for a local run without model calls.
5. Start the server.

   ```sh
   uv run --no-sync python -m theos.server
   ```

The fake provider returns a fixed response and does not exercise tools.
A real provider needs its credential in `AGENT_API_KEY`.
The default local address is `http://127.0.0.1:8080`.

Start the terminal UI with `uv run --no-sync theos`.
The installed `theos` command also opens this UI.
Read the [terminal guide](terminal.md) for installation, local profiles, settings, and saved conversations.
The terminal and HTTP server each require exclusive access to their data directory.

## Docker development

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

The development file mounts the four source packages into the container.
Restart the service after Python changes.
Rebuild the image after dependency changes.
The overlay does not enable automatic reload or Compose Watch.
It retains the host binding from the base configuration.

## Quality checks

Run the deterministic checks after an implementation change:

```sh
uv run --no-sync ruff check src/theos tests/app
uv run --no-sync ruff format --check src/theos tests/app
uv run --no-sync pytest -q
node --check src/theos/transports/browser/static/app.js
uv build
```

The default pytest selection excludes tests marked `live`.
The [acceptance guide](runtime/acceptance.md) lists live checks and recorded results.
The [workflow](../.github/workflows/theos.yml) also checks wheel imports, Compose, and containers on amd64 and arm64.
The container checks use the fake provider and disposable state.

## Add or change a tool

1. Read [project memory](../MEMORY.md) before changing the implementation plan.
2. Find the owning service in the [code guide](code-structure.md).
3. Put the callable in that service under `src/theos/services`.
4. Bind the authenticated owner when constructing the tool.
5. Register the tool in `runtime/tools.py` or the appropriate service collector.
6. Add approval rules for sensitive actions in `runtime/approvals.py`.
7. Check ownership, service failure, and uncertain outcomes with relevant tests.
8. Update the [tool catalog](tool-catalog.md) and service guide.
9. Record new project decisions in `MEMORY.md`.

Keep provider and protocol rules inside the owning service.
Keep generic harness behavior under `src/harness`.
Transport modules handle authentication and delivery.
They do not own service records or external protocols.
Preserve source notices and provenance manifests.

## Maintain documentation

The [documentation map](documentation-map.md) is the navigation index.
The repository contains Markdown guides and local diagram previews.
It does not configure a documentation publishing service.

1. Check commands against the current source and environment samples.
2. Use Simplified Technical English for prose and procedures.
3. Embed the existing PNG diagrams where they explain the topic.
4. Label planned framework components explicitly.
5. Use the Excalidraw MCP for diagram edits.
6. Keep editable sources, element files, and previews in sync.
7. Use Excalidraw font family `1` for diagram text.
8. Check local links and the modified prose before delivery.

Read the [diagram library](architecture/README.md) for source files and preview commands.
