# Feature and acceptance checklist

## Provider state recovery hotfix

A later voice turn transcribed successfully, but its model request mixed OpenAI and Azure encrypted reasoning.
OpenRouter rejected this mixed history with HTTP 400. The following text turn failed for the same reason.
Release 0.1.7 selects the latest known provider format for each OpenAI request and omits incompatible sequences.
It preserves saved history, visible messages, tool exchanges, request options, and ZDR.
A specific mixed-provider rejection permits one retry before generation. Unrelated errors and started streams do not retry.
Empty recovery now returns a clear failure with `failed` status. Useful saved findings retain `partial` status.
No model instructions changed.
The full suite passed 854 tests, with three credential-dependent live checks excluded.
Regression checks cover provider changes across consecutive turns, exact HTTP 400/404 retries, preserved tool exchanges, and empty recovery.
Three live turns completed against a disposable copy of the Pi conversation with mixed OpenAI and Azure state.
The copy used the full runtime and configured services. It did not change production chat or send Telegram messages.
A second diagnostic transcribed the saved seven-second voice note and ran its unchanged text in a disposable fresh conversation.
That turn and the following text turn completed. No Telegram message or scheduled reminder was delivered.
The Pi beta reset clears chats, pending chat actions, Telegram inbox payloads, and trace records.
It retains accounts, preferences, credentials, files, usage records, and the Telegram offset.

## OpenRouter reasoning routing hotfix

On 2026-10-11, the Pi returned partial answers because OpenRouter rejected saved encrypted OpenAI reasoning under ZDR.
The same conversation succeeded without the incompatible reasoning sequences.
Fresh Azure reasoning replay succeeded with ZDR.
The adapter now retries that specific routing rejection once, before any generation event.
The retry preserves ZDR, visible messages, tool exchanges, tools, and model options.
Saved history remains unchanged. Claude signatures and unrelated failures retain their previous behavior.
The full suite passed 844 checks, with three credential-dependent live checks excluded.
A live diagnostic on the Pi completed with the affected history and all 98 tools.
The diagnostic executed no tools and changed no production conversation records.


The capability baseline uses upstream commit `d006624c150973a5637dbfb47ec0b4a6ff3ed613`.
This checklist covers its user-facing capabilities and the additional persistence, transport, and deployment requirements.
Tool names and transport APIs can differ from the upstream ADK interfaces.

## Pinned capability inventory

Read the [code guide](../code-structure.md) for the current service boundaries.

The inventory comes from the pinned tool registry, Telegram handlers, Google account services, and deployment guides.
Each row names the application code and its deterministic acceptance coverage.
Test files are in [`tests/app`](../../tests/app).

| Capability | Application code | Acceptance coverage |
| --- | --- | --- |
| Persistent conversations, resets, model and reasoning choices | `runtime/`, `server.py`, `runtime/models.py` | `test_runtime.py`, `test_interfaces.py` |
| Streaming, tool progress, approvals, bounded concurrent turns | `runtime/` | `test_runtime.py`, `test_interfaces.py` |
| Compaction and bounded research delegates | Existing harness, `runtime/` | Existing compaction tests, `test_integrations.py` |
| Telegram private chats, allowlists, groups, topics, commands | `transports/telegram/` | `test_interfaces.py` |
| Telegram `/start` onboarding, access code, preferred name, timezone, 50-user cap, restart recovery | `transports/telegram/onboarding.py`, `storage/telegram_access.py`, SQLite migrations 003, 004, and 008 | `test_telegram_onboarding.py` |
| Photos, image documents, albums, voice, uploads, file delivery | `transports/telegram/`, `services/files/`, `services/voice/` | `test_interfaces.py`, `test_integrations.py`, `test_regressions.py` |
| Browser chat, sessions, settings, approvals, private dashboard | `transports/browser/` | Browser API workflows and manual browser checks |
| Telegram-confirmed browser enrollment, hashed tokens, device sessions, expiry, revocation, and ordinary user roles | `storage/browser_access.py`, `transports/browser/auth.py`, `transports/telegram/web_access.py`, migration 009 | `test_browser_onboarding.py` |
| Installed terminal command, persistent sessions, images, steering, approvals, scheduled notices, and shutdown | `transports/terminal/`, owned renderer | `test_terminal.py`, existing `test_tui.py`, installed wheel UI turn |
| Connected terminal, shared browser conversations, settings, usage, approvals, and server-owned turns | `transports/terminal/remote.py`, `routes.py`, `wire.py`, `screens.py` | `test_terminal_remote.py`, client-only wheel and real HTTP disconnect checks |
| Memory save, search, list, read, update, delete | `services/memory/` | Ownership and service failures in `test_personal_memory.py` |
| Automatic fact retrieval and opt-in consolidation | `services/memory/automation.py`, migration 005 | Owner isolation, consent, batching, outages, and uncertain writes in `test_automation.py` |
| One-time and recurring agent tasks | `services/schedules/`, `runtime/scheduled.py`, migration 005 | Single execution, access, approval, budget, delivery failure, and restart checks in `test_automation.py` |
| One-time and recurring reminders, cancellation, timezones | `services/reminders/`, `runtime/scheduler.py` | Durable occurrences and daylight-saving checks in `test_personal_memory.py` |
| Preferences, calorie goals, instruction overrides | `services/preferences/` | Preference and meal workflows in `test_personal_memory.py` |
| Meal logging, summaries, editing, deletion | `services/meals/` | `test_personal_memory.py` |
| Rotating training programs, prescriptions, rest days, deload weeks | `services/training/` | `test_personal_memory.py` |
| Workout history, comparable sessions, sets, metrics, deletion | `services/training/` | `test_personal_memory.py` |
| Private tables, query templates, parameterized SQL | `services/custom_tables/` | Ownership, injection, and extension restrictions in `test_personal_memory.py` |
| Exa search, Brave fallback, current weather, forecasts | `services/search/`, `services/weather/`, `services/skills/` | Mock service contracts in `test_integrations.py` |
| Skill discovery and text resources | `services/skills/` | Resource loading and path restrictions in `test_integrations.py` |
| Shell, Python, files, images, browser automation | `services/sandbox/` | OpenSandbox SDK contracts in `test_integrations.py` |
| Sandbox creation, reconnection, renewal, destruction | `services/sandbox/` | Lifecycle and owner isolation in `test_integrations.py` |
| File catalog, R2 archive, restore, deletion | `services/files/` | Storage contracts and ownership in `test_integrations.py` |
| Voice transcription and Kokoro speech | `services/voice/` | Request formats and generated files in `test_integrations.py` |
| Per-user Google authorization and disconnection | `services/google/oauth.py` | State, scopes, encryption, expiry, races, and ownership tests |
| Gmail search, messages, threads, attachments, drafts, labels | `services/gmail/` | `test_oauth_gmail_health.py`, `test_regressions.py` |
| Gmail send approval and draft revalidation | `services/gmail/`, `runtime/` | Changed draft rejection and single confirmed send |
| Google Health summaries and scheduled imports | `services/health/` | Pagination, daily summaries, and scheduler isolation |
| Nutrition export, backfill, edits, deletion, retries | `services/health/`, `services/meals/` | Durable export reconciliation and cancellation tests |
| Per-owner Zepto OAuth, encrypted credentials, Telegram return handoff, tools, and approvals | `services/zepto/`, `transports/telegram/`, `runtime/` | `test_zepto.py` covers encrypted restart storage, owner and state binding, inbox redaction, and chat isolation. Regression tests cover schemas and approvals |
| Redacted logs, traces, token usage, cost estimates | `operations/logging.py`, `runtime/`, `server.py` | Accounting, dashboard access, and log redaction tests |
| OTel turn waterfalls and OTLP/HTTP export | `operations/tracing.py`, runtime model and tool boundaries | `test_tracing.py`, Jaeger ingestion and restart checks |
| Partial answers after runtime limits | `runtime/recovery.py`, delegate boundaries | `test_recovery.py`, terminal, schedule, and tracing checks |
| Migrations, restart recovery, one scheduler, health endpoints | `storage/database.py`, `runtime/scheduler.py`, `server.py` | Database reopen, process lock, and restart tests |
| Consistent backup and restore | `backup.py` | Database and file restoration in `test_integrations.py` |
| Locked image, non-root runtime, both architectures | `Dockerfile`, Compose files | Container chat, restart, UID, and resource checks |

A seven-day training program supplies a weekly split through the same training tools.
Set the instruction preference to an empty string to remove an override.
The weather tool returns both current conditions and a forecast.
The application loads skill resources from an operator-controlled directory.
It does not bundle the upstream ADK skill registry.

## Current verification

Release 0.1.5 raises the default total to 30 calls with proportional allowances.
The allocation is 23 research calls, five compaction calls, and two recovery calls, with ten calls per delegate.
Recovery can use its second tool-free attempt within the existing 15-second deadline.
The final local suite passed 837 tests, with three live tests excluded, after integration with the current CI policy.
Lint, formatting, lock validation, and package builds passed for version 0.1.5.
The version and all release documentation changes are included in the tracing PR.
Jaeger access remains private to operators, without built-in passwords or per-user trace isolation.


The 2026-10-10 tracing update adds optional, content-free OTel spans and OTLP/HTTP protobuf export.
Twenty-one deterministic checks cover model and tool ownership, parallel delegates, title and compaction calls, errors, cancellation, approvals, sampling, redaction, and shutdown.
Concurrent turns and later turns share conversation identifiers without sharing trace identifiers.
Five log checks cover size rotation, age rotation, expired backups, quiet processes, and cleanup failures.
A local HTTP receiver verified the protobuf payload, trace hierarchy, endpoint, and authentication headers.
Jaeger `2.22.0` displayed a 12-span fake-model turn with two overlapping research delegates.
Its Badger volume retained the complete trace across a container restart.
These checks used disposable SQLite data and made no model API requests.
Jaeger accepted another 12-span turn with the memory limiter and 300 MiB Go memory target enabled.
The local Theos and Jaeger Compose services started with separate persistent data volumes.
Theos readiness returned HTTP 200. Jaeger displayed the scripted 12-span example waterfall.
The local browser instance uses the configured OpenRouter model with Telegram polling disabled.

The bounded content update adds three checks for named delegates, task capture, message and tool links, byte limits, Unicode, cycles, and structured credential masking.
The full suite passed 747 tests, with three live tests excluded. Ruff checks, formatting, package builds, and the local Docker build passed.
A real OpenRouter `gpt-6-luna` turn compared three-day Open-Meteo forecasts for Pune, Mumbai, and Bengaluru.
The parent called `get_weather` for Pune. Two named agents fetched Mumbai and Bengaluru forecasts concurrently and returned separate summaries.
Jaeger displayed the 14-span waterfall in 28 seconds, with seven model calls and three successful weather tool calls.
Its GenAI panel rendered the delegate task and answer. All captured fields stayed within their byte limits without truncation.
The exported child spans retained their agent names. Legacy task strings and content-disabled tracing remain covered by tests.
This local result does not complete the pending Telegram, image, reasoning-control, or Pi workload checks.

A realistic travel query asked for weather, relaxed itineraries, rainy-day alternatives, and a Mumbai versus Bengaluru recommendation.
The query did not mention tools, delegation, or agent names.
Theos chose two concurrent agents named `Mumbai itinerary` and `Bengaluru itinerary` from the task scope.
Initial runs exposed the research timeout, a context-limit failure after extra searches, and an answer cut short by its output limit.
Runtime instructions now guide focused delegation, task-based names, concise research, limited verification, and explicit uncertainty.
These search limits are model guidance. The enforced shared call budget and 90-second tool timeout remain unchanged.
The final test conversation used a 4,096-token output limit. This does not change deployment defaults.
That run completed in 64 seconds with 19 spans, nine model calls, two weather calls, four search calls, and two successful delegates.
The final answer covered both itineraries and a recommendation, with a normal `stop` finish reason.
Jaeger displayed the named branches. All content stayed within capture limits, with eight spans marked for truncation.
The final answer was captured in full. The 33 tracing and integration checks, Ruff checks, and local Docker build passed.

The earlier recovery implementation reserved one model call and up to 15 seconds within the turn deadline for a final answer.
The recovery request uses unchanged instructions and no tools. Failed recovery returns bounded saved findings with explicit uncertainty.
Sixteen deterministic checks cover turn and delegate timeouts, shared and delegate budgets, context sizing, recovery failures, output truncation, and explicit cancellation.
They also check full durable results, bounded model-visible copies, completed sibling findings, conversation continuation, and uncertain writes without repetition.
Tracing checks confirm the `partial` root status and the final model beneath a `finalize answer` span.
Terminal checks verify visible partial replies. Schedule checks verify that incomplete runs pause their schedule.
The full suite passed 764 tests, with three live tests excluded. Ruff checks, package builds, and the local Docker build passed.
The unchanged realistic travel query completed again with both named delegates, ten model calls, and 25 spans over 109 seconds.
It returned both itineraries and a recommendation with a normal `stop` finish reason.
The isolated demo retained its existing 4,096-token output limit. Deployment defaults remain unchanged.
Jaeger displayed the overlapping delegate branches and their inherited agent names.
A separate deterministic budget-limit fixture exported five spans, including a tool-free final request beneath the recovery span.
Its root recorded `partial` status and its answer preserved the known finding.

The 2026-10-11 budget update separates compaction from research within the configured total ceiling.
Defaults allocate nine research calls, two compaction calls, and one recovery call within twelve total calls.
The delegate cap is configurable and defaults to four calls. Delegates retain the existing 85-second deadline.
Title generation consumes a research slot. Each completed compaction request records its own usage row.
Root spans expose limits and consumed calls for research, compaction, recovery, and the total.
Twenty-two additional checks cover allocation, small ceilings, environment settings, concurrent spending, and configurable delegate caps.
They also cover successful compaction, failed compaction without memory changes, recovery, title limits, and budget trace attributes.
The full suite passed 786 tests, with three live tests excluded.
All existing parent, delegate, compaction, title, and recovery instruction strings remain unchanged.
The same realistic travel query completed in 106 seconds with 19 spans and seven model calls.
The parent used three calls. The Mumbai itinerary and Bengaluru itinerary delegates each used two calls.
The run used two weather calls and six search calls. Both delegates completed, and the final answer ended normally.
The root recorded seven research calls, zero compaction calls, and zero recovery calls under the twelve-call ceiling.
This run did not require compaction. Forced-context checks exercised separate compaction allowances and their exhaustion path.
Jaeger displayed both named delegate branches. The demo retained its existing 4,096-token output limit.

The full suite passed 744 tests, with three live tests excluded.
Application lint, formatting, lock validation, Compose configuration, and package builds passed.
Real model and deployed transport acceptance remain separate checks.

The 2026-10-10 CI usage update selects container coverage by destination and build-file changes.
All 49 policy checks passed on Python 3.12 and 3.13.
They cover PR merge bases, multi-commit pushes, deleted and renamed build files, missing history, and failed or skipped checks.
The full Python 3.12 suite passed 767 tests, with three live tests excluded.
Workflow validation, application lint, formatting, and package builds passed.
Tagged releases retain application checks and test the exact ARM64 image before publication.
These local checks do not prove a tagged deployment through the updated workflow.

The 2026-10-10 OpenRouter retention update enforces `provider.zdr=true` in the application adapter.
Standalone requests passed automatic ZDR routing for all seven configured chat models.
Of 81 explicit provider routes, 76 returned HTTP 200 and five returned HTTP 429.
A forced non-ZDR OpenAI route returned HTTP 404 because it did not match the retention policy.
The [ZDR verification record](openrouter-zdr.md) lists providers, failures, request settings, and limits.

Five new deterministic checks cover streamed and buffered SDK payloads, preserved request options, disabled-ZDR overrides, and unavailable routes.
The full suite passed 718 tests after synchronization with `dev`, with three live tests excluded.
Application lint and formatting checks passed.
These text probes do not complete the remaining tool, image, reasoning, or transport acceptance checks.

The Telegram reply formatter converts Markdown into explicit message entities with UTF-16 offsets.
Regression tests cover emphasis, links, literal HTML, code blocks, tables, emoji, message splitting, and incomplete streamed markup.
They also check complete Unicode approval previews and removal of obsolete reply chunks.
Shared output checks cover browser, Telegram, and terminal streams, saved replies, reasoning summaries, and generated titles.
These checks use fake models and mocked Telegram calls. Live formatting acceptance remains pending.

The 2026-10-10 browser enrollment update completes Telegram-confirmed UI access without an encryption decision.
Completed users receive a single-use link when `AGENT_WEB_URL` is configured.
Tests cover browser binding, Telegram ownership, ordinary roles, expiry, denial, replay, revocation, credential rotation, and restart persistence.
They also check owner-scoped usage, private connections, connected terminal access, and preservation of the configured administrator account.
The full suite passed 676 tests, with three live tests excluded.
Ruff lint, Python formatting, JavaScript syntax, package builds, and changed documentation links passed.
The built wheel includes migrations 008 and 009 and the browser access modules.
Disposable browser previews confirmed code display, reload recovery, token presentation, chat, personal usage, and sign-out.
The confirmation and token screens fit at 320 pixels without horizontal overflow.
These checks use fake models and mocked Telegram calls. Live Telegram delivery and public HTTPS routing remain unverified.
Encryption onboarding and encrypted personal storage remain deferred.

The 2026-10-10 onboarding update asks for a preferred name before timezone setup.
Tests cover invalid names, Unicode, skip behavior, owner isolation, model context, resets, and restarts.
Migration 008 preserves completed profiles, pending timezone setup, and access-code authorization.
The full suite passed 662 tests, with three live tests excluded.
Application Ruff lint and formatting checks for the changed Python files passed.
These checks use fake models and mocked Telegram calls. Live Telegram delivery remains pending.
Telegram-confirmed browser access is implemented. Encrypted personal storage remains deferred.

The 2026-10-10 Git and release setup passed 655 deterministic tests with three live tests excluded on both Python 3.12 and 3.13.
GitHub CI passed browser syntax, workflow and shell validation, secret scanning, package and lightweight client checks, Compose validation, and native amd64 and arm64 container acceptance.
The Raspberry Pi runner is installed on 64-bit Debian 13.
The 2026-10-10 Telegram recovery replaced an unauthorized bot token and recreated the deployed container.
Live `getMe` and `getWebhookInfo` checks passed for `@mytheos_bot`, with no active webhook.
The local release changes add Telegram checks before worker replacement and after activation.
Focused tests cover safe errors, disabled bots, webhook conflicts, preservation before shutdown, and rollback after activation.
All 693 deterministic tests passed, with three live tests excluded. Application lint, formatting, and patch whitespace checks passed.
The new checker also passed live execution in a disposable Compose container and inside the active Pi container.
These changes require a new tagged release. End-to-end Telegram reply delivery remains unverified.
A disposable Docker rehearsal passed initial installation, replacement, deliberate readiness failure, and automatic rollback.
The original and restored SQLite records survived.
Release `rpi-v0.1.0` is healthy on the Pi with the configured model provider, browser user and administrator `owner`, and HTTPS Google callback URLs.
Readiness and browser-token authentication passed. No live model turn or Google account consent was performed.
The private GHCR image denies anonymous pulls.
The first registry upload failed with `unknown blob`; publication succeeded on retry before the deployment changed.
The existing Cloudflare service cannot start without `/etc/cloudflared/token`, so public OAuth routing is not verified.
These deployment checks do not establish real workload capacity or complete the remaining live-service checks.


The 2026-10-07 usage update adds separate personal and administrator views.
`test_dashboard_activity.py` checks owner-scoped charts, token-only authentication, cross-transport administrator totals, and content exclusion.
Administrator responses omit conversation titles and message history.
These checks do not establish encryption or privacy from direct database access.
Public-key onboarding and encrypted personal storage remain open requirements.
The related browser, interface, and connected-terminal checks passed: 36 tests.
Ruff lint and JavaScript syntax checks passed.
Browser previews confirmed personal scope and separate administrator totals with disposable records.

The service refactor retains the existing harness and application acceptance scenarios.
Tests use mocked models and external services unless the `live` marker selects a credential-dependent test.
Container checks use the fake provider and disposable data volumes.
Verification on 2026-10-04:

| Check | Result |
| --- | --- |
| Full test suite after sandbox server-proxy support | 533 passed, 3 live tests excluded |
| Sandbox direct and server-proxy connections | Creation and restart reconnection settings passed with mocked SDK lifecycle calls. Live Tailscale execution remains pending |
| Telegram onboarding, access code, and enrollment limit | 16 deterministic checks passed, including inbox redaction, code rotation, OAuth access, concurrent starts, restarts, and existing-user migration |
| Application suite after the final SQL formatting pass | 50 passed |
| Ruff lint and format | Passed |
| Browser JavaScript syntax | Passed |
| Wheel and source package builds | Passed |
| Wheel imports, assets, and SQLite migrations outside the source directory | Passed |
| Production and development Compose configuration | Passed |
| Local documentation links | Passed |
| Existing harness source and browser asset comparison | Unchanged |
| Linux arm64 container | Chat, assets, restart, non-root user, and graceful shutdown passed |
| Linux amd64 container under emulation | Chat, assets, restart, non-root user, and graceful shutdown passed |

The 2026-10-05 automation update adds 19 deterministic checks in `test_automation.py`.
These cover scheduled tasks, memory retrieval, and consented consolidation.
They include concurrent shutdown, revoked enrollment, and separate owner batches.
Zepto coverage checks encrypted owner-scoped token recovery, callback state binding, Telegram inbox redaction, chat-history isolation, schema validation, and order approval.
The full suite passed 556 tests, with three live tests excluded.
Ruff lint, formatting, and local documentation links passed.
Live scheduled delivery, Mem0 extraction, and Zepto sign-in remain pending.

The 2026-10-06 terminal integration adds 14 deterministic checks in `test_terminal.py`.
The full suite passed 570 tests, with three live tests excluded.
Ruff lint, formatting, browser JavaScript syntax, and package builds passed.
The installed wheel opened the UI and completed a fake-provider turn outside the source directory.
The editable installation exposes `theos` through the normal shell path.
The installed command completed a fake-provider turn in a real terminal and exited through `/quit`.
Background notice checks cover the timer after startup.
The terminal guide passed the prose check with 0.55 findings per 100 words.
Terminal checks use isolated local state and mocked or fake providers.
Live terminal model requests remain pending.

The 2026-10-06 browser update adds 20 deterministic checks for cost scopes, missing prices, tool access, reasoning summaries, model controls, voice APIs, OpenRouter streams, and automatic titles.
The full suite passed 590 tests, with three live tests excluded.
Ruff lint, formatting, browser JavaScript syntax, Prettier checks, and package builds passed.
Local browser checks used isolated SQLite data and a fake provider.
Desktop and mobile checks covered cost tables, tool search, input schemas, collapsible thinking and tool results, generation settings, slash command help and suggestions, model changes, and active thinking animations.
An isolated voice fixture verified TTS controls. A title fixture verified a generated title and its cost in the browser.
Live provider reasoning and titles, microphone capture, transcription inference, and audible TTS remain unverified.

The voice control refinement replaces text buttons and the native audio widget with microphone, speaker, loading, and stop icons.
Browser checks verified play/stop, cached replay, one active reply, and desktop and mobile layouts.
A synthetic microphone stream verified recording, stop, editable transcription, and cancellation without capturing ambient audio.
The mini-theos thinking orb appears before reasoning text and stops when the reply completes.
The 15 browser and transport API tests, JavaScript syntax, Prettier checks, and package build passed.

The browser UX audit aligned messages and the composer at a shared left gutter, including with the sidebar collapsed.
The audit grouped composer icons, enlarged mobile touch targets, and aligned tools and dashboard headings with their navigation controls.
Browser checks covered desktop, 390px, and 320px layouts, recording glow cleanup, growing drafts, slash suggestions, generation settings, and mobile drawer dismissal.
The reading-position check retained the earlier message position after a streamed reply.
Light mode switches the login, header, and empty conversation to the mini-theos Daylight logo.
The 15 browser and transport API tests, JavaScript syntax, Prettier checks, and package build passed after these changes.

The message statistics update adds live output-token estimates, elapsed generation time, and local timestamps.
Final replies use provider token counts. Missing usage retains the estimate.
Three new deterministic checks cover separate generation durations, checkpoint and restart persistence, owner isolation, and legacy history without timestamps.
The browser API check confirms that streamed usage and display values match saved history.
The full suite passed 593 tests, with three live tests excluded.
Application Ruff checks, formatting, JavaScript syntax, Prettier checks, and the package build passed.
Browser checks verified the live estimate, final count, stopped timer, reload persistence, and legacy messages.
Desktop and 320px checks verified footer alignment, speaker controls, and dark and light themes without horizontal overflow.
These browser checks used an isolated database and a fake provider.

The rich chat update renders streamed and saved Markdown in thinking and replies, with code copy controls and sanitized links.
The composer starts at one line, grows to 140px, and uses an accent recording glow that follows microphone RMS volume.
Dropdown arrows have a 14px right margin.
Dashboard charts show model requests, recorded cost, tokens by model, and tool starts over 7, 30, or 90 UTC days.

Four new deterministic checks cover complete aggregates beyond 100 rows, UTC boundaries, inactive dates, unknown prices, administrator access, and locally served Markdown dependencies.
The full suite passed 597 tests, with three live tests excluded.
Application Ruff checks, formatting, JavaScript syntax, Prettier checks, and the package build passed.
The wheel contains the renderer, charts, pinned vendor scripts, and their licenses.

Browser checks covered streaming, saved Markdown, code copying, literal HTML, unsafe links, TTS text without toolbar labels, and internal table/code scrolling.
A synthetic microphone stream verified volume response, transcription, cancellation, and analyzer cleanup without ambient audio capture.
Desktop and 320px checks verified compact drafts, slash suggestions, inset arrows, chart ranges, chart details, data tables, and dark/light layouts without horizontal overflow.
These checks used an isolated database and fake services. Live microphone and speech-service checks remain pending.

The 2026-10-06 browser connections update adds 15 deterministic checks.
They cover Google consent, encrypted credential recovery, callback replay, cancellation, expiry, revoked access, and reserved identity namespaces.
They also cover Zepto return handoffs, setup failures, owner isolation, Health job cancellation, and sandbox approval isolation.
The full suite passed 612 tests, with three live tests excluded.
Application Ruff checks, formatting, JavaScript syntax, Prettier checks, package builds, and the local Docker build passed.
The running local container serves the new Connections view and owner-bound account routes.
Its authenticated tool registry includes configured Google account and sandbox tools.
Desktop and 320px browser checks used isolated accounts and fake providers.
They verified sign-in links, Google setup cancellation, Zepto return completion, service labels, themes, and mobile navigation without horizontal overflow.

Read-only checks from the container reached the sandbox health route and both voice model-list routes.
The memory client returned an empty result for a synthetic owner.
Zepto OAuth discovery returned an authorization server.
These checks do not prove sandbox execution, speech inference, account consent, or remote account actions.
Gmail and Google Health live account checks still require user consent.
Zepto browser sign-in and order-history access succeeded.
An approved product search returned a missing-store prerequisite.
The session update adds SDK-backed checks for store retention, owner isolation, cancellation, shutdown, and failures without replay.
The combined error and session update adds seven checks. The full suite passed 619 tests, with three live tests excluded.
Ruff, formatting, the Docker build, and container readiness passed.
Live MCP discovery reused the account session across two requests.
The previous approved search still required delivery-store selection and returned the new setup guidance.
Running Gmail and Health sign-in links use the registered local HTTP callbacks on port 8080.
Live address selection and successful product search remain pending.

The browser approval fix clears accepted decisions before the resumed turn finishes.
API checks cover both decisions, the initial pending-approval snapshot, and rejection of repeated submissions.
Isolated browser checks covered slow Zepto execution, generic tool denial, a broken stream, and a rejected submission.
Accepted decisions removed the card and replaced the waiting label without duplicate tool rows.
Rejected submissions retained enabled decision controls. The full suite passed 620 tests, with three live tests excluded.
Python style, JavaScript syntax, and Prettier checks passed.

The provider icon and mention update passed 31 browser API and transport checks.
Isolated browser checks covered keyboard and pointer insertion, mid-draft completion, multiple mentions, email addresses, Escape, and slash commands.
Submitted mentions remained in user history. Account status came from the authenticated Connections API.
Provider icons loaded locally. Desktop and 320px checks covered light and dark themes without horizontal overflow.
Package and Docker builds passed. The wheel includes all three provider icons with the recorded hashes.
The healthy local container serves the updated controls, styles, and provider assets.
The service icon update replaces letter placeholders with native SVG symbols for all eight workspace services.
Isolated browser checks found icons for all 11 Connections entries and all 11 mention suggestions.
Desktop and 320px checks verified light and dark visibility, including speech and transcription, without horizontal overflow.
JavaScript syntax and Prettier checks passed.

The browser settings and command update passed 35 browser API checks.
Isolated browser checks verified combined settings saves, canceled drafts, save failures, supported reasoning choices, and output limits after model changes.
They covered command option menus, the hidden `/thinking` alias, interactive help, usage cards, and sidebar navigation.
Commands did not add messages to conversation history. Unpriced requests remained visible in usage cards.
Light and dark layouts passed at 320px, 390px, 768px, and 1440px without horizontal overflow.
JavaScript syntax and Prettier checks passed. These checks used a fake model and disposable SQLite data.
The rebuilt local container passed readiness checks and serves browser assets that match the updated source.

The connected terminal update adds 15 deterministic checks in `test_terminal_remote.py`.
The full suite passed 635 tests, with three live tests excluded.
They cover shared browser history, owner isolation, authenticated routes, atomic approval decisions, images, settings, usage, delegate progress, concurrent turns, and disconnection without replay.
Native terminal checks cover saved approvals, keyboard option selection, canceled settings, rejected saves, and continuation commands.
The combined local, remote, and renderer terminal suite passed 48 tests.
The client-only wheel launched outside the source directory and completed a turn through a disposable HTTP server with a fake provider.
That environment contained no FastAPI, OpenAI, or cryptography package.
Settings and usage dialogs passed visual inspection at 100 by 40 terminal cells.
A real HTTP check closed the event stream and confirmed that the server completed and saved the reply.
The rebuilt local deployment passed readiness and authenticated terminal route checks.
The terminal and browser session endpoints returned the same owned conversation IDs.
Ruff lint, formatting, lock validation, and package builds passed.
These checks did not make live model requests or deploy to a VPS.

The terminal status update replaces diamond markers and adds a grouped, bordered status panel.
The Theos terminal suite passed 51 checks. The reusable renderer suite in `agents-intro` passed 28 checks.
Status checks cover 40, 80, and 110 columns, literal values, cached tokens, waiting and failed states, reloads, and session changes.
The panel passed visual inspection at 100 by 40 terminal cells.
The modified files add no Ruff findings. Existing renderer style findings remain.

The containers run Python 3.13 as UID `10001` with a read-only root filesystem.
The host uses Docker Desktop on Apple Silicon.
The amd64 result uses emulation, not a native amd64 host.
The mock browser and Telegram workflows pass through the application acceptance suite.
Live Telegram and other credential-dependent checks remain in the table below.

| Architecture | Memory snapshot after a short turn | CPU snapshot |
| --- | --- | --- |
| arm64 | 62.06MiB / 768MiB | 68.96% |
| amd64, emulated | 86.34MiB / 768MiB | 0.99% |

These single samples can include startup work.
They are not idle measurements, peak-load measurements, or Raspberry Pi benchmarks.
The limits remain one CPU and 768 MiB per container.

The new service map and Telegram sequence use the Excalidraw MCP.
Their editable sources, elements, and PNG previews remain together under `docs/architecture`.
The guides embed PNG previews and link to editable sources.

The 2026-10-11 sandbox startup fix explicitly starts the interpreter for new sandboxes.
The full suite passed 854 tests, with three live tests excluded.
Ruff lint, formatting, and package builds passed.
A patched application client ran from the Pi against the Mac mini.
It passed Python execution, file retrieval, reconnection, and destruction in 10.57 seconds.
The earlier range execution timeout remains unresolved.
These checks did not cover Telegram delivery or browser automation.

## Repeat the deterministic checks

1. Install the locked dependencies.

   ```bash
   uv sync --locked --extra server --extra terminal
   ```

2. Run the tests.

   ```bash
   uv run --no-sync pytest -q
   ```

3. Check Python style.

   ```bash
   uv run --no-sync ruff check src/theos tests/app
   uv run --no-sync ruff format --check src/theos tests/app
   ```

4. Check JavaScript syntax.

   ```bash
   node --check src/theos/transports/browser/static/app.js
   ```

5. Build the package.

   ```bash
   uv build
   ```

The CI workflow also installs the wheel outside the source directory.
It checks Compose, containers, restart recovery, and resource use.

## Live service checks

These checks need operator credentials and service access.
They remain pending until someone records a real service result.
Mocks do not count as live results.

| Service | Required live check | Status |
| --- | --- | --- |
| Gemini and OpenRouter | Stream text, call a tool, inspect an image, change reasoning | Pending |
| Telegram | Poll a real bot, send an album and voice note, approve an action, receive a reminder and file | Pending |
| Terminal | Stream a real model turn, inspect tool progress, attach an image, and answer an approval through `theos` | Pending |
| External memory | Save, search, edit, delete, and reject another user's memory | Pending |
| Automatic memory | Approve consolidation, submit personal facts, confirm retrieval and correction, then disable consolidation | Pending |
| Scheduled agent tasks | Receive a timed Telegram result, approve a protected action, and inspect a recurring run after restart | Pending |
| Exa, Brave, Open-Meteo | Search, exercise fallback, request a forecast | Pending |
| OpenSandbox | Create, reconnect, execute code, automate a browser, deliver a file, destroy | Patched application client creation, Python execution, file retrieval, reconnection, and destruction passed from the Pi on 2026-10-11. Range execution, browser automation, and transport delivery remain pending |
| R2 | Archive, restore, and delete a disposable object | Pending |
| Transcription and Kokoro | Transcribe audio and play generated speech | Pending. Operator confirmed Whisper Small cache discovery on the Mac mini on 2026-10-04. Inference and playback remain unconfirmed |
| Gmail | Connect, read a thread, download an attachment, draft, approve, and send to a test recipient | Pending |
| Google Health | Connect, import all available data types, export/edit/delete a meal, recover an interrupted export | Pending |
| Zepto | Connect through browser or private Telegram OAuth, inspect account access, reject an order, inspect a payment confirmation | Browser sign-in and order-history access confirmed on 2026-10-06. Live search returned `Store not selected`. Delivery-store setup, successful search, and order/payment approval checks remain pending |
| Raspberry Pi | Run the arm64 image on the target device and measure real workload limits | Deployment and rollback verified on 2026-10-10. Real workload limits remain pending |

Use disposable records and an operator-approved recipient for Gmail send tests.
A real Zepto order or payment needs separate authorization for its exact contents and price.
The application never completes a live purchase as part of its test suite.

## Deployment boundaries

Mem0, Qdrant, embeddings, OpenSandbox, and voice servers remain separate projects.
The application connects to their configured endpoints.
Zepto requires an operator-configured MCP endpoint and a valid encryption key.
Each user authorizes their own account through browser Connections or private Telegram.
The application stores OAuth credentials encrypted in SQLite.

Gmail performs a final content check before sending a draft.
Its API cannot prevent another client from changing the draft after that check.
The send result can remain unknown after a connection failure.
The application records that uncertainty and does not repeat the send automatically.

Google Health exports use named records and operation IDs for reconciliation.
Live acceptance must check those contracts against the account's enabled API version.
A disconnected account keeps local records but stops pending background work.

No production server or external account was configured during local acceptance.

## Research context and response limits

Parents and delegates now share provider capacities and compaction at 60 percent of the model window.
Agent response limits use only the supported provider output parameter. Application code does not clip generated answers.
Each researcher reserves one final handoff before research starts. The parent retains a separate final response call.
Final responses retain task requirements, corrections, complete findings, and sources. They do not run tools or retry.
Active generation can finish after the research deadline. Explicit cancellation and provider connection idle timeouts remain.
Telegram, browser chat, and terminals replace interrupted drafts. Stored history retains the original drafts for diagnosis.
Connected terminals use protocol version 2 and require matching client and deployment updates.

Deterministic checks cover provider capacity refresh, native output parameters, reserved sibling handoffs, and complete context.
Output-space checks reserve the requested generation allowance before summarizing input.
They cover parent answers, researcher answers, final responses, and all supported output parameter names.
Summary chunks retain the full output allowance. Requests that cannot fit preserve complete saved findings without lowering that allowance.
They also cover answers above the earlier byte limit, full evidence chunks, long summaries, and generation beyond research deadlines.
Transport checks cover browser replacement, Telegram chunk replacement, terminal replacement, and reopened conversation history.
This change has not deployed or run a live provider research query.

The initial local suite passed 875 checks, with three credential-dependent live checks excluded.
Ruff checks, formatting, lock validation, source and wheel builds, browser JavaScript syntax, and the client-only wheel check passed.

The output-space follow-up passed 887 tests, with three credential-dependent live checks excluded.
It adds twelve checks for complete output reservations, small explicit settings, and preserved findings when requests cannot fit.
Ruff checks, formatting, and source and wheel builds passed for this follow-up.
