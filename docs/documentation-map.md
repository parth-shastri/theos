# Documentation map

This map organizes the guides by installation task.
Configuration defaults come from the current application source and Compose files.

## Start and use

| Guide | Contents |
| --- | --- |
| [Documentation home](index.md) | Starting points, framework overview, and runtime boundaries |
| [First deployment](DEPLOYMENT.md) | Server requirements, configuration, first start, and private access |
| [Telegram setup](telegram-setup.md) | Bot credentials, allowlists, commands, media, and approvals |
| [Browser guide](browser.md) | Tokens, sessions, model choices, files, and dashboard access |
| [Terminal guide](terminal.md) | Installed command, local profiles, sessions, images, steering, and approvals |
| [Personal tools](personal-tools.md) | Preferences, reminders, meals, training, and private tables |
| [Scheduled tasks](scheduled-tasks.md) | One-time and recurring agent work, approvals, and recovery |

## Configure services

| Guide | Contents |
| --- | --- |
| [Environment variables](base-infra/environment-variables.md) | Application defaults, limits, precedence, and Compose variables |
| [External services](services.md) | Models, search, weather, skills, and integration setup |
| [Memory](memory.md) | Self-hosted Mem0, managed Platform limits, owner scope, and explicit saves |
| [Sandbox](sandbox.md) | Remote execution, browser dependencies, and sandbox lifetime |
| [Files and voice](files-and-voice.md) | Local files, R2 archives, transcription, and speech |
| [Speech hosting](speech-hosting.md) | Docker, native MLX/MPS, hosted providers, SSD storage, and speech checks |
| [Gmail](gmail.md) | Authorization, messages, drafts, and send approval |
| [Google Health](google-health.md) | Authorization, imports, meal exports, and retries |
| [Zepto MCP](zepto-mcp.md) | External authorization, tool discovery, and approvals |

## Operate

| Guide | Contents |
| --- | --- |
| [Operations](operations.md) | Status, backups, restore, upgrades, and recovery |
| [Git and releases](releases.md) | CI, Raspberry Pi tags, activation, and rollback |
| [Troubleshooting](troubleshooting.md) | Symptoms, causes, and corrective actions |
| [Observability](base-infra/observability.md) | Local logs, OTel turn traces, Jaeger waterfalls, usage, and retention |
| [Compose workflow](base-infra/docker-compose-workflow.md) | Network, volume, resource, and lifecycle settings |
| [Docker image](base-infra/dockerfile-strategy.md) | Build stages, dependencies, runtime user, and image contents |
| [Acceptance](runtime/acceptance.md) | Recorded results and live service checks |

## Understand and develop

| Guide | Contents |
| --- | --- |
| [Architecture](architecture.md) | Framework, all six diagrams, and current implementation |
| [Code structure](code-structure.md) | Runtime diagram, source paths, and the order of a turn |
| [Development](development.md) | Local commands, tests, service changes, and documentation rules |
| [Tool catalog](tool-catalog.md) | Callable names, dependencies, and approval rules |
| [Diagram library](architecture/README.md) | PNG previews, editable sources, and implementation status |

The [repository README](../README.md) is the short entry point.
