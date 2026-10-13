# Read the Theos code

Start with a user message, then follow the turn into its service.
Each service has its own directory under `src/theos/services`.
Small services keep their tools in one file.
Larger services separate clients, validation, and background work.

![Runtime and service boundaries](architecture/theos-services.png)

This runtime diagram is the main source navigation view.
It maps the [Agent Harness framework](architecture.md#complete-framework) to implemented services and directories.
Read the [architecture guide](architecture.md) for the full framework, memory, tools, and operations paths.

## Find a responsibility

All source paths below start at `src/theos`.

| Area | Responsibility | Start here |
| --- | --- | --- |
| Server | Start one HTTP worker and scheduler | `server.py` |
| Configuration | Validate environment settings | `settings.py` |
| Runtime | Reserve turns and run the harness | `runtime/engine.py` |
| Approvals | Match decisions to unchanged actions | `runtime/approvals.py` |
| Checkpoints | Save tool attempts and recover results | `runtime/checkpoints.py`, `runtime/hooks.py` |
| Final answers and failures | Reserve a final model call after runtime limits. Explain failures without exposing raw findings | `runtime/recovery.py`, `runtime/errors.py` |
| Context and output | Resolve provider capacities and share compaction rules across agents | `runtime/context.py` |
| Call budgets | Count calls without enforcement by default. Retain optional bounded allocations | `runtime/budgets.py` |
| Connector wrappers | Page verbose account results and retain complete sources | `runtime/connector_wrappers.py` |
| History retrieval | Read bounded pages of original evidence after compaction | `runtime/history_tools.py`, `runtime/history_content.py` |
| Deep research | Gate explicit mode and persist research evidence, notes, reports, and checkpoints | `runtime/research_mode.py`, `services/research/`, migration 010 |
| Delivery events | Turn harness events into transport events | `runtime/events.py`, `runtime/turn.py` |
| Providers and usage | Build model clients, retain OpenRouter reasoning and costs, and record usage | `runtime/models.py`, `runtime/model_catalog.py`, `runtime/openrouter.py`, `runtime/usage.py` |
| Scheduler | Deliver reminders and run agent tasks, memory consolidation, and Health work | `runtime/scheduler.py`, `runtime/scheduled.py` |
| Storage | SQLite transactions, migrations, restart recovery, and application message display metadata | `storage/database.py`, `storage/messages.py`, `storage/migrations/` |
| Telegram | Poll updates, authenticate senders, onboard users, handle commands and media | `transports/telegram/` |
| Browser | Serve chat, owner-scoped activity, administrator usage aggregates, uploads, and streamed replies | `transports/browser/app.py`, `transports/browser/activity.py`, `transports/browser/static/` |
| Browser enrollment | Confirm Telegram-owned browser sign-in, issue hashed credentials, and revoke generated access | `storage/browser_access.py`, `transports/browser/auth.py`, `transports/telegram/web_access.py` |
| Terminal | Run `theos` as a deployed workspace client or standalone runtime, with a generic renderer | `transports/terminal/cli.py`, `remote.py`, `routes.py`, `wire.py`, `session.py`, `app.py`, `screens.py` |
| Operations | Redact logs, export OTel spans, and make consistent backups | `operations/logging.py`, `operations/tracing.py`, `backup.py` |

## Follow one turn

The owned harness keeps the pinned summary template in `src/harness/compression_policy.py`.
`src/harness/summary_references.py` extracts exact identifiers independently of model prose.
`src/harness/lean_context.py` bounds their request index and commits working memory through the runtime callback.
Application research ownership remains in `services/research/`.

1. Read `Telegram.handle()` or the browser chat route to see how the transport identifies the owner.
2. Read `Runtime.start()` to see the ownership checks and conversation reservation.
3. Read `Runtime.run()` to follow its five numbered steps.
4. Read `runtime/tools.py` to see which services the conversation can access.
5. Read the selected service's `tools.py` to follow its validation and action.
6. Read `runtime/hooks.py` to find the durable model and tool checkpoints.
7. Read `runtime/events.py` to follow text, progress, approval, and file delivery.

The runtime allows one active turn per conversation.
A shared semaphore limits concurrent turns across conversations.
The event queue can discard old display events when a client stops reading.
SQLite retains the durable conversation and tool state.
The standalone terminal requests raw harness events through its turn queue.
Its adapter converts these events for the generic renderer under `src/renderer`.
The adapter uses the same runtime tools, checkpoints, and approval policy.
It restores approval prompts after restart and keeps local owner identities separate from Telegram and browser owners.
Connected terminal mode uses `remote.py` to call authenticated HTTP endpoints on the deployment.
`routes.py` binds these calls to the browser owner and shared browser conversations.
`wire.py` converts raw harness events into display-only JSON without provider state or harness run results.
The client never opens SQLite or starts another scheduler. Disconnects leave server work running.
`ClientSettings` reads only the server URL and token before the command loads standalone service settings.
`screens.py` owns terminal settings and usage dialogs. The application adds commands through generic renderer extension points.

## Work within a service

| Service directory | Contents |
| --- | --- |
| `preferences/` | Timezone, calorie goal, display name, and instruction override |
| `reminders/` | Reminder tools and explicit handling of ambiguous local times |
| `schedules/` | Owner-scoped scheduled agent task tools and recurrence validation |
| `meals/` | Meal validation, saved records, daily totals, and export intent |
| `training/` | Program validation, versions, workout history, and metrics |
| `custom_tables/` | Private SQLite tables and bounded query templates |
| `memory/` | Mem0 HTTP client, ownership checks, bounded retrieval, consented consolidation, and explicit tools |
| `search/`, `weather/`, `skills/` | Search fallback, forecasts, and bounded skill resources |
| `files/` | Private catalog, image validation, R2 transfers, source objects, model checkpoints, and file tools |
| `voice/` | Transcription and Kokoro clients with audio tools |
| `sandbox/` | Remote lifecycle client, execution tools, and versioned task workspaces |
| `google/` | Shared Google OAuth state, token encryption, refresh, and disconnection |
| `gmail/` | Gmail requests, draft previews, and account tools |
| `health/` | Imports, normalization, records, nutrition exports, job retries, and tools |
| `zepto/` | OAuth, encrypted owner tokens, MCP discovery, and account-scoped sessions that serialize tool calls |

`storage/account_access.py` permits configured browser identities and authorized private Telegram identities.
`transports/browser/connections.py` binds account actions to the authenticated browser owner.
It reports configuration status without exposing credentials.
Groups and standalone terminal sessions receive no account tools.
Connected terminal clients use the authenticated browser user's existing account access.
Configured browser IDs cannot overlap reserved Telegram and terminal namespaces.
Generated browser credentials reuse the verified Telegram owner's private records and account access.
Telegram and browser conversation threads remain separate.

`services/personal.py` and `services/information.py` only collect related tools.
They contain no database rules or external requests.
The runtime creates clients explicitly and closes them during shutdown.
`runtime/scheduled.py` claims durable scheduled occurrences and delivers ordinary runtime turns.
`services/memory/automation.py` owns retrieval, consent policy, and consolidation batches.
No service registry or inheritance hierarchy hides those dependencies.

For Google Health, read these files in order:

1. Read `client.py` for account requests and service entry points.
2. Read `imports.py` for pagination and complete summary storage.
3. Read `queue.py` for export intent saved with a meal transaction.
4. Read `nutrition.py` for the six numbered reconciliation steps.
5. Read `jobs.py` for ordering, retry delay, and cancellation checks.

## Check approvals and recovery

The approval policy matches the saved call, arguments, decision, expiry, and review contents.
Gmail reads the draft again at approval and immediately before sending.
The final read cannot lock the draft against edits from another client.

A tool attempt enters SQLite before execution starts.
The after-tool hook saves its result before the next model request.
After a restart, unfinished tool calls have an unknown outcome.
The runtime does not repeat them automatically.
Health jobs inspect named remote records before another write.

The Telegram polling loop has three numbered steps: receive, save, and dispatch.
It saves updates and the polling offset in one transaction.
An interrupted reply does not cause another model turn.
`transports/telegram/onboarding.py` reserves user slots and asks for a preferred name and timezone before normal routing.
Owner-scoped preferences retain the chosen name across restarts and conversation resets.
`runtime/engine.py` supplies the saved display name to the model on each turn.
`storage/telegram_access.py` checks SQL authorization and removes access-code arguments before inbox storage.
Commands, account tool registration, and OAuth callbacks use the same private account access check.
SQLite counts unique senders, including incomplete setup, against a maximum of 50 Telegram users.

![Telegram and durable checkpoints](architecture/theos-telegram.png)

This sequence explains checkpoint order.
The current transport records durable inbound updates and reminder delivery state.
It does not have a general durable outbox for every streamed reply.

## Write readable changes

Use comments for constraints that a reader cannot infer from an assignment.
Explain ownership checks, transaction boundaries, retry rules, and provider behavior.
Number the major steps in an ordered workflow.
Keep each numbered comment close to the code it explains.

Use ordinary functions for stateless work.
Use a small class when it owns clients, locks, or other lifecycle state.
Keep existing entry points working when moving internal files.
Run the [acceptance checks](runtime/acceptance.md) after changing a service boundary.

The generic compression policy lives in `src/harness/compression_policy.py`.
`src/harness/lean_context.py` connects it to model calls and durable working context.
Assistant storage and sandbox dependencies stay under `src/theos/services`.
