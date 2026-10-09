# Theos

Theos is a private personal assistant for Telegram, browser chat, and the terminal.
It uses an owned Python harness, SQLite, and optional external services.
The default model is `gpt-6-luna` through OpenAI Responses.
Set `AGENT_NAME` in `.env` to name your assistant. The default name is `Theos`.

## Start here

| Task | Guide |
| --- | --- |
| Deploy on a server | [First deployment](docs/DEPLOYMENT.md) |
| Connect the primary transport | [Telegram setup](docs/telegram-setup.md) |
| Use browser chat | [Browser guide](docs/browser.md) |
| Connect the terminal to your deployment or run it locally | [Terminal guide](docs/terminal.md) |
| Find a setting or procedure | [Documentation home](docs/index.md) |
| Browse all guides | [Documentation map](docs/documentation-map.md) |

## Start locally

1. Install the locked dependencies.

   ```sh
   uv sync --locked --extra server --extra terminal
   ```

2. Copy `.env.minimal` to `.env`.
3. Set the model key and a unique browser token of at least 32 characters.
4. Start the application.

   ```sh
   uv run python -m theos.server
   ```

5. Open `http://127.0.0.1:8080` and enter the browser token.

For an offline smoke test, set `AGENT_PROVIDER=fake`.
The fake provider returns a fixed answer and does not call tools.
Read [configuration](docs/base-infra/environment-variables.md) and [personal tools](docs/personal-tools.md) for settings and daily use.

## Architecture

The uploaded Agent Harness framework defines the architecture.
It connects working context, the model and tool loop, memory, consolidation, and operations feedback.

![Agent Harness framework](docs/architecture/theos-framework.png)

The [architecture guide](docs/architecture.md) explains all six diagrams and maps the framework to current code.
It identifies implemented components and planned consolidation, retrieval, and evaluation paths.
The [runtime diagram](docs/architecture.md#current-implementation) shows the running services and their boundaries.
The [code guide](docs/code-structure.md) uses that runtime diagram to navigate the source.

## Guides

| Guide | Contents |
| --- | --- |
| [External services](docs/services.md) | Credentials, endpoints, and account connections |
| [Deployment](docs/DEPLOYMENT.md) | First server start and private access |
| [Configuration](docs/base-infra/environment-variables.md) | All application and Compose settings |
| [Operations](docs/operations.md) | Backups, restore, upgrades, and recovery |
| [Troubleshooting](docs/troubleshooting.md) | Failure symptoms and corrective actions |
| [Development](docs/development.md) | Local commands, checks, and service changes |
| [Git and releases](docs/releases.md) | CI, Raspberry Pi tags, deployment, and rollback |
| [Code structure](docs/code-structure.md) | Service areas, turn loop, approvals, and recovery |
| [Tool catalog](docs/tool-catalog.md) | Implemented callables and their service dependencies |
| [Acceptance](docs/runtime/acceptance.md) | Automated coverage and pending live checks |
| [Architecture](docs/architecture.md) | Agent Harness framework, all six diagrams, and implementation mapping |
| [Diagrams](docs/architecture/README.md) | Excalidraw PNG previews and editable drawings |
| [Project memory](MEMORY.md) | Current decisions and implementation limits |
| [Licenses](docs/runtime/notices.md) | Source and font attribution |

## Repository

```text
src/theos/         Assistant services, runtime, transports, and storage
src/harness/       Owned agent harness and provider adapters
src/renderer/      Terminal renderer and session interfaces
src/config/        Logging support used by the harness
tests/            Harness and application acceptance tests
scripts/          Container smoke check and architecture exports
docs/             Current guides, drawings, and source provenance
```

Theos owns its harness copy. It has no package dependency on `agents-intro`.
The original starter and application transfer manifests remain under `docs` for source provenance.
The [acceptance guide](docs/runtime/acceptance.md) separates mock coverage from live service checks.
