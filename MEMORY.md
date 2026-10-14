# Theos project memory

Updated: 2026-10-14.

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
| Telegram setup guidance | After setup, point users to Connections in the web UI to add connectors and to the existing `/help` command. Show web guidance when `AGENT_WEB_URL` is configured. Otherwise, show help for capabilities and account connections |
| Telegram temporary activity | Remove finished tool and compaction messages. Clean active indicators when delivery ends. Send one final message with elapsed time, tool counts, failed or uncertain outcomes, and successfully loaded skills. Count parent and delegate events before display queues can discard them. Approval cards notify once and remain pending until a decision or expiry. Store review message references in SQLite migration 012, including multipart reviews, attached reviews, and waiting notices. Remove resolved cards immediately for Telegram decisions and through polling for other decisions or expiry. Failed deletion removes buttons when possible and retains references for another attempt. Preserve durable approval snapshots, tool results, transcripts, and recovery behavior |
| Reply formatting | Render assistant Markdown as Telegram text and explicit UTF-16 entities. Split long messages without losing text or formatting. Keep command responses literal. Show approval reviews as labeled fields, formatted prose, and literal code. Preserve exact arguments for approval checks. Browser and terminal retain their own Markdown rendering |
| Assistant punctuation | Never use em dashes in assistant replies, reasoning summaries, or generated titles. Add shared model instructions and replace any emitted em dash with an ASCII hyphen before display and persistence. Preserve user input, tool arguments, and opaque provider data |
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
| OpenRouter retention | Enforce `provider.zdr=true` in the application adapter for every OpenRouter request, including chat, delegates, compaction, and titles. Preserve other provider preferences. No request can disable ZDR. External Mem0 and voice services keep separate policies |
| OpenRouter reasoning routing | For OpenAI models, replay encrypted reasoning from only the latest known provider format in each wire request. Omit incompatible sequences without changing saved messages or signed blocks. Recover a mixed-provider HTTP 400 once before generation, with the same restrictions as the ZDR routing retry. If OpenRouter rejects encrypted OpenAI reasoning with a ZDR routing 404 before generation, retry once without those reasoning sequences. Preserve messages, tool exchanges, model options, saved history, and ZDR. Do not retry unrelated errors, Claude signatures, or streams that emitted events. A retry is a transport attempt within the same harness model call |
| Browser conversation titles | Generate from the first completed exchange with the selected model and refine once after three user messages. Bound title calls, include their usage in costs, preserve custom titles, and retain a fallback on failure. Migration 007 tracks automatic titles |
| Configuration | Pydantic settings with the `AGENT_` prefix |
| Deployment | One application worker and scheduler per SQLite database |
| Tracing | Optional runtime-owned OTel SDK with OTLP/HTTP protobuf export. One root trace per turn. All spans share the existing conversation ID and a separate turn ID. Model and tool spans nest under the turn, with separate parallel research delegates. Export metadata by default. Optional bounded content capture includes model messages, tool arguments/results, and delegate tasks/results. Use OTel GenAI roles, parts, and descriptive agent names inherited by child spans. Retain legacy string delegate tasks. Theos chooses descriptive agent names from task scope without user-supplied names. Delegate substantial independent research when useful, and handle simple or dependent lookups directly. Instruct research delegates to use at most two focused search calls with three results each, then return findings and unverified facts. These search limits are guidance. After delegation, instruct the parent to use findings and caveats, with at most two focused verification searches before answering. Retain call usage accounting and the 90-second tool timeout. Capture limits default to 8,192 UTF-8 JSON bytes per field and 32,768 per span. Exclude reasoning, binary payloads, provider state, and exception payloads. Keep SQLite events and usage. Use optional Jaeger v2 with single-node Badger storage for waterfalls |
| Trace access | The optional Jaeger viewer and OTLP receiver bind to host loopback. The Pi uses persistent Tailscale Serve on HTTPS port 8443 to proxy the viewer. Restrict Pi TCP 8443 to `group:theos-operators` in the tailnet policy. Exclude this endpoint from broader grants across both IP families. The group currently contains `parth-shastri@github`. Keep Funnel disabled for this endpoint. Jaeger has no configured password or per-user trace isolation. Theos authentication does not protect it. Operators can also use local access or authenticated SSH tunnels. Anyone with Jaeger access can inspect all stored traces. Per-user trace access requires a separate ownership-checking layer and is not implemented |
| Diagnostic retention | Keep SQLite events and usage unchanged. Rotate application logs by size and age, and bound Docker logs. Use seven-day Jaeger span expiry, a 512 MiB container limit, and memory pressure guards. Do not impose a 1 GB disk quota. Jaeger storage retains traces across restarts. Monitor disk growth separately |
| Turn recovery | Preserve the transcript and uncertain actions. Retry provider context rejection only with a smaller request, without repeating tools. An irreducible request remains a failure, never a fabricated successful answer |
| Tool execution batches | Replace the hard 16-call response rejection with `ExecutionLimits.tool_batch_size`, default 16. Process every valid call in ordered batches. Only tools declared safe may overlap. Keep each call ID and approval check. Append each batch's results before the next batch. Tell the model to request at most 16 calls per response and provide explicit feedback after larger groups. Reject invalid arguments per call as `not_started` before approval or execution, with correction instructions and a new call ID. Keep `failed`, `denied`, and `unknown` outcomes distinct. Duplicate IDs and malformed response identities remain fatal before execution. Retain transcript and checkpoint guarantees. Record exact generated call counts in trace metadata and only fixed harness error codes in logs |
| Approval policy | Global approval prompts apply only to Zepto cart confirmation, checkout, order placement, and payment-related tools. Search, read, delivery-store setup, ordinary cart updates, all sandbox actions, email sending, deletion, and memory settings do not prompt. Keep owner isolation, validation, durable attempts, exact approval snapshots, and unknown-outcome recovery. Retire old pending cards for ungated tools without executing anything during cleanup |
| Sandbox creation lifetime | Default and Pi configuration are 3,600 seconds from creation. Cached and saved references retain their original deadlines. Activity and the legacy renew action cannot extend expiry. Check cached instances before use. Recreate only confirmed missing or expired instances. Preserve references on transient failures and never replay an operation automatically. Restore workspace checkpoints before saving a replacement instance. Status and explicit restart remain available. Destroying an absent sandbox does not create one |
| Skill selection | Include installed skill descriptions in model context. Match task intent to descriptions and load relevant instructions before work without requiring skill names from the user. Do not load every skill or treat names as the whole selection policy. Supply report-style and document-format instructions automatically for document requests. New reports default to styled PDF. Explicit formats and existing document styles retain precedence. Count automatically supplied skills in turn stats. Shared scripts and assets still need transfer into the sandbox |
| Model-call allowances | Theos disables call allocations and research deadlines by default through `Runtime(enforce_budgets=False)`. Preserve all budget fields and their validation for callers that explicitly enable bounded mode. Parent, delegate, summary, and recovery calls retain usage accounting without enforced call ceilings. Root traces mark enforcement false and limits as -1. Provider, context, output, tool, concurrency, approval, and cancellation limits remain active. See `docs/runtime/context-recovery.md` |
| Distribution | Self-hosted installations and an operator-hosted Telegram service |
| Google credential ownership | Each deployment operator supplies OAuth clients and an encryption key. Each browser or private Telegram user authorizes their own accounts |
| Browser account connections | Owner-bound Gmail, Google Health, and Zepto consent, status, cancellation, and disconnection. Keep existing configured browser IDs outside reserved namespaces. Telegram-confirmed browser credentials use the enrolled Telegram owner's private account access. No automatic merging of existing browser and Telegram accounts |
| Browser connection mentions | Show local provider logos for accounts and use-case SVG icons for all workspace services in Connections and `@` suggestions. Complete mentions at the composer caret with current account status and configured workspace services. Preserve draft text. Send mentions as ordinary user text without changing access or approval policy |
| Zepto account linking | Browser and private Telegram users authorize their own accounts through MCP OAuth. Theos encrypts credentials in SQLite. Use the localhost return handoff by default, with an optional public HTTPS callback |
| External memory | Separate Mem0 OSS REST service with explicit, owner-scoped tools. Use OpenRouter for Mem0 models. Mem0 Platform needs an adapter |
| Memory automation | Bounded private-chat retrieval when memory is enabled. Per-user explicit opt-in for future user-message consolidation through Mem0 inference |
| Scheduled agent tasks | Durable one-time and cron schedules run through the normal conversation runtime and approval policy. Interrupted or uncertain runs pause the schedule |
| Remote sandbox | Keep the Mac mini configuration, database, and server logs under `/Volumes/extssd/opensandbox`. Pin the native server to `1.1.1`. Use server proxy mode with `resolve_internal=false`. Keep launchd console logs under the user's Library because macOS blocks its removable-volume access. Docker storage remains on the SSD |
| Model context | Use the pinned middle-turn compression policy in `src/harness/compression_policy.py`: tool-output pruning first, protected head, token-budget tail, iterative auxiliary summaries, distributed samples, and scaled budgets. One async adapter in `lean_context.py` serves all agents. Default fraction 0.5 with the upstream small-window floor. Pi 100,000 context and 8,192 output imply a 68,856-token trigger. Keep raw sources outside model context and checkpoint working state in R2 |
| Reply generation requirement | Main responses use the configured provider output limit, default 8,192. Do not clip generated answers. The auxiliary summary uses a scaled prompt target without a hard output cap. Explicit cancellation, provider timeouts, and output truncation remain distinct. Bounded callers retain research deadlines without cancelling an active answer |
| Explicit deep research | Start only through the browser mode or an explicit user command. Apply the mode to one turn. Normal questions receive focused delegate briefs and protected final response capacity. Deep research adds conversation-owned SQLite records, full source reading through Exa, structured notes, validated summary references, and the browser Research view. Retain original sources, notes, transcripts, reports, and summary checkpoints. Source references protect retrieval, not factual truth |
| Speech hosting | Separate services. Document Docker CPU, native Apple Silicon MLX/MPS, and hosted transcription. Generic hosted speech output needs an adapter or client changes |
| Code organization | Separate service directories with plain functions and small lifecycle classes |
| Shared Pi skills | Store operator-installed skills in `/home/neuron/.agents/skills`. Use skills.sh with a temporary Node 22 runtime. Theos mounts that same host directory read-only at `/skills` through `compose.skills.yaml`, `THEOS_SHARED_SKILLS_DIR`, and `AGENT_SKILLS_DIR`. Retain source licenses, installation metadata, file hashes, and local adaptations. Reapply report overrides after upstream updates |
| Paper research | Prefer the official `pwc-cli` skill from `huggingface/pwc-cli`. Use arXiv and Hugging Face skills as supplemental sources. Public catalog research needs no credentials. Keep host CLI installation separate from remote sandbox execution |
| Report appearance | New PDF and DOCX reports use the operator-supplied neutral `report-style`: Inter typography, green numbered headings, beige tables, dashed rules, yellow status badges, and consistent diagram colors. Explicit user styles take precedence. Preserve existing document styles during edits. Render and inspect every output page |
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

The public GitHub repository is `parth-shastri/theos`.
On 2026-10-10, the operator made the repository public to avoid the private-repository Actions minutes quota.
GitHub now permits branch protection for this repository without an account upgrade.
On 2026-10-11, the operator required branch protection on `dev`, `main`, and `rpi`.
The operator then replaced the three branch protection rules with one active [repository ruleset](https://github.com/parth-shastri/theos/rules/24850327).
The `Integration branches: PR and CI` ruleset targets only these three branches and has no bypass actors.
Each branch requires a PR and the `CI passed` check from GitHub Actions, including for administrators.
Force pushes and branch deletion are blocked. Reviewer approvals remain optional, and merge commits remain allowed.
Branches need not be current with the destination before merge. Destination PR CI still validates the proposed merge.
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
Use merge commits for branch promotion and history synchronization PRs. Do not squash or rebase these PRs.
On 2026-10-10, PR #1 promoted the code to `main` through a squash merge, leaving different histories with identical files.
The operator requested history synchronization through a topic branch from `dev`, a merge of `main`, and a PR into `dev`.
Publish Raspberry Pi releases from `rpi`.
Do not commit changes directly to `dev`, `main`, or `rpi`.
Tags named `rpi-vX.Y.Z` must match the package version and the current remote `rpi` commit.
CI covers Python 3.12 and 3.13, browser syntax, packages, Compose, workflow validation, and secret scanning.
On 2026-10-10, the operator requested lower CI usage through destination-specific container coverage.
Run CI on PRs into `dev`, `main`, and `rpi`, and pushes to those integration branches.
Topic pushes do not start duplicate runs. New development pushes and PR updates cancel superseded runs.
Dev checks ARM64 only when build or deployment files change. Missing comparison history retains ARM64 coverage.
Main checks amd64, arm64, 386, ARMv7, and PPC64LE before promotion and after merge.
Rpi checks native ARM64. Tagged releases retain application CI and test the exact ARM64 image before publishing it.
The release does not repeat the general container matrix. Deployment verification and rollback remain required.
The final CI gate accepts skipped container jobs only when the policy explicitly selects no architectures.
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
Release `rpi-v0.1.1` includes the deployed Telegram connection checks and browser onboarding.
GitHub initially rejected branch protection while the repository was private because the account required an upgrade.
The disposable Docker rehearsal passed first installation, replacement, intentional readiness failure, and automatic rollback on the Pi.
Both the original and restored SQLite records survived.
CI passed on `main` and `rpi` with Python 3.12 and 3.13, native amd64 and arm64 containers, workflow validation, browser checks, and secret scanning.
Release `rpi-v0.1.1` is deployed and healthy on the Pi with package version `0.1.1` and database schema 9.
On 2026-10-10, the operator requested promotion of `dev` to `rpi` and deployment through a new release tag.
The `rpi-v0.1.1` workflow succeeded and the Pi manifest confirmed the active release. The previous release and backup remain available.
The operator requested PR #8's setup guidance on both `main` and `rpi`, followed by a new Pi release.
Release `rpi-v0.1.2` deployed successfully on 2026-10-10 through workflow 38052880400. The Pi manifest confirmed version `0.1.2`, readiness, and the setup guidance. PR #9 promoted `dev` to `main`, and PR #10 promoted it to `rpi`, both through merge commits.
The operator requested PR #11's Telegram formatting and punctuation fix on `dev`, `main`, and `rpi`, followed by a new release tag.
Release `rpi-v0.1.3` deployed successfully on 2026-10-10 through workflow 38057843139. The Pi manifest confirmed the release and healthy container.
The operator authorized merging ZDR promotion PRs #15 and #16 with merge commits after CI, followed by a new Pi release.
Prepare package version `0.1.4` and tag `rpi-v0.1.4` through the normal topic-branch and promotion PR workflow. Deployment remains unconfirmed until release CI and the Pi manifest confirm success.
The running container uses `owner` and the HTTPS Google callbacks. Readiness and browser-token authentication passed.
The GHCR image denies anonymous pulls. The first registry upload failed with `unknown blob`; retrying publication succeeded before any deployment change.
The Cloudflare tunnel routes all paths on `theos.parth-shastri.com` to `http://localhost:8080`. Its proxied CNAME targets tunnel `4584e314-7c3f-448a-8118-7b6e324ebe3c`. Public HTTPS checks passed for the homepage and its assets, health endpoints, authenticated owner APIs, rejection of anonymous API requests, and both Google callback routes. A real model turn completed through the public SSE stream, and its conversation history was saved. The operator updated the Google redirect list. Full Google consent and account linking remain untested. The existing `mytheos.parth-shastri.com` frontend uses its original Vercel CNAME. On the operator Mac, Tailscale's internal DNS lookup retained a stale nonexistent-domain response despite correct public DNS answers. Refreshing `accept-dns` off and back to its original enabled setting restored normal macOS resolution. The Theos browser workspace then loaded, owner sign-in succeeded, and a browser-submitted real model turn returned `BROWSER_OK` in Brave.
See [Git and releases](docs/releases.md).

## Mac mini sandbox storage

On 2026-10-11, the operator requested the sandbox setup on the external SSD.
The active configuration, SQLite database, and server logs now use `/Volumes/extssd/opensandbox`.
The migration preserved both earlier setups in `backups/20261011T060145Z` under that directory.
The launch agent now pins OpenSandbox server `1.1.1` and uses the SSD configuration.
Its working directory and console logs remain under the user's home directory.
macOS denied launchd access to console logs on the removable volume.
Docker Desktop already stores its data under `/Volumes/extssd/docker/DockerDesktop`.
Both configured runtime images are downloaded.

A direct SDK check from the Pi passed creation, interpreter readiness, Python execution, file retrieval, and destruction.
The check returned `4` and read `sandbox-check` in 8.03 seconds before cleanup.
It explicitly used `/opt/code-interpreter/code-interpreter.sh` as the entrypoint.
Theos now supplies that entrypoint when creating a sandbox.
A patched application client check from the Pi passed execution, file retrieval, reconnection, and destruction in 10.57 seconds.
The regression checks cover direct and server-proxy creation without recreating saved sandboxes.
A separate range execution also reached its 60-second deadline after readiness.
These checks do not confirm Telegram execution, browser automation, or file delivery.

## Beta chat reset

On 2026-10-11, the operator authorized a fresh beta reset of chats, pending chat actions, and traces.
Keep account setup, connected credentials, enrollment, preferences, files, and usage accounting.
Preserve the Telegram offset so a restart does not replay old updates.
This is a one-time reset, not a retention policy for SQLite events.

## Pi Jaeger access

On 2026-10-11, the operator requested private Pi Jaeger access through Tailscale Serve.
The viewer URL is `https://neuralbox-pi.tail61f0ca.ts.net:8443/`.
Tailscale Serve proxies `http://127.0.0.1:16686` and persists across restarts.
The tailnet policy restricts Pi TCP 8443 to `group:theos-operators`, currently `parth-shastri@github`.
The former wildcard grant now excludes the Pi. Separate grants retain other Pi TCP ports, UDP, and ICMP.
The existing SSH policy and node attributes remain unchanged. This endpoint has no public Funnel configuration.
Seven saved policy tests cover operator access, nonoperator rejection, both IP families, and other service access.
Mac HTTPS checks passed with certificate validation. The viewer displayed an existing four-span Pi trace.
No nonoperator device was available for a live denial check. The saved policy tests validate denial.
Keep the policy snapshot and runbook together in the same change.
See [observability](docs/base-infra/observability.md#pi-viewer-through-tailscale-serve) and [policy snapshot](config/tailscale/pi-jaeger.policy.json).

## Research response fix

The research response fix replaces interrupted drafts in Telegram, browser chat, and terminal conversation views.
Stored history retains the originals with a superseded display flag.
Connected terminals use protocol version 2 for explicit answer replacement.
Update the deployment and terminal client together when releasing this change.
This branch does not deploy or publish a release.

## Explicit research workspace

PR #42 adds explicit deep research on the existing fix branch.
Migration 010 stores research runs, evidence, notes, and full checkpoints in the existing SQLite database.
Docker retains these records in its persistent data volume. The browser Research view reads account-owned conversation records.
Normal queries receive focused delegate briefs and protected summary capacity for final responses.
Only explicit research receives the durable research tools and structured reference checks.
Exa's contents API reads extracted source text without an application excerpt limit.
The shared call ceiling stays unchanged. Final responses hold summary capacity within the existing summary allowance.
See [research behavior](docs/runtime/deep-research.md) and [call budgets](docs/runtime/call-budgets.md).

## Release 0.1.9 preparation

On 2026-10-11, the operator requested all open PRs on `dev`, `main`, and `rpi`, followed by one Pi release tag.
Release 0.1.9 combines private Jaeger access, complete research responses, explicit deep research, and shared Pi skills.
The Pi already has the required shared skill paths and no explicit context or call-count overrides.
That release retained provider context capacity and proportional call allowances. The later Pi configuration update sets an explicit context cap, increased to 100,000 tokens on 2026-10-12.
Keep local development credentials unchanged.
Release `rpi-v0.1.9` deployed successfully through workflow `38144121306` after the skill mount correction below.

The 0.1.9 main promotion exposed a CI race in the sibling-recovery test's 0.3-second setup deadline.
The test now advances isolated runtime clocks after one delegate completes, while preserving the event loop clock.
It still checks the expired parent deadline, retained sibling answer, partial delegate, and single tool-free final response.
This test-only correction changes no production limits or environment settings.

## Release backup and shared skills

The first 0.1.9 deployment rolled back before candidate activation.
The Telegram preflight created an empty `/data/skills` mount directory in the candidate data volume.
The backup restore correctly refused that nonempty volume.
Mount shared skills at `/skills`, outside the application data volume, and set `AGENT_SKILLS_DIR=/skills`.
A disposable rehearsal confirmed an empty candidate volume and successful restoration of the saved backup.
The operator requested one tag. Retain the failed attempt and its backup, then retry the same immutable image and tag.
Do not move or create another tag. Keep `rpi` unchanged while the release workflow runs.

The second workflow attempt deployed the unchanged 0.1.9 image and published the GitHub release.
The active manifest confirms tag `rpi-v0.1.9` and revision `6af0d911f4eef59cfa05f4911b345fe32d8130db`.
Post-deployment checks passed package version 0.1.9, schema 10, SQLite integrity, browser authentication, and a live model response.
Telegram authentication, public readiness, private Jaeger access, and all eight skills also passed.
The host skill mount at `/skills` is read-only. The installed terminal client now reports version 0.1.9.
The failed candidate volume, attempt records, private configuration, and original backup remain available.
This retry used the operator's explicit one-tag request. No published tag moved, and no additional tag was created.

## Pi configuration and failure replies

The 2026-10-11 update defaults output to 8,192 tokens and the compaction trigger to 70 percent.
On 2026-10-12, the operator increased the private local Pi context cap from 64,000 to 100,000 tokens.
The 70 percent trigger starts compaction at 70,000 input tokens. The output limit remains 8,192 tokens.
Provider failures produce a persona-based explanation with the provider name and safe error category, including HTTP status when available.
Provider timeouts remain separate from Theos research deadlines. Failed generations do not publish text deltas.
No error path assembles raw tool results into a partial answer. Saved evidence remains in the transcript.
Browser and Telegram approval reviews use labeled fields, multiline prose, and literal code. Exact snapshots still control approval.
Deployment of this update remains unconfirmed.

## Release 0.1.10 preparation

On 2026-10-12, the operator requested release preparation before the development PR and both promotion PRs.
Prepare package version 0.1.10 with the Pi context, output, provider-error, and approval-review changes.
Merge the topic branch into `dev`, then promote `dev` into `main` and `rpi` through separate PRs.
Use merge commits for both promotions. Wait for their required CI checks before merging.
Set the private Pi environment to 100,000 context tokens, a 0.7 compaction ratio, and 8,192 output tokens.
Preserve all other Pi settings and retain a private backup before changing the environment.
After both promotions, tag the current `rpi` revision as `rpi-v0.1.10` to start deployment.
The release workflow creates the GitHub release after successful Pi activation.
Deployment remains unconfirmed until the workflow and active Pi manifest agree.

## Unified compression and workspace policy, 2026-10-12

This decision replaces the earlier local chunked-summary and bounded-request prototypes.
Use one pinned compression policy with a cheap auxiliary summary model, protected head and tail, tool pruning, and scaled budgets.
Keep Theos call allocations and research deadlines disabled. Retain their configuration and explanatory comments.
Remove the separate chunk compressor, tokenizer preview policy, and fixed repeated-retrieval cutoff.
Use provider usage for matching prefixes and the upstream rough estimator for added content.

Wrap Gmail and Health read tools at the runtime boundary. Do not change their connector implementations or MCP tools.
Save complete raw responses in R2 and return readable pages with source IDs.
Use the sandbox as a normal task workspace whenever computation or files help.
Keep task files under `/workspace`. Save nested files, versions, progress, and model checkpoints in R2.
Preserve newer live workspace files when reconnecting. Restore missing files when the sandbox is replaced.
SQLite remains the local journal and transfer index. Pending R2 uploads retry without repeating tools.

The live replay of the captured Pi failure produced all nine expected purchases and correct separate currency totals.
The live workspace check saved nested input/output files in R2 and calculated the expected total.
See `docs/runtime/acceptance.md` for the current test evidence and remaining limits.
These changes remain in the topic worktree and are not deployed to the Pi.

## Text summaries on the recovery branch, 2026-10-13

The operator requested integration on `fix/context-overflow-recovery` and removal of the separate structured-summary branch.
Use the pinned Markdown summary template for fresh and iterative summaries. Do not request or parse generated JSON summaries.
Replace model-written mechanical sections with original transcript data.
Keep exact anchors, saved research IDs, and unknown tool outcomes in `ContextMemory.state.references`.
Bound the request index while retaining the full index and transcript in storage.
Save parent working memory in SQLite before the next answer request. Child summaries cannot replace that session.
Keep Theos call budgets and research deadlines disabled by default. Summary calls retain usage accounting.
Retain lean tails as the recovery default. Allow `current` tails and one through twenty recent user messages.
The new implementation replaces the older JSON summary compressor. It does not add another compression pipeline or runtime dependency.


## Full request fit and readable activity, 2026-10-14

Keep this work on `fix/context-overflow-recovery` and PR #55.
After summary generation, cut and check the full request until input plus reserved output fits.
Use the same fit loop after failed or oversized summaries. Do not impose a fixed cut or provider-overflow retry count.
A recovery request must reduce estimated tokens, or serialized bytes when token estimates stay equal.
Retain current instructions, active user steering, pending tool batches, and tool validation contracts.
Keep complete call/result groups. Preserve full transcripts, saved sources, reference indexes, and uncertain outcomes.
Publish fitted memory through the existing checkpoint transaction. Never retry an identical request or repeat completed tools.
Required content can still exceed a provider window. Report that limit without fabricating a successful answer.

Emit scoped compaction events without private summary prose. Show them in browser chat and Telegram.
Show one editable Telegram activity per tool call with an emoji and readable action name.
Group approval fields by item, use short labels, and place exact request details in expandable disclosures.
Retain the immutable approval snapshot and complete large reviews.
Zepto cart price and maximum retail price use paise. Display `3900` as `₹39.00` and retain raw values in exact details.
Apply this conversion only to known cart price fields. Tool arguments and approval checks remain unchanged.
These changes add no runtime dependency and remain undeployed until the release process runs.


## Live fit replay and release 0.1.11 preparation, 2026-10-14

The operator authorized live replay, integration into `dev`, promotion PRs for `main` and `rpi`, and a new Pi release tag.
The stricter normal replay passed all 21 checks. Four injected context rejections passed all 23 checks with live model continuation.
Both recovered nine original purchases with separate currency totals and retained the original transcript.
The overflow run completed five compactions without a failed event. It needed no auxiliary summary call.
The initial normal run reused older summary facts, so the repeated normal run explicitly required original receipt reads before totals.
Replay evidence checks accept both supported history selectors. Seven deterministic checks protect that validation contract.

Prepare package version 0.1.11 and tag `rpi-v0.1.11`. Preserve immutable older tags.
No new private environment setting is required. Keep the existing local Pi context, output, and trigger values.
All related remote topic branches already belong to `dev`, except `fix/context-overflow-recovery` and its current PR #55.
Promote through separate PRs and merge commits. Confirm the tagged pipeline before claiming deployment.


## Pi promotion timeout-test correction, 2026-10-14

Pi promotion CI exposed a race in the bounded write-timeout test on Python 3.12.
The 150-millisecond deadline could expire during setup, before the write started. That outcome correctly has failed status.
The test now advances only application deadline clocks after the write starts and gives the tool a separate 50-millisecond timeout.
Keep the event loop clock real. Preserve unknown outcomes for started writes and never repeat them.
This correction changes test timing only. Production runtime behavior and the successful live replay remain unchanged.
Integrate it through a topic PR into `dev` before the Pi promotion and release tag.
