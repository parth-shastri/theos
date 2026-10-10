# Theos project memory

Updated: 2026-10-10.

## Confirmed decisions

| Decision | Value |
| --- | --- |
| Assistant name | Configurable through `AGENT_NAME`, default `Theos` |
| Repository | `/Users/nightowl/my_projects/theos` |
| Harness ownership | Theos owns the copy under `src/harness` |
| Default model and API | `gpt-6-luna` through OpenAI Responses |
| First transport | Telegram |
| Terminal command | Installed `theos` opens the terminal UI. The HTTP server retains `python -m theos.server` |
| Terminal appearance | Use no diamond markers in the TUI. `/status` shows a bordered snapshot with a colored run state and grouped model, session, workspace, and latest-turn details. Latest-turn counters cover events observed by this client and reset on session changes. Keep this renderer behavior in `agents-intro` |
| Terminal runtime | Standalone mode uses the existing SQLite lock, scheduler, tool policy, and a separate `terminal:<local profile>` owner. Connected mode uses one deployed runtime through HTTP and owns no local database or scheduler |
| Terminal deployment connection | `--server` or `AGENT_SERVER_URL` selects the deployed workspace. Authenticate with the browser token through a hidden prompt, `AGENT_SERVER_TOKEN`, or `--token-file`. Share browser conversations, history, settings, usage, account tools, and approvals. Read only client settings in connected mode, without loading model SDKs or validating local service credentials. Preserve standalone mode through `--local`. Never fall back locally after connection failure or retry uncertain requests automatically |
| Terminal deployment controls | Offer `/settings`, `/model`, `/reasoning`, `/usage`, and `/continue` in connected mode. Show supported command options and native settings and usage dialogs. Keep `/thinking` for trace visibility. Preserve approval batches, delegate scope, images, titles, and steering through server endpoints. Closing the client leaves server work running |
| Terminal configuration | Current `.env`, editable codebase `.env`, then `~/.config/theos/.env`. Explicit `--config` takes precedence |
| Terminal storage | Default `~/.theos`. Resolve configured relative data paths from the configuration directory |
| Telegram onboarding | Private `/start` asks what to call the user, then asks for a valid timezone. Save the chosen name in owner-scoped preferences and include it in model context. `/skip` accepts the saved name when available. Preserve existing completed profiles and pending timezone setup |
| Telegram access code | Optional `AGENT_TELEGRAM_ACCESS_CODE` in private `.env`; SQL authorization replaces manual sender enrollment |
| Telegram enrollment limit | 50 unique senders per database, including incomplete setup. Operators can lower the limit |
| Browser style | Controls and visual style from ocr-checker |
| Browser usage and tools | Owner and conversation USD estimates. Administrator totals and cost breakdowns include all transports. Missing prices stay visible. Collapsed reasoning summaries and tool calls. Searchable conversation tool registry with approval labels |
| Usage view access | Every browser user has personal Activity & usage through their token. Administrators have a separate Admin dashboard for all users and transports. Personal charts always use the authenticated owner, including administrator tokens. Administrator responses exclude conversation titles and message content |
| Enrollment roles | The deployment operator uses an explicitly configured administrator account in `AGENT_USERS` and `AGENT_ADMINS`. First registration never grants administrator access. New Telegram enrollments receive ordinary access. With `AGENT_WEB_URL` configured, completed users receive a browser link and confirm a matching code in Telegram. Generated browser credentials reuse their stable Telegram owner and never grant administrator access |
| Browser enrollment credentials | SQLite stores hashes of single-use 10-minute invitations, browser pairing secrets, personal tokens, and seven-day device sessions. Confirmed sign-in issues an HttpOnly, SameSite Strict session cookie and shows a personal token once. New sign-in replaces the saved token while retaining other device sessions. `/web revoke` removes all generated browser access without deleting personal data. Preserve configured browser IDs and do not merge accounts by name |
| User-owned encryption requirement | Deferred: the user requested completion of onboarding without choosing an encryption mechanism. Private content storage, password wrapping, and automatic key access remain proposals. Current personal content is not encrypted. Keep the existing encrypted service credentials and content-free usage views. Hosted processing can expose plaintext to the running server |
| Encrypted history continuity | Restore saved history automatically while a decryption grant is active. The user requested transparent access across turns. Password-based key wrapping and automatic key-service access remain proposals. Losing a runtime grant must not erase encrypted history. See `docs/architecture/theos-encryption-proposal.excalidraw` for the proposed boundary |
| Browser model controls | Keep the current model selector. OpenRouter exposes the six requested aliases plus the existing default. Preserve explicit operator allowlists. Save supported generation parameters in SQLite migration 006. Model-specific cost rates can override shared rates |
| Browser settings and command panels | Move model and reasoning into the header Settings dialog with generation and voice controls. Save changes together and discard canceled drafts. Use a sidebar icon beside the logo to toggle conversations. Show interactive help and usage dialogs. Keep usage access through `/usage`, without a sidebar Usage button. Keep generation controls in Settings, without `/generation`. Offer supported options for argument commands. List only `/reasoning`, with `/thinking` retained as a compatibility alias |
| Browser commands and voice | Slash command help and keyboard suggestions. Record microphone audio for editable transcription. Optional TTS reply playback through the existing configured voice services |
| Browser identity and thinking | Copy the mini-theos logo into owned browser assets. Animate active thinking and respect reduced motion |
| Browser voice controls | Use accessible microphone, recording stop, and speaker icons. Keep TTS playback in one play/stop button, cache audio for replay, and stop it on conversation changes. Use the mini-theos glow during thinking and the theme accent during recording. Smooth microphone RMS volume into the composer glow with a quiet baseline. Close the analyzer on stop, cancellation, errors, or page exit. Reduced motion keeps a static recording glow |
| Browser Markdown and composer | Render streamed and saved thinking and replies with pinned, locally served Marked 18.1.0 and DOMPurify 3.4.16. Show raw HTML as text, block unsafe links, and show remote images as links. Preserve raw Markdown for token estimates. Copy code without toolbar labels and send rendered plain text to TTS. Start the composer at one line and grow it to 140px. Inset native dropdown chevrons by 14px |
| Dashboard charts | Use native SVG and HTML charts for daily model requests, recorded USD cost, input/output tokens by model, and main-agent tool starts. Offer 7, 30, and 90 day UTC ranges. Aggregate complete records across transports behind administrator access. Preserve missing prices, zero-fill inactive dates, and provide hover/tap details and chart data tables |
| Browser UX and appearance | Align chat messages and the composer at a shared left gutter. Keep attachment, command, input, microphone, and send controls in one row. Hide attachment and command buttons during mobile recording to retain input space. Grow multiline drafts, preserve reading position during streams, and dismiss the mobile drawer after navigation. Use the mini-theos Daylight logo in light mode |
| Browser message statistics | Show estimated output tokens and elapsed time during each model generation. Use final provider usage when available. Save UTC message timestamps and generation duration in application history metadata. Show local dates as `6 Oct 14:32`. Preserve unknown dates for older messages. Keep display metadata out of provider and generic harness serialization |
| OpenRouter accounting | Keep its adapter in the application runtime. Retain readable reasoning, replay signed blocks only for the same model, and prefer reported request costs over token-rate estimates |
| Browser conversation titles | Generate from the first completed exchange with the selected model and refine once after three user messages. Bound title calls, include their usage in costs, preserve custom titles, and retain a fallback on failure. Migration 007 tracks automatic titles |
| Configuration | Pydantic settings with the `AGENT_` prefix |
| Deployment | One application worker and scheduler per SQLite database |
| Distribution | Self-hosted installations and an operator-hosted Telegram service |
| Google credential ownership | Each deployment operator supplies OAuth clients and an encryption key. Each browser or private Telegram user authorizes their own accounts |
| Browser account connections | Owner-bound Gmail, Google Health, and Zepto consent, status, cancellation, and disconnection. Keep existing configured browser IDs outside reserved namespaces. Telegram-confirmed browser credentials use the enrolled Telegram owner's private account access. No automatic merging of existing browser and Telegram accounts |
| Browser connection mentions | Show local provider logos for accounts and use-case SVG icons for all workspace services in Connections and `@` suggestions. Complete mentions at the composer caret with current account status and configured workspace services. Preserve draft text. Send mentions as ordinary user text without changing access or approval policy |
| Zepto account linking | Browser and private Telegram users authorize their own accounts through MCP OAuth. Theos encrypts credentials in SQLite. Use the localhost return handoff by default, with an optional public HTTPS callback |
| External memory | Separate Mem0 OSS REST service with explicit, owner-scoped tools. Use OpenRouter for Mem0 models. Mem0 Platform needs an adapter |
| Memory automation | Bounded private-chat retrieval when memory is enabled. Per-user approved opt-in for future user-message consolidation through Mem0 inference |
| Scheduled agent tasks | Durable one-time and cron schedules run through the normal conversation runtime and approval policy. Interrupted or uncertain runs pause the schedule |
| Remote sandbox | OpenSandbox can run on the Mac mini over Tailscale. Enable `AGENT_SANDBOX__USE_SERVER_PROXY` for execution through its server |
| Speech hosting | Separate services. Document Docker CPU, native Apple Silicon MLX/MPS, and hosted transcription. Generic hosted speech output needs an adapter or client changes |
| Code organization | Separate service directories with plain functions and small lifecycle classes |
| Comments | Explain constraints and number the major workflow steps |
| Documentation | Task-based Markdown guides, Simplified Technical English, and existing Excalidraw PNG diagrams |

Application and deployment environment variables use the `AGENT_` prefix.
The configured name supplies model instructions, browser labels, and Telegram greetings.
The package name, storage paths, and existing deployment resource names remain stable.

The user requested removal of unrelated starter examples and historical planning documents.
The required mock API fixture now lives under `tests/fixtures`.
Keep harness tests, source notices, provenance manifests, and editable architecture sources.
Keep only reusable building blocks in the separate `agents-intro` repository.

## Implemented application

The application lives in `src/theos`.
It includes persistent chat, Telegram, browser chat, approvals, reminders, personal tools, and optional service clients.
Each service owns its tools and its external protocol or record rules.
The runtime owns conversation locks, tool checkpoints, permissions, and delivery events.
The [code guide](docs/code-structure.md) maps these responsibilities to files.

Run `python -m theos.server` after installing the `server` extra.
Keep that entry point, `theos.server.create_app`, `theos.runtime.Runtime`, and the backup commands available.
The harness, renderer, and copied logging package retain their existing interfaces.
Theos has no runtime package dependency on `agents-intro`.

The terminal transport lives under `src/theos/transports/terminal`.
The `terminal` extra includes application dependencies, Rich, and Textual for standalone mode.
The `client` extra includes HTTPX, Pydantic Settings, Rich, and Textual for connected mode.
The installed command needs no factory or module target.
It adapts raw runtime events to the generic renderer and preserves nested delegate progress.
It supports saved sessions, titles, archive state, image attachments, steering, and approval recovery.
The runtime saves unconsumed steering on interruption.
The standalone terminal scheduler displays reminders and saved scheduled task results as notices.
Connected clients read shared browser conversations from the deployment using the browser token.
The server owns the only runtime, database connection, and scheduler for that deployment.
It sends display-only events without provider state or harness run results.
Client disconnection does not cancel server work. Reconnect and inspect saved history before another request.
Standalone terminal accounts never adopt Telegram identity or account tools.
Connected clients use the authenticated browser owner, including Telegram-confirmed browser credentials.

Ordinary chat continues during optional memory outages.
Consolidation requires explicit per-user opt-in through the approved memory automation tool.
Only new user text from completed private turns enters the consolidation queue.
Exclude group messages, scheduled prompts, assistant output, and tool output.
Do not retry uncertain memory writes automatically.
Retrieval supplies fallible reference data, never permissions or executable instructions.
Do not repeat uncertain external effects after a crash.
Do not rerun a turn because Telegram reply delivery failed.
Compaction cannot grant permissions or create authoritative personal records.

Gmail, Google Health, and Zepto support authenticated browser users and allowed private Telegram identities.
Groups and standalone terminal sessions receive no account tools.
Connected terminal clients retain the authenticated browser user's account-tool permissions.
Browser Connections shows account setup and optional service configuration without credentials.
Configuration status does not prove live service access.
Google consent uses saved owner-bound, single-use state and PKCE.
Zepto return URLs use a dedicated authenticated endpoint outside model history.
Account credentials and personal records belong to the owner across private conversations.
Approvals, chat state, and sandbox references belong to the conversation.
Browser approval cards clear when the server accepts either decision.
Disable decision buttons during submission and refresh saved approvals after stream failures.
Reuse tool rows by call ID so resumed actions replace stale waiting states.
Configured browser IDs cannot use the `telegram:`, `telegram-group:`, or `terminal:` prefixes.
Existing browser IDs remain stable.
Telegram-confirmed browser credentials reuse the enrolled sender's `telegram:<id>` owner.
The browser and Telegram share personal records and usage while retaining separate conversation threads.
Existing configured browser accounts do not merge with Telegram accounts automatically.
An empty Telegram sender allowlist permits registration through the bot within the user limit.
When configured, the deployment access code is required through `/start <access-code>`.
Without an access code, registration is public.
A nonempty allowlist restricts registration and chat access.
Completed enrollment grants private account connection access without a manual sender allowlist.
Existing explicitly allowed accounts remain compatible when no access code exists.
Zepto uses a deployment-configured MCP endpoint and owner-scoped OAuth credentials.
Product search requires a selected delivery store, even when order history works.
Search tools explain saved-address selection and location serviceability before search.
Map the known missing-store error to setup guidance. Keep unknown remote error bodies private.
Store setup keeps the normal approval policy. Do not select addresses or retry actions automatically.
Retain one MCP session per account and serialize its remote calls.
This preserves selected delivery stores across conversations without sharing them between owners.
Close these sessions on account reconnection, disconnection, and application shutdown.
Failed or canceled calls do not replay. A later call can start a new session and need store setup again.
Do not configure per-user Zepto tokens in `.env`.
Keep each deployment password in private `.env`, never in shared samples or source defaults.
SQL stores code fingerprints. The inbox removes code arguments before persistence.
Changing the code requires authorization again and preserves profiles, conversations, and enrollment slots.
SQLite retains onboarding state across restarts.
Existing private Telegram users retain access and count toward the enrollment limit without losing saved preferences.
Keep application credentials out of general-purpose sandboxes.
Both distribution options use the existing server and Google account services.
Self-hosted operators configure their own Google project, bot, model credential, and callback URLs.
Hosted users complete Telegram onboarding and Google consent without application secrets.
Do not ship a shared Web client secret in self-hosted packages.
The hosted option retains the 50-user limit and one worker per database.
Public Google approval and live account checks remain external launch requirements.
Theos has no central OAuth broker for independent installations.
Track live service checks separately from mocked acceptance coverage.
See [acceptance](docs/runtime/acceptance.md) for results and open checks.

## Architecture artifacts

Preserve the uploaded framework in `docs/architecture/reference/Agent-Harness.excalidraw`.
Preserve its harness, memory, consolidation, and operations layout.
Use the Excalidraw MCP for diagram changes and font family `1` for traditional handwriting.
Keep editable drawings, MCP elements, and PNG exports in sync.
Use PNG exports in the guides.
The uploaded Agent Harness framework is the primary architecture reference.
Lead the README, documentation home, and architecture guide with the complete framework diagram.
Explain all six diagrams in the architecture guide, with implementation status for each framework path.
Place the runtime/service diagram under Current implementation after the framework sections.
Keep that runtime diagram as the main view in the code structure guide.

The runtime now retrieves owner-scoped facts and queues consented text for Mem0 extraction and consolidation.
General episodic retrieval, evaluation gates, and a high-level library facade remain future work.
The framework drawings do not prove implementation of those paths.

Keep the reference assistant's name and repository URL out of project artifacts and responses.
Preserve its required source attribution and license notices.
The provenance manifests record original transfers. Their file paths and hashes are historical evidence, not the current file layout.

## Documentation structure

The documentation starts at `docs/index.md` and `docs/documentation-map.md`.
Separate guides cover deployment, operations, configuration, development, transports, and optional integrations.
Keep procedures consistent with the current source and the `AGENT_` environment samples.
Reuse the existing diagrams and label planned framework components explicitly.
The cleanup removed duplicate runtime overview and deployment guides.
The service overview now lives at `docs/services.md` and links to the detailed integration guides.
Update active links when removing replaced guides.
Preserve historical paths in provenance manifests.

## References

- [Documentation home](docs/index.md)
- [Documentation map](docs/documentation-map.md)
- [Code structure](docs/code-structure.md)
- [Architecture](docs/architecture/README.md)
- [Tool catalog](docs/tool-catalog.md)
- [Starter provenance](docs/starter-provenance.json)
- [Application provenance](docs/application-migration.json)

## Git and Raspberry Pi releases

The private GitHub repository is `parth-shastri/theos`.
Start normal changes on a topic branch from `dev`, including fixes, features, chores, and documentation.
On 2026-10-10, the operator approved an exception for urgent Pi release fixes while `dev` contains unfinished changes.
Start these hotfixes on a `fix/<name>` branch from `rpi` and merge them into `rpi` through a PR.
Validate the hotfix and publish a new patch release from `rpi`.
Cherry-pick the fix onto a separate topic branch from `dev`, adapt it when necessary, and merge through a PR.
The operator prohibits the `codex/` branch prefix in every repository going forward.
Use descriptive names such as `fix/<name>`, `feature/<name>`, `chore/<name>`, or `docs/<name>`.
Merge normal topic branches into `dev` through a PR.
Promote `dev` through a separate PR for each destination when ready: `main`, `rpi`, or both.
Promotions are independent. Every change does not require both promotion PRs.
Publish Raspberry Pi releases from `rpi`.
Do not commit changes directly to `dev`, `main`, or `rpi`.
Tags named `rpi-vX.Y.Z` must match the package version and the current remote `rpi` commit.
CI covers Python 3.12 and 3.13, browser syntax, packages, workflow validation, secret scanning, and containers on amd64, arm64, 386, ARMv7, and PPC64LE.
An explicit extended run also checks s390x and RISC-V64. AMD64 and ARM64 run natively; other targets use QEMU.
The release workflow publishes a tested arm64 image and deploys its digest with a Pi runner labeled `theos-rpi`.
Activation uses a separate restored data volume. Failure restores the previous image and original volume.
The Pi SSH alias is `neuralbox-pi`; the default deployment directory is `/home/neuron/theos-deploy`.
The Pi is online on 64-bit Debian 13 with Python 3.13.
The repository runner is installed as a `neuron` system service. Docker access and Compose are configured.
The operator authorized deriving a private `.env.pi` from the existing local `.env`.
The Pi user and administrator are `owner`. Gmail and Google Health use HTTPS callbacks at `theos.parth-shastri.com`.
Keep local `.env` unchanged. Store `.env.pi` with mode `0600`, outside Git and outside the runner checkout.
On the Pi, the deployment `.env` is a symlink to `.env.pi`.
The Pi release checks Telegram with read-only `getMe` and `getWebhookInfo` requests before stopping the worker and after activation.
Invalid credentials, network failures, malformed responses, and active webhooks fail the check. An empty bot token skips it.
Branch and pull-request CI use mocked responses. Production Telegram credentials remain in the private Pi environment outside the runner checkout.
The check does not read updates or send messages. It does not prove reply delivery or detect another polling process.
On 2026-10-10, the prior token returned HTTP 401. The operator replaced it in local `.env.pi`.
Only that token was synchronized to the Pi. Container recreation applied it.
Live authentication and polling-configuration checks passed for `@mytheos_bot`.
The connection-check code needs a new tagged release before it becomes part of the deployed image.
GitHub rejected branch protection for the private repository because the account requires an upgrade.
The disposable Docker rehearsal passed first installation, replacement, intentional readiness failure, and automatic rollback on the Pi.
Both the original and restored SQLite records survived.
CI passed on `main` and `rpi` with Python 3.12 and 3.13, native amd64 and arm64 containers, workflow validation, browser checks, and secret scanning.
Release `rpi-v0.1.0` is deployed and healthy on the Pi.
The running container uses `owner` and the HTTPS Google callbacks. Readiness and browser-token authentication passed.
The GHCR image denies anonymous pulls. The first registry upload failed with `unknown blob`; retrying publication succeeded before any deployment change.
The Cloudflare tunnel routes all paths on `theos.parth-shastri.com` to `http://localhost:8080`. Its proxied CNAME targets tunnel `4584e314-7c3f-448a-8118-7b6e324ebe3c`. Public HTTPS checks passed for the homepage and its assets, health endpoints, authenticated owner APIs, rejection of anonymous API requests, and both Google callback routes. A real model turn completed through the public SSE stream, and its conversation history was saved. The operator updated the Google redirect list. Full Google consent and account linking remain untested. The existing `mytheos.parth-shastri.com` frontend uses its original Vercel CNAME. On the operator Mac, Tailscale's internal DNS lookup retained a stale nonexistent-domain response despite correct public DNS answers. Refreshing `accept-dns` off and back to its original enabled setting restored normal macOS resolution. The Theos browser workspace then loaded, owner sign-in succeeded, and a browser-submitted real model turn returned `BROWSER_OK` in Brave.
See [Git and releases](docs/releases.md).
