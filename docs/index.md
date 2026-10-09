# Theos documentation

Theos is a private personal assistant for Telegram, browser chat, and the terminal.
It uses an owned Python harness, SQLite, and optional external services.
The default model is `gpt-6-luna` through OpenAI Responses.
Set `AGENT_NAME` to choose the assistant name.

## Choose a task

| Task | Guide |
| --- | --- |
| Deploy to a server | [First deployment](DEPLOYMENT.md) |
| Connect the primary transport | [Telegram setup](telegram-setup.md) |
| Use browser chat | [Browser guide](browser.md) |
| Use the installed `theos` command | [Terminal guide](terminal.md) |
| Change a setting | [Environment variables](base-infra/environment-variables.md) |
| Host or connect memory services | [Memory guide](memory.md) |
| Host or connect speech services | [Speech hosting](speech-hosting.md) |
| Maintain an installation | [Operations](operations.md) |
| Diagnose a failure | [Troubleshooting](troubleshooting.md) |
| Change the code | [Development](development.md) |
| Find a guide | [Documentation map](documentation-map.md) |

## Architecture

The uploaded Agent Harness framework defines the architecture.
Its main paths cover working context, model and tool execution, memory, consolidation, and operations feedback.

![Agent Harness framework](architecture/theos-framework.png)

The [architecture guide](architecture.md) explains all six diagrams, starting with the framework.
Each section states what the code implements and what remains planned.
The [runtime diagram](architecture.md#current-implementation) maps those responsibilities to current services.
The [diagram library](architecture/README.md) contains editable sources and previews.

## Runtime boundaries

The application runs one worker and one scheduler per data directory.
Telegram uses outbound polling.
Browser requests require a token that identifies one configured user.
All three transports retain conversations in SQLite across restarts.
The terminal command uses a local profile and starts its own runtime and scheduler.
Gmail, Google Health, and Zepto tools require an authenticated browser or allowed private Telegram identity.

The [acceptance checklist](runtime/acceptance.md) records completed checks and pending live checks.
