# Observability

Theos records application events, tool traces, and model usage locally.
The application log formatter excludes prompts, credentials, and remote error bodies.
Conversation history remains private data in SQLite and needs separate protection.

## Outputs

| Output | Location | Contents |
| --- | --- | --- |
| Application events | `AGENT_DATA_DIR/logs/theos.log` | Fixed event names, timestamps, levels, and selected metadata |
| Runtime traces | `traces` table in `theos.sqlite3` | Owner, session, event, tool name, status, and timestamp |
| Model usage | `usage` table in `theos.sqlite3` | Owner, session, model, token counts, and optional cost estimate |
| Conversation state | `sessions` and related SQLite tables | Messages, tool arguments, results, and approval state |
| Container output | Docker logging driver | Process and HTTP server output |

Compose stores application data under `/data`.
Application events use a file handler and do not propagate to container output.
The server suppresses verbose harness and external client loggers.

## Read application events

```sh
docker compose exec theos python -c   'from pathlib import Path; print(Path("/data/logs/theos.log").read_text()[-16000:])'
```

| Event | Meaning |
| --- | --- |
| `started` | Application workers entered their lifespan |
| `turn_failed` | A model turn raised an exception |
| `integration_unavailable` | Optional integration discovery failed |
| `telegram_update_failed` | An accepted Telegram update failed |
| `notification_failed` | Reminder delivery failed or has an uncertain outcome |
| `scheduler_failed` | Scheduled work raised an exception |

The formatter permits `error_type` and `session_id` metadata.
It does not include exception text or stack traces.
A generic error type can require a separate service check.

## Private dashboard

1. Configure a browser token in `AGENT_USERS`.
2. Add that user ID to `AGENT_ADMINS`.
3. Sign in through the browser page.
4. Open **Admin dashboard**.

`GET /api/dashboard` requires an administrator token.
It returns users, recent sessions, usage totals, recent traces, recent jobs, and the last scheduler tick.
`GET /api/logs` returns up to 100 recent application events.
There is no separate `/dashboard` page.

## Usage and cost

Model checkpoints record input, output, and cached input token counts.
Cost stays absent until both configured rates exist.

```dotenv
AGENT_INPUT_COST_PER_MILLION=0.10
AGENT_OUTPUT_COST_PER_MILLION=0.40
```

These values are illustrative, not current model prices.
Set rates appropriate for your deployment.
The calculation is input tokens times the input rate plus output tokens times the output rate, divided by one million.
Rates apply to all configured models.
The estimate does not represent an invoice or separate cached-token pricing.

## Retention

The application log rotates at 2,000,000 bytes with three backup files.
Compose rotates container logs at 5 MB with three files.
These mechanisms operate independently.

The application has no automatic retention schedule for conversations, tool traces, or usage rows.
Monitor database and volume growth.
The backup command excludes application logs.
Archive required diagnostic evidence separately before a restore or cleanup.

## Planned operations framework

![Operations framework](../architecture/theos-operations.png)

This diagram includes planned evaluation and release feedback paths.
The current application implements local logs, tool traces, usage records, and acceptance checks.
It does not implement the complete evaluation cycle or a remote OpenTelemetry exporter.
No remote telemetry variables exist in the application settings model.

Source: [logging](../../src/theos/operations/logging.py), [usage](../../src/theos/runtime/usage.py), and [browser APIs](../../src/theos/transports/browser/app.py).
