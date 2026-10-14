# Implemented tool catalog

Context summaries use the pinned Markdown template without JSON generation.
The harness supplies bounded exact references from the original transcript and owned research records.
The full reference index stays in saved memory. Existing `history_read`, `history_search`, and research tools recover omitted details.
This extension adds no tool or runtime dependency.

Tool responses can contain more than 16 calls. The harness processes valid calls in ordered batches of at most 16.
It preserves call IDs, approval checks, and completed results. Only tools declared safe may overlap.
The model receives batching guidance and explicit feedback after oversized groups.
Invalid arguments and unknown tools receive `not_started` results before execution, with correction instructions.
Executed failures retain `failed`. Uncertain actions retain `unknown` and cannot repeat automatically.
Trace metadata retains the complete generated call count even when content capture includes only the first 16 calls.

The runtime binds tools to the authenticated owner and conversation.
A model cannot supply another owner ID through tool arguments.
Optional account tools appear only after configuration and transport checks.
Read the [service setup guide](services.md) for endpoints and credentials.
The [configuration reference](base-infra/environment-variables.md) lists every environment setting.
Use the [documentation map](documentation-map.md) to find each service guide.

![Framework tool design](architecture/theos-tools.png)

This diagram shows how tool groups fit into the framework.
It preserves earlier design names and planned delivery phases.
The tables below describe the current implementation.
Read the [runtime diagram](architecture.md#current-implementation) for service ownership.

## CI coverage selection

`scripts/ci_policy.py` uses Git and the Python standard library to select container architectures.
It reads the GitHub event file and writes the matrix to `GITHUB_OUTPUT`.
Dev runs check build and deployment changes. Main runs check five architectures. Pi runs check ARM64.
Manual extended runs add IBM Z and RISC-V.
Missing Git comparison history retains ARM64 checks. The tagged release tests its image in a separate job.
This script adds no package dependency or model tool.

Source: [CI policy](../scripts/ci_policy.py) and [workflow](../.github/workflows/theos.yml).

## Telegram reply formatting

Telegram reply formatting uses `markdown-it-py` 4.x from the `server` extra.
The renderer converts Markdown into text and explicit Telegram message entities.
It uses UTF-16 offsets and splits long replies while retaining formatting.
Raw HTML remains literal text. Only HTTP, HTTPS, mail, and Telegram links become link entities.
Commands remain literal text. Approval reviews use labeled fields, formatted prose, and literal code.
Telegram uses one editable status per tool call and per compaction, with readable action names and tool icons.
Finished activities disappear. A final message shows elapsed time, call count, failed or uncertain outcomes, and successfully loaded skills.
The runtime counts parent and delegate activity before display queues can discard events.
Approval cards notify once and stay visible until a decision or expiry. Saved message references survive restarts.
Telegram decisions remove complete reviews immediately. Polling also removes reviews resolved elsewhere and retries failed cleanup every ten seconds.
If deletion fails, cleanup removes approval buttons while retaining references for another attempt.
SQLite retains approval snapshots, decisions, tool results, and conversation history.
Expandable quotes retain exact identifiers and raw price units. Long reviews retain complete details in splits or a file.
Zepto cart reviews show paise prices in rupees, while approval snapshots retain the original values.
This renderer adds no model tool.

Source: [Telegram formatter](../src/theos/transports/telegram/formatting.py).

## Telegram release check

`python -m theos.operations.telegram_check` uses HTTPX and the Python standard library.
The optional `--env-file` argument uses python-dotenv, already installed through Pydantic Settings.
The check calls Telegram's read-only `getMe` and `getWebhookInfo` methods with ten-second request timeouts.
It checks bot authentication and rejects active webhooks that prevent polling.
It sends no messages, reads no updates, and prints no credentials or remote error bodies.
The Pi release runs the check before stopping the worker and after activating the candidate.
An empty bot token disables the check. This operation adds no model tool or package dependency.

Source: [connection check](../src/theos/operations/telegram_check.py) and [release activation](../scripts/deploy_rpi.py).

## Terminal transport

The installed `theos` command uses the owned renderer, Rich, and Textual.
The `terminal` extra installs standalone application dependencies.
The smaller `client` extra installs HTTPX, Pydantic Settings, Rich, and Textual for deployed workspace access.
Connected mode reads only the server URL and token. Model SDKs and account credential encryption stay on the server.
Connected mode authenticates with the browser token and uses the deployment's shared conversations, tools, settings, usage, and approvals.
HTTP Server-Sent Events carry display events with nested delegate scope. They omit provider state and harness run results.
The client uses native Textual settings and usage dialogs and supported model and reasoning option menus.
It starts no local runtime, SQLite connection, scheduler, or Telegram poller.
Disconnects leave server work running. Requests and approval decisions have no automatic retry.
Standalone mode saves transcripts and metadata under a local `terminal:` owner.
That mode uses the existing file catalog, runtime tools, approval policy, and scheduler.
It adds no model tools.
Read the [terminal guide](terminal.md) for installation and controls.

Source: [terminal adapter](../src/theos/transports/terminal/session.py), [remote client](../src/theos/transports/terminal/remote.py), [authenticated routes](../src/theos/transports/terminal/routes.py), and [command lifecycle](../src/theos/transports/terminal/cli.py).

## Browser tools view

The browser uses FastAPI and native HTML details controls.
It reads the current conversation's runtime registry without executing tools.
The view shows tool descriptions, input schemas, and approval requirements.
Chat shows collapsible tool calls and model reasoning summaries when available.
SQLite usage records supply owner totals and administrator cost breakdowns.
`/api/activity` uses the browser token to scope charts and totals to one owner.
`/api/dashboard` requires administrator access and includes all users and transports.
Administrator usage responses exclude conversation titles and message history.
Message footers use provider output-token usage, streaming estimates, and elapsed generation time.
The application saves UTC timestamps and durations in history JSON through `storage/messages.py`.
Native browser timers and Intl formatters supply live updates and local timestamps.

Markdown uses locally served [Marked](https://marked.js.org/) 18.1.0 and [DOMPurify](https://github.com/cure53/DOMPurify) 3.4.16.
The [vendor manifest](browser-vendor-provenance.json) records pinned package sources, file hashes, and included license files.
The renderer treats raw HTML as text and removes unsafe links from generated markup.

Native SVG, ResizeObserver, and HTML data tables supply responsive dashboard charts.
`transports/browser/activity.py` aggregates usage and tool-start records for bounded UTC periods.
Personal queries use the authenticated owner. Administrator queries cover the workspace.

Web Audio MediaStreamAudioSourceNode and AnalyserNode measure microphone RMS volume for the accent recording glow.
Reduced motion and unsupported audio analyzers retain a static glow.
These UI features add no Python dependency or model tool.

Browser commands use the existing authenticated conversation APIs.
Native HTML dialogs supply Settings, command help, and usage cards. Native SVG supplies the settings and sidebar icons.
These controls add no runtime dependency. Settings saves model, reasoning, generation, and voice choices together.
Generation controls use Pydantic validation and SQLite migration 006.
Automatic titles use bounded, tool-free requests to the selected model and SQLite migration 007.
Their token usage is included in the conversation cost.
OpenRouter aliases and parameter support live in [the model catalog](../src/theos/runtime/model_catalog.py).
Microphone input uses browser MediaRecorder and the existing transcription client.
Speech playback uses the existing Kokoro client and authenticated file catalog.
The [OpenRouter adapter](../src/theos/runtime/openrouter.py) retains streamed reasoning, signed reasoning blocks, and provider-reported costs.
It enforces `provider.zdr=true` for every OpenRouter request, including delegated research, compaction, and titles.
This uses the existing OpenAI SDK and adds no dependency or model tool.

Source: [browser API](../src/theos/transports/browser/app.py) and [browser controls](../src/theos/transports/browser/static/app.js).

## Browser connections

Native HTML controls and authenticated FastAPI routes expose account consent, setup status, cancellation, and disconnection.
Google uses the existing HTTPX OAuth client, PKCE, and encrypted SQLite credentials.
Zepto uses the existing MCP OAuth client and owner-bound return handoff.
The view also reports optional service configuration without secrets.
Composer `@` suggestions use these same owner-bound connection statuses.
Mentions remain user text and do not grant tool access or approve actions.
Provider icons are local assets. The [provider manifest](browser-provider-provenance.json) records their sources and hashes.
These controls add no Python dependency or model tool.
Configured sandbox tools work in browser conversations without execution approval prompts.

Source: [connection routes](../src/theos/transports/browser/connections.py), [account access](../src/theos/storage/account_access.py), and [browser controls](../src/theos/transports/browser/static/app.js).

## Preferences

SQLite. The timezone uses the Python zoneinfo database.
Telegram `/start` asks for a preferred name and timezone before normal chat.
The saved display name enters owner-scoped model context on each turn.
`/skip` accepts the saved or Telegram name, then the saved default timezone in the next step.
The transport uses SQLite enrollment records to enforce a maximum of 50 Telegram users.
An optional `AGENT_TELEGRAM_ACCESS_CODE` protects registration and later access through SQL authorization records.
The transport uses Python hashlib and hmac to verify codes and store fingerprints.
Completed users can connect private accounts without a manual sender allowlist.
This setup uses no model tool or additional service dependency.

Source: [service tools](../src/theos/services/preferences/tools.py).
See [Telegram onboarding](telegram-setup.md#user-onboarding-and-limit) for the transport flow.

Telegram-confirmed browser access uses existing FastAPI, HTTPX, SQLite, hashlib, and secrets dependencies.
`AGENT_WEB_URL` supplies the validated deployment origin.
Private Telegram approval binds a single-use invitation to a browser cookie before credential issuance.
SQLite stores only credential hashes. Session cookies are HttpOnly and SameSite Strict, with Secure enabled on HTTPS.
Cookie mutations require a custom same-origin request header and reject foreign origins.
Personal access tokens retain the existing bearer-token login interface.
This flow adds no model tool and makes no encryption decision.

Source: [credential storage](../src/theos/storage/browser_access.py), [browser sign-in](../src/theos/transports/browser/auth.py), and [Telegram web access](../src/theos/transports/telegram/web_access.py).
The cookie controls follow [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

| Callable | Action |
| --- | --- |
| `set_preference` | Set your timezone, calorie goal, display name, or instruction override. |
| `get_preferences` | Read your preferences and instruction override. |

## Reminders

SQLite and croniter. The application scheduler delivers saved occurrences.

Source: [service tools](../src/theos/services/reminders/tools.py).

| Callable | Action |
| --- | --- |
| `schedule_reminder` | Schedule a reminder. Recurrence is a five-field cron expression in your timezone. |
| `list_reminders` | List your pending reminders and their delivery status. |
| `cancel_reminder` | Cancel one of your reminders. |

## Meals

SQLite and Pydantic. Connected Google Health accounts receive durable export jobs.

Source: [service tools](../src/theos/services/meals/tools.py).

| Callable | Action |
| --- | --- |
| `log_meal` | Save a meal with calories, nutrients, and the time you ate it. |
| `edit_meal` | Replace a saved meal and queue its nutrition export. |
| `delete_meal` | Delete a meal and queue deletion of its exported nutrition record. |
| `get_calorie_summary` | List meals and nutrient totals for a day in your timezone. |

## Training

SQLite and Pydantic. Program versions preserve the meaning of past workouts.

Source: [service tools](../src/theos/services/training/tools.py).

| Callable | Action |
| --- | --- |
| `set_training_program` | Save a rotating program with resistance, cardio, recovery, and rest days. |
| `get_todays_training` | Read today's prescription, deload state, and last comparable workout. |
| `advance_training_cycle` | Advance the training program by one day, including its week counter. |
| `log_training` | Save training results, per-set details, metrics, and completion status. |
| `get_training_history` | List comparable workouts by cycle day, session type, or exercise. |
| `delete_workout` | Delete one of your saved workouts. |
| `update_training_metrics` | Record a training metric with an explicit unit and measurement time. |
| `get_training_metrics` | List your training metrics and measurement history. |

## Custom Tables

A separate SQLite database per owner. Queries use bound parameters and an authorizer.

Source: [service tools](../src/theos/services/custom_tables/tools.py).

| Callable | Action |
| --- | --- |
| `create_custom_table` | Create a table in your private database. |
| `delete_custom_table` | Delete a table and its rows after confirmation. |
| `create_query_template` | Save one SELECT, INSERT, UPDATE, or DELETE statement with named parameters. |
| `execute_query_template` | Run a saved query with bound parameters in your private database. |
| `list_custom_tables_and_templates` | List your tables and saved query templates. |

## Memory

HTTPX and the configured Mem0 OSS REST endpoint. Mem0 Platform needs an adapter.
Returned records require matching owner metadata. The OSS API key does not bind `user_id` to its dashboard user.

Source: [service tools](../src/theos/services/memory/tools.py).

| Callable | Action |
| --- | --- |
| `save_memory` | Save information that the user explicitly wants to remember. |
| `search_memory` | Search your saved memories. |
| `get_all_memories` | List your saved memories. |
| `get_memory` | Read one of your saved memories. |
| `update_memory` | Replace one of your saved memories. |
| `delete_memory` | Delete one of your saved memories. |

## Search

HTTPX with Exa, then Brave when configured. At least one search key is required.

Source: [service tools](../src/theos/services/search/tools.py).

| Callable | Action |
| --- | --- |
| `web_search` | Search with Exa. Use Brave if Exa fails or is not configured. |

## Weather

HTTPX with the Open-Meteo geocoding and forecast APIs.

Source: [service tools](../src/theos/services/weather/tools.py).

| Callable | Action |
| --- | --- |
| `get_weather` | Get current weather and a daily forecast for a place. |

## Skills

An operator-controlled directory. Resource reads cannot escape the selected skill directory.

Source: [service tools](../src/theos/services/skills/tools.py).

| Callable | Action |
| --- | --- |
| `list_skills` | List the skill instructions installed by the operator. |
| `load_skill` | Read a skill or a resource inside its directory. |

The Pi uses `/home/neuron/.agents/skills` as its shared skill directory.
Theos mounts that same directory read-only at `/skills` with `AGENT_SKILLS_DIR=/skills`.
The operator sets `THEOS_SHARED_SKILLS_DIR=/home/neuron/.agents/skills` and installs `compose.skills.yaml` in the deployment directory.
The deployment script retains this mount during release and rollback.
Manual Compose commands must include the shared-skills file explicitly.
Host skill updates appear without a copy or application restart.
The runtime includes installed skill descriptions and requires purpose-based skill selection before work.
It supplies report-style and format instructions automatically for document requests, with explicit user formats taking precedence.
The [skills.sh CLI](https://skills.sh/docs) installed code review, Papers with Code, arXiv, Hugging Face papers, DOCX, XLSX, and PDF skills.
It runs through a temporary Node 22 runtime because the Pi's system Node 20 is incompatible with `skills@1.7.2`.
Source licenses, installation metadata, hashes, and local corrections remain with the installation.

The local [report style](../skills/report-style/SKILL.md) supplies the default appearance for new PDF and DOCX reports.
The [style updater](../scripts/apply_skill_styles.py) adds its policy to the upstream DOCX and PDF instructions.
The policy preserves explicit user styles and existing document formats during edits.
See [shared skill maintenance](../skills/README.md) for installation and updates.

| Report helper | Dependencies |
| --- | --- |
| `build_doc.py` | Python 3.10 or later, Markdown, Chrome or Chromium, network access for CSS fonts |
| `build_docx.py` | Python 3.10 or later, python-docx, Markdown, Beautiful Soup, Inter and DejaVu Sans Mono fonts |
| DOCX diagrams | Playwright and Chrome or Chromium |
| Visual verification | LibreOffice for DOCX conversion and Poppler for PDF page images |

The helper scripts declare their Python dependencies for `uv run`.
Copy their scripts and text assets into the remote sandbox before execution.
Skill installation does not install browser binaries, fonts, LibreOffice, or Poppler in that sandbox.

Paper research uses the official `pwc-cli` skill first, with arXiv and Hugging Face as supplemental sources.
The Pi has `pwc 0.4.3` in an isolated Python environment.
Live search and metadata retrieval passed against the public catalog.
The remote sandbox needs a separate CLI installation.

On 2026-10-11, the Pi's deployed loader listed eight skills and read every instruction file.
A temporary host-file change appeared through `load_skill` without a restart.
The container mount is read-only.
It also read the report scripts, stylesheet, JavaScript, and diagram references.
Local PDF and DOCX samples rendered successfully and passed page inspection.
Those samples do not verify remote document execution or transport delivery.

## Files

Private SQLite catalog and local files. R2 operations also use boto3 and configured bucket credentials.

Source: [service tools](../src/theos/services/files/tools.py).

| Callable | Action |
| --- | --- |
| `list_user_files` | List your uploaded and generated files. |
| `archive_user_file` | Archive a file in the configured R2 bucket. |
| `restore_user_file` | Restore one of your archived files. |
| `delete_user_file` | Delete your file from local storage and R2. |

## Voice

HTTPX with configured transcription and Kokoro endpoints. Generated audio enters the private file catalog.

The [speech hosting guide](speech-hosting.md) covers separate Docker and native deployments.
Docker uses Speaches with faster-whisper and Kokoro-FastAPI CPU images.
Native Apple Silicon uses MLX Whisper and Kokoro-FastAPI through PyTorch MPS, with uv, FFmpeg, and espeak-ng.
Hosted transcription uses a compatible multipart API with bearer authentication.
The speech client fixes the model to `kokoro` and sends no authentication header.
Generic hosted speech APIs require an adapter or client changes.

Source: [service tools](../src/theos/services/voice/tools.py).

| Callable | Action |
| --- | --- |
| `send_text_to_speech` | Generate speech with Kokoro and deliver it as a file. |
| `transcribe_file` | Transcribe an uploaded audio file. |

## Sandbox

OpenSandbox and its code interpreter SDK. Browser commands require agent-browser inside the remote image.

The Mac mini uses OpenSandbox server `1.1.1` with configuration and state on the external SSD.
It uses the `code-interpreter:v1.1.0` and `execd:v1.1.0` images from the `opensandbox` registry namespace.
The interpreter requires `/opt/code-interpreter/code-interpreter.sh` as its entrypoint.
Theos supplies this entrypoint when creating a sandbox. See [sandbox deployment](sandbox.md#operator-deployment).

Source: [service tools](../src/theos/services/sandbox/tools.py).

`AGENT_SANDBOX__USE_SERVER_PROXY=true` routes SDK execution and file requests through the OpenSandbox server.
This uses the existing SDK and lets remote clients connect without access to container ports.

| Callable | Action |
| --- | --- |
| `sandbox_run_command` | Run a shell command in your remote sandbox without an approval prompt. |
| `sandbox_execute_code` | Run Python in your remote sandbox's persistent interpreter. |
| `sandbox_write_file` | Write a text file in the remote sandbox. |
| `sandbox_read_file` | Read a text file from the remote sandbox. |
| `sandbox_list_files` | List files in a remote sandbox directory. |
| `sandbox_send_file_to_user` | Download a generated sandbox file and deliver it to the user. |
| `sandbox_view_image` | Read a sandbox image and attach it to the next model request. |
| `sandbox_upload_file` | Copy one of your uploaded files into the remote sandbox. |
| `sandbox_browser` | Run agent-browser in the sandbox. Use snapshot, open, click, fill, or screenshot commands. |
| `sandbox_lifecycle` | Inspect, restart, destroy, or forget a sandbox. Expiry remains fixed from creation. |

## Gmail

HTTPX, Google OAuth, and encrypted owner tokens. Tools require a browser or private Telegram conversation.

Source: [service tools](../src/theos/services/gmail/tools.py).

| Callable | Action |
| --- | --- |
| `gmail_connect` | Create a Google authorization link for your Gmail account. |
| `gmail_disconnect` | Disconnect your Gmail account and revoke its grant. |
| `gmail_search_messages` | Search Gmail messages outside Spam and Trash. |
| `gmail_get_message` | Read a Gmail message, including its MIME body and attachment IDs. |
| `gmail_get_thread` | Read a Gmail thread outside Spam and Trash. |
| `gmail_download_attachment` | Download an attachment from one of your accessible messages. |
| `gmail_list_drafts` | List your Gmail drafts. |
| `gmail_get_draft` | Read a draft with its recipients, subject, body, and content hash. |
| `gmail_create_draft` | Create a draft in your connected account. |
| `gmail_send_draft` | Send after explicit approval of the current draft. Recheck its contents immediately before sending. |
| `gmail_list_labels` | List Gmail labels. |
| `gmail_create_label` | Create a Gmail label. |
| `gmail_modify_labels` | Add or remove labels on a message or thread. |

## Health

HTTPX, Google OAuth, and encrypted owner tokens. Tools require a browser or private Telegram conversation.

Source: [service tools](../src/theos/services/health/tools.py).

| Callable | Action |
| --- | --- |
| `health_connect` | Create an authorization link for Google Health. |
| `health_disconnect` | Disconnect Google Health and stop pending imports and exports. |
| `get_health_summary` | Read your latest seven-day health import, or request a refresh. |
| `get_meal_sync_status` | List nutrition export states, including uncertain writes. |
| `retry_meal_sync` | Queue failed exports for reconciliation before any retry. |
| `backfill_nutrition` | Queue historical meals that have no backfill marker. |

## Zepto

Streamable HTTP MCP, OAuth, JSON Schema validation, and encrypted owner credentials.

Source: [service tools](../src/theos/services/zepto/tools.py).

Each user connects Zepto from the browser Connections view or a private Telegram chat.
The client discovers remote tools and registers them with the `zepto_` prefix.
It excludes the `zepto_shop` wrapper and validates arguments against each remote schema.
Only Zepto cart confirmation, checkout, order placement, and payment tools require approval.
Searches, reads, store setup, and ordinary cart updates run without approval.
Product search needs a selected delivery store.
Use `zepto_list_saved_addresses` and `zepto_select_saved_address` for the user's chosen address.
Use `zepto_get_location_serviceability` for a new delivery location's coordinates.
The tools explain the known missing-store error without exposing arbitrary remote error bodies.
Each account retains its own MCP session to preserve the selected store between calls.
Calls run in order. Failed or canceled calls do not replay automatically.

## Delegated research

`delegate_tasks` runs up to three research tasks with the parent's research allowance.
Each assignment supplies a descriptive `name`, `task`, relevant `context`, quoted `requirements`, and optional deep-research `source_ids`. Results and OTel spans include that name.
Theos chooses names from task scope. Users do not need to request delegation or name agents.
The runtime instructions prefer concurrent delegation for substantial independent research and direct execution for simple lookups.
Delegate instructions limit research to two focused search calls with three results each, then request findings and unverified facts.
These search limits are model instructions. Runtime limits enforce a configurable call cap and 85 seconds per delegate.
`AGENT_DELEGATE_MAX_MODEL_CALLS` defaults to ten calls. Each call also consumes the shared research allowance.
Delegates share the research budget and retain one parent call for synthesis.
Normal tools retain their 90-second deadline. Delegate groups permit each final handoff to finish.
Named delegates receive a focused brief and the original user messages selected by quoted requirements. Unrelated parent history stays with the parent.
Delegates return model-written answers with source URLs, status, and a limit reason to the parent.
The parent receives the full answers, rather than only a source list.
Legacy string assignments remain supported.
Delegates receive search, weather, and skill tools only.
They cannot create more delegates or change account data.
Source: [runtime tool registration](../src/theos/runtime/tools.py).

## Explicit deep research

Deep research requires the browser mode or an explicit user command. It applies to one turn.
The `deep_research` tool runs independent assignments within the same shared call ceiling.
Each researcher saves its full transcript, report, evidence, notes, and summary checkpoints in SQLite migration 010.
The browser **Research** view permits later inspection within the same account and conversation.
Normal questions do not receive these tools or create research records.

| Tool | Behavior | Dependency |
| --- | --- | --- |
| `deep_research` | Up to three named delegates with relevant briefs and durable records | Existing harness and runtime |
| `save_research_note` | Save plans, findings, conflicts, and questions with source IDs and status | Existing SQLite database |
| `list_research` | List research in the current conversation | Existing SQLite database |
| `read_research` | Reopen full saved reports and evidence | Existing SQLite database |
| `read_source` | Read and save extracted source text without an application excerpt limit | Exa contents API and `AGENT_EXA_KEY` |

Source extraction uses `POST https://api.exa.ai/contents` with `urls` and `text: true`.
It does not request `maxCharacters`. No new package dependency is required.
Search excerpts retain their search-provider limits. The source reader is separate.
Extraction can fail for inaccessible pages. Returned text is not proof that all page content was accessible.
See [Exa contents documentation](https://exa.ai/docs/reference/get-contents) and [research behavior](runtime/deep-research.md).

## Context and answer limits

Parents and delegates use the same model capacity and compaction policy.
OpenRouter metadata supplies the provider context and maximum output tokens.
The runtime caches metadata for one hour and uses verified catalog values when retrieval fails.
Unknown models use a logged 24,000-token context fallback unless the operator sets a window.
Unknown Anthropic models use the configured output default because that API requires an output maximum.
`AGENT_CONTEXT_TOKENS` optionally selects a smaller window, within known provider capacity.
The shared policy prunes old tool output before summarizing middle turns.
It protects the head and a tail selected by token cost, and updates the previous summary with an auxiliary model.
The default trigger fraction is 0.5, with the upstream floor for small windows.
See [compression and workspaces](runtime/context-recovery.md) for the formulas and execution boundaries.

For agents, only `max_output_tokens` enforces response length, through the provider's supported parameter.
OpenAI Responses and Gemini use `max_output_tokens`. OpenRouter and Anthropic use the equivalent `max_tokens` field.
Requests default to `AGENT_MAX_OUTPUT_TOKENS`, which defaults to 8,192, bounded by the provider maximum.
An explicit conversation output setting overrides this default.
Space checks reserve the full requested output before reducing input through summaries.
Answer and summary requests must fit their input and requested output within the model window.
The runtime does not silently lower the output setting to fit an oversized input.
Application code never clips generated answers or rejects them by byte size.
Calls without a known output setting use one shared 8,192-token space estimate.
`harness/output.py` defines that estimate for agents, turn entry points, and summary requests.
Known output settings replace the estimate. The estimate never enters a generation parameter or cuts returned text.
Provider-stopped answers remain intact and carry an incomplete notice.

## Optional bounded mode and partial answers

The call allocations below apply only to `Runtime(enforce_budgets=True)`.
Theos disables them by default and retains usage accounting.

`AGENT_MAX_MODEL_CALLS` sets the total ceiling, including research, compaction, titles, and final responses.
Omitted summary and delegate counts derive from the total, rounded up, using configurable one-sixth and one-third ratios.
Explicit counts override their ratios. The runtime resolves the allocation once per turn.
At the default total of 30, allocation is 24 research calls, five compaction calls, and one parent response call.
At 50, allocation becomes 40 research, nine compaction, and one parent response call.
Each delegate reserves one research slot for its final handoff before any sibling starts.
Its derived ceiling includes that handoff and is bounded by the research pool: ten at a total of 30, 17 at 50.
Compaction uses the separate shared compaction allowance and counts toward the total, outside the delegate ceiling.
The parent holds one summary call for its final response. Each active delegate holds one when available.
Ordinary summaries use unheld calls. Completed delegates release unused holds.
See the [call budget map](runtime/call-budgets.md) for request checks and exhaustion paths.
A total budget of one reserves the parent response without starting research.
The runtime accepts the legacy `AGENT_MAX_RECOVERY_CALLS` setting, but always permits one final response attempt.

Call, research-time, or context exhaustion stops new research and requests one final response without tools.
That request retains the task, corrections, complete available context, and a limit notice.
Final responses use the model window after reserving the requested output and compact only when necessary to fit.
Failed or oversized summaries trigger further cuts until the full request fits.
There is no fixed cut or provider-overflow retry count. Recovery retries only smaller requests and never repeats tools.
If mandatory content cannot fit, the runtime preserves it and returns a clear failure.
A failed final response never triggers a second attempt or repeats tools.
Research deadlines do not cancel active answer generation or final responses.
Provider connection idle timeouts and explicit cancellation remain active.
The connected terminal stream waits without a response read deadline.

Failed final generation returns a provider-specific error with no raw tool results.
Useful answers have `partial` status. Empty failures have `failed` status.
Incomplete scheduled runs pause their schedule. Explicit cancellation retains `interrupted` status.
Telegram, browser chat, and terminals replace incomplete drafts with the final answer.
Stored history retains replaced drafts for diagnosis and hides them when conversations reopen.
Connected terminals use protocol version 2. Update the client and deployment together.
OTel content capture has separate byte limits. Those limits do not change model answers.
Source: [context policy](../src/theos/runtime/context.py), [runtime recovery](../src/theos/runtime/recovery.py), and [model checkpoints](../src/theos/runtime/hooks.py).

## OpenTelemetry tracing

The server uses `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http`.
It exports turn, model, tool, delegate, and title spans through OTLP/HTTP protobuf.
Optional content capture includes messages, tool arguments, results, and named delegate tasks within configurable byte limits.
The runtime owns its tracer provider and background batch processor.
The optional `compose.tracing.yaml` runs Jaeger `2.22.0` with seven-day Badger storage in a separate volume.
Jaeger uses a 512 MiB container limit, a Go memory target, and the Collector memory limiter.
Jaeger supplies the waterfall viewer. It is an operations dependency, not an assistant tool.
The Pi uses host Tailscale `1.102.4` Serve for private HTTPS access to the viewer on port 8443.
Tailnet grants restrict this port to `group:theos-operators` across IPv4 and IPv6.
This host dependency does not change the application image or expose the OTLP receiver.
See [observability](base-infra/observability.md) for setup and trace contents.
Source: [tracing](../src/theos/operations/tracing.py) and [Jaeger configuration](../config/jaeger.yaml).
The [content serializer](../src/theos/operations/trace_content.py) uses the OTel GenAI role and parts schema without new dependencies.
Runtime phase spans measure queue waits, history restoration, model capacity, tool registration, memory retrieval, and local checkpoint persistence.
HTTPX hooks measure each OpenAI-compatible HTTP request through response headers.
Model spans retain first-chunk and complete generation timing separately.
The [provider diagnostics](../src/theos/operations/provider_diagnostics.py) retain validated identifiers and allowlisted classifications.
Raw provider errors, prompts, authentication headers, and unknown metadata never enter diagnostic fields.
OpenRouter can retry a transient accepted stream twice before any output, without repeating tools or weakening ZDR.

## Scheduled agent tasks

SQLite, croniter, and the normal agent runtime execute one-time or recurring tasks.
The scheduler owns occurrence claims and delivery status.
Source: [task tools](../src/theos/services/schedules/tools.py) and [dispatch](../src/theos/runtime/scheduled.py).

| Tool | Action |
| --- | --- |
| `schedule_task` | Schedule a named agent task in the creating conversation |
| `list_scheduled_tasks` | List the owner's schedules |
| `pause_scheduled_task` | Pause future runs |
| `resume_scheduled_task` | Resume a paused schedule from a future time |
| `cancel_scheduled_task` | Cancel future runs without deleting history |
| `list_scheduled_runs` | Read execution and delivery states |

## Memory automation

HTTPX supplies bounded owner-scoped retrieval before private-chat model calls.
SQLite queues consented user text for Mem0 OSS fact extraction and consolidation.
The worker uses the existing Mem0 inference, embedding, and vector-store dependencies.
Source: [memory automation](../src/theos/services/memory/automation.py).

| Tool | Action |
| --- | --- |
| `configure_memory_automation` | Set retrieval and consolidation policy at the user's request |
| `get_memory_automation_status` | Read owner policy and batch status counts |

## Approval boundary

The global policy requires approval for Gmail sending and Zepto cart confirmation, checkout, order placement, and payment-related tools.
This includes online payments, UPI, wallet payments, and payment status tools.
Searches, cart updates, delivery-store setup, and account reads do not prompt.
Sandbox execution, draft creation, file and table deletion, and memory settings do not prompt.
Gmail checks the recipients, subject, body, attachments, and raw draft hash against the approved preview before sending.
Account ownership, tool validation, transcript checkpoints, and uncertain-action recovery remain active.
Each approval still binds one user, conversation, call ID, and exact arguments, with a 15-minute expiry.
Old pending cards for tools that no longer need approval are retired without changing their saved snapshots.

Source: [approval policy](../src/theos/runtime/approvals.py).


## Context compression and durable workspaces

The generic policy lives in `src/harness/compression_policy.py` and its asynchronous adapter in `src/harness/lean_context.py`.
The source manifest pins the upstream revision and preserves its MIT license.
Request sizing uses provider usage anchors and the upstream UTF-8-aware rough estimator. No tokenizer package is required.

The runtime owns `history_read` and `history_search` for bounded access to original agent history.
The Gmail and Health wrappers add `source_read` and `source_to_workspace` for complete saved connector responses.
They preserve raw results in fsynced local objects and queue R2 replication.
Returned pages include source IDs, offsets, and pagination tokens.
MIME text views identify unread attachments and do not download them.
MCP tools and connector implementations remain unchanged.

`services/files/checkpoints.py` uses the existing boto3 dependency for R2 objects and the SQLite transfer index.
One background worker uploads bounded batches and publishes only complete recovery pointers.
Checkpoint persistence and connector reads do not wait for those uploads.
The storage client is reused and has bounded connection, read, and retry settings.
`services/sandbox/workspace.py` uses the existing OpenSandbox SDK for `/workspace` files and restoration.
The agent can choose this workspace without an explicit sandbox request from the user.
Changed files, including nested files and output from failed commands, receive versioned checkpoints.
Sources and model checkpoints require the authenticated owner and conversation.
See [compression and workspaces](runtime/context-recovery.md) for the complete storage contract.
