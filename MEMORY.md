# Theos project memory

Updated: 2026-10-27.

## Release 1.4.2 preparation, 2026-10-27

The operator requested both workspace tools and Telegram connector controls from PR #112 on `main` and `rpi`.
Increment the last version component from 1.4.1 to 1.4.2. Keep the other account connector PRs outside this release.
Use topic PRs into `dev`, followed by separate promotion PRs with merge commits.
Publish immutable tag `rpi-v1.4.2` at the current promoted `rpi` tip.
Confirm the tagged workflow and active Pi manifest before reporting deployment.

## Pi deployment helper recovery, 2026-10-27

The 1.4.2 backup exceeded the deployment script's five-minute command timeout after writing more than 2 GiB.
Docker left the helper running with the old volume's process lock, so automatic rollback failed.
Stopping that helper allowed both 1.4.1 services to recover. API and frontend readiness returned HTTP 200.
The failed tag remains unchanged. Prepare urgent fix 1.4.3 from `rpi`, then copy it through a topic PR from `dev`.
Give backup and restore helpers separate bounded deadlines. Always remove their named containers before rollback.
Journal recovery removes helpers that survived an abrupt runner crash before reopening the previous database.
The native Mac mini guard resets unreadable recovery state and flushes each new journal before replacement.
Retain both data volumes and backup files. Extend the deployment job deadline to include backup, restore, and rollback.

## Mac mini power recovery, 2026-10-27

The operator requested automatic recovery after power loss and authorized Docker Desktop restarts.
The Mac mini already enables power restoration and automatic login. FileVault is off. Do not change these security settings.
Install the native host guard at login. Wait for the external SSD before starting Docker Desktop.
Check engine writes with a disposable stopped container. Repeated failures permit bounded Docker Desktop restarts.
Restore stopped memory and voice containers without replacing their images or volumes. Existing native services retain launchd keepalive.
Do not prune Docker data or recreate missing service containers automatically.
Docker Desktop still requires a macOS login. A future login or disk-encryption change can require an operator after reboot.

## Confirmed decisions

| Decision | Value |
| --- | --- |
| Composer Return key | At mobile widths up to 700px, Return inserts a new line, including while command or connection suggestions are open. Use the send button to submit. Set the keyboard hint and accessible instructions to match. Desktop Enter still sends and Shift + Enter inserts a new line |
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
| Telegram setup guidance | After name and timezone setup, offer buttons for configured, unconnected accounts and Skip for now. Keep Google Health optional. Share the owner-scoped completion marker with browser onboarding. Preserve saved names. Keep web access and /help available |
| Telegram connector controls | Use native sign-in URL buttons, status checks, retry, cancel, and account navigation. Zepto uses a Paste return link button and an owner-scoped ForceReply prompt. Encrypt prompt replies before inbox storage and consume them outside model history. Preserve existing credentials on setup cancellation. Keep the manual localhost handoff and support /connections after onboarding |
| Telegram temporary activity | Stream OpenAI Responses reasoning summaries as temporary messages. Never show raw provider reasoning. Show each tool name and its exact JSON arguments in temporary tool messages, then delete the message when that model phase or tool call ends. Clean active indicators when delivery ends. Send one final message with elapsed time, tool counts, failed or uncertain outcomes, and successfully loaded skills. Count parent and delegate events before display queues can discard them. Approval cards notify once and remain pending until a decision or expiry. Store review message references in SQLite migration 012, including multipart reviews, attached reviews, and waiting notices. Remove resolved cards immediately for Telegram decisions and through polling for other decisions or expiry. Failed deletion removes buttons when possible and retains references for another attempt. Preserve durable approval snapshots, tool results, transcripts, and recovery behavior |
| Reply formatting | Render assistant Markdown as Telegram text and explicit UTF-16 entities. Split long messages without losing text or formatting. Keep command responses literal. Show approval reviews as labeled fields, formatted prose, and literal code. Preserve exact arguments for approval checks. Browser and terminal retain their own Markdown rendering |
| Assistant punctuation | Never use em dashes in assistant replies, reasoning summaries, or generated titles. Add shared model instructions and replace any emitted em dash with an ASCII hyphen before display and persistence. Preserve user input, tool arguments, and opaque provider data |
| Telegram access code | Optional `AGENT_TELEGRAM_ACCESS_CODE` in private `.env`; SQL authorization replaces manual sender enrollment |
| Telegram enrollment limit | 50 unique senders per database, including incomplete setup. Operators can lower the limit |
| Browser framework and deployment | Next.js App Router and React components under `web/`. Preserve existing CSS, assets, glass effects, native interactions, and responsive layouts. Run Next.js separately from FastAPI. The `web` Compose service owns the public origin and forwards requests to the private `theos` API service. Release and roll back both immutable images together |
| Browser authentication | Preserve Telegram confirmation and private access-token identities. Both browser sign-ins use opaque HttpOnly sessions. Never retain access tokens in browser storage. Hash session credentials in SQLite. Enforce seven-day absolute and twelve-hour idle expiry, logout revocation, configured token rotation, CSRF checks, and persistent login throttling. HTTPS sessions use `__Host-` cookies. Keep the frontend service credential server-only. Terminal clients retain bearer access to the private API |
| Browser style | Retain the existing green palette and light/dark theme colors. Start the green background tint along the full bottom edge in both themes. Keep the top-corner tint minimal and reduce dark-mode tint strength. Avoid bright light pools. Keep panes transparent enough to show blurred content underneath. Use moving edge highlights, pointer light, and shadows on the sidebar, dialogs, and menus. Use cached SVG rim displacement in Chromium, with CSS blur and edge highlights as the fallback. Keep controls above a separate optical layer. Scroll dialog content inside the fixed pane. Use simple child-control fills instead of stacked glass. Keep the floating composer subtle and allow content to scroll behind it. Preserve solid fallbacks and reduced-motion and reduced-transparency preferences |
| Mobile keyboard layout | The shared application frame follows visual viewport height and vertical offset on resize and scroll. Keep navigation and the composer inside that frame. Bound top-layer dialogs separately. Remove keyboard-time bottom safe-area padding, clamp stale offsets on dismissal, and preserve native pinch zoom. Keep viewport ownership outside conversation state |
| Browser navigation arrows | Use the shared SVG northeast arrow for sidebar navigation and sign-in actions. Inherit the text color and keep icons decorative. Avoid Unicode arrows that iOS renders as emoji |
| Browser usage and tools | Owner and conversation USD estimates. Administrator totals and cost breakdowns include all transports. Missing prices stay visible. Collapsed reasoning summaries and tool calls. Searchable conversation tool registry with approval labels |
| Usage view access | Every browser user has personal Activity & usage through their token. Administrators have a separate Admin dashboard for all users and transports. Personal charts always use the authenticated owner, including administrator tokens. Administrator responses exclude conversation titles and message content |
| Enrollment roles | The deployment operator uses an explicitly configured administrator account in `AGENT_USERS` and `AGENT_ADMINS`. First registration never grants administrator access. New Telegram enrollments receive ordinary access. With `AGENT_WEB_URL` configured, completed users receive a browser link and confirm a matching code in Telegram. Generated browser credentials reuse their stable Telegram owner and never grant administrator access |
| Browser enrollment credentials | SQLite stores hashes of single-use 10-minute invitations, browser pairing secrets, personal tokens, and seven-day device sessions. Confirmed sign-in issues an HttpOnly, SameSite Strict session cookie and shows a personal token once. New sign-in replaces the saved token while retaining other device sessions. `/web revoke` removes all generated browser access without deleting personal data. Preserve configured browser IDs and do not merge accounts by name |
| User-owned encryption requirement | Deferred: the user requested completion of onboarding without choosing an encryption mechanism. Private content storage, password wrapping, and automatic key access remain proposals. Current personal content is not encrypted. Keep the existing encrypted service credentials and content-free usage views. Hosted processing can expose plaintext to the running server |
| Encrypted history continuity | Restore saved history automatically while a decryption grant is active. The user requested transparent access across turns. Password-based key wrapping and automatic key-service access remain proposals. Losing a runtime grant must not erase encrypted history. See `docs/architecture/theos-encryption-proposal.excalidraw` for the proposed boundary |
| Browser model controls | Keep the current model selector. OpenRouter exposes the six requested aliases plus the existing default. Preserve explicit operator allowlists. Save supported generation parameters in SQLite migration 006. Model-specific cost rates can override shared rates |
| Browser settings and command panels | Move model and reasoning into Settings, opened from the desktop header or mobile sidebar with generation and voice controls. Save changes together and discard canceled drafts. Use a sidebar icon beside the logo to toggle conversations. Show interactive help and usage dialogs. Keep usage access through `/usage`, without a sidebar Usage button. Keep generation controls in Settings, without `/generation`. Offer supported options for argument commands. List only `/reasoning`, with `/thinking` retained as a compatibility alias |
| Browser commands and voice | Slash command help and keyboard suggestions. Record microphone audio for editable transcription. Optional TTS reply playback through the existing configured voice services |
| Browser identity and thinking | Copy the mini-theos logo into owned browser assets. Animate active thinking and respect reduced motion |
| Browser voice controls | Use accessible microphone, recording stop, and speaker icons. Keep TTS playback in one play/stop button, cache audio for replay, and stop it on conversation changes. Use the mini-theos glow during thinking and the theme accent during recording. Smooth microphone RMS volume into the composer glow and three animated waves along the bottom edge. Modulate wave height and opacity with speech volume. Stop the waves and clear both meters on stop, cancellation, errors, or page exit. Reduced motion keeps static recording feedback |
| Browser glass edges and modes | Keep moving edge highlights fine and localized. Use a 0.75px highlight mask with soft permanent borders, without stacked bright rims. Keep 4px between dropdown option rows and draw keyboard focus inside each row to separate it from the current selection. Model and reasoning use bounded glass popovers with native values and a native-menu fallback. Open the message-mode listbox upward with a short spring animation. Show conversation and search icons beside Normal and Deep research. Preserve keyboard navigation and one-message mode scope |
| Browser Markdown and composer | Render streamed and saved thinking and replies with pinned, locally served Marked 18.1.0 and DOMPurify 3.4.16. Show raw HTML as text, block unsafe links, and show remote images as links. Preserve raw Markdown for token estimates. Copy code without toolbar labels and send rendered plain text to TTS. Start the composer at one line and grow it to 140px. Inset native dropdown chevrons by 14px |
| Browser composer feedback | Remove the private-workspace badge and dot. Keep errors and voice feedback inside the composer. Show run activity in the conversation and tool states in their tool events. Show Listening... and Transcribing... in the empty input; keep voice feedback inside the composer when a draft exists. Add no transcription-ready or cancellation note. Rotate playful idle prompts every eight seconds while the empty input is unfocused and visible. At widths up to 700px, use exaggerated philosophical prompts in three short words, and update them when the viewport changes. Focus shows Start Typing... and never changes the draft. Light-theme user bubbles use the send-button green with white text; preserve dark-theme bubbles |
| Dashboard charts | Use native SVG and HTML charts for daily model requests, recorded USD cost, input/output tokens by model, and main-agent tool starts. Offer 7, 30, and 90 day UTC ranges. Aggregate complete records across transports behind administrator access. Preserve missing prices, zero-fill inactive dates, and provide hover/tap details and chart data tables |
| Browser workspace panels | Use the shared glass material for the top navigation, usage cards, account cards, and workspace services. Keep lifetime totals distinct from period charts. Use the glass range picker, exact data disclosures, direct ranking values, and keyboard-selectable days. Preserve price gaps and owner boundaries. Keep the themed logo and a sticky return-to-chat action in both usage views. Desktop panes tint on hover only. Preserve mobile touch feedback. Release optical filters when refreshed panes leave the page |
| Browser interface case | Use sentence case for interface headings, labels, role names, badges, and command argument hints. Do not apply uppercase text transforms. Preserve user and model text, model identifiers, and standard technical abbreviations |
| Browser UX and appearance | Align messages and the composer at a shared gutter. On mobile and desktop, start with one frosted input row, a plus button on the left, and microphone and send buttons on the right. Focus or a draft expands the composer into a text row above controls and message mode. The plus menu offers attachments, commands, and conversation settings. Remove the idle readiness note and its space. Show run progress in the conversation. Keep recording feedback and errors in the composer. Grow drafts to 140px, preserve reading position during streams, and fit the visual viewport without changing pinch zoom. Use a sliding mobile drawer with keyboard focus handling, safe-area spacing, and dismissal after navigation. Keep the existing theme-specific logos. Hide the mobile conversation toolbar. In light mode, place the sidebar trigger on a glass navigation strip. Dark mode keeps the standalone trigger. Put the Theos name, theme switch, Settings, and conversation actions in the mobile sidebar. Preserve the desktop header and toolbar. Use fixed 44px composer controls with an 8px gap between microphone and send |
| Browser message statistics | Show estimated output tokens and elapsed time during each model generation. Use final provider usage when available. Save UTC message timestamps and generation duration in application history metadata. Show local dates with the year, as `6 Oct 2026 14:32`. Preserve unknown dates for older messages. Keep display metadata out of provider and generic harness serialization |
| OpenRouter accounting | Keep its adapter in the application runtime. Retain readable reasoning, replay signed blocks only for the same model, and prefer reported request costs over token-rate estimates |
| OpenRouter retention | Enforce `provider.zdr=true` in the application adapter for every OpenRouter request, including chat, delegates, compaction, and titles. Preserve other provider preferences. No request can disable ZDR. External Mem0 and voice services keep separate policies |
| OpenRouter reasoning routing | For OpenAI models, replay encrypted reasoning from only the latest known provider format in each wire request. Omit incompatible sequences without changing saved messages or signed blocks. Recover a mixed-provider HTTP 400 once before generation, with the same restrictions as the ZDR routing retry. If OpenRouter rejects encrypted OpenAI reasoning with a ZDR routing 404 before generation, retry once without those reasoning sequences. Preserve messages, tool exchanges, model options, saved history, and ZDR. Do not retry unrelated errors, Claude signatures, or streams that emitted events. A retry is a transport attempt within the same harness model call |
| Query latency traces | When enabled, turn spans record total duration and first/last response text chunk times. They also record first model-call and reasoning times. Model spans record per-call first/last text chunk and response-complete times |
| Browser conversation titles | Generate from the first completed exchange with the selected model and refine once after three user messages. Bound title calls, include their usage in costs, preserve custom titles, and retain a fallback on failure. Migration 007 tracks automatic titles |
| Configuration | Pydantic settings with the `AGENT_` prefix |
| Deployment | One application worker and scheduler per SQLite database |
| Tracing | Optional runtime-owned OTel SDK with OTLP/HTTP protobuf export. One root trace per turn. All spans share the existing conversation ID and a separate turn ID. Model and tool spans nest under the turn, with separate parallel research delegates. Export metadata by default. Optional bounded content capture includes model messages, tool arguments/results, and delegate tasks/results. Use OTel GenAI roles, parts, and descriptive agent names inherited by child spans. Retain legacy string delegate tasks. Theos chooses descriptive agent names from task scope without user-supplied names. Delegate substantial independent research when useful, and handle simple or dependent lookups directly. Instruct research delegates to use at most two focused search calls with three results each, then return findings and unverified facts. These search limits are guidance. After delegation, instruct the parent to use findings and caveats, with at most two focused verification searches before answering. Retain call usage accounting and the 90-second tool timeout. Capture limits default to 8,192 UTF-8 JSON bytes per field and 32,768 per span. Exclude reasoning, binary payloads, provider state, and exception payloads. Keep SQLite events and usage. Use optional Jaeger v2 with single-node Badger storage for waterfalls |
| Trace access | The optional Jaeger viewer and OTLP receiver bind to host loopback. The Pi uses persistent Tailscale Serve on HTTPS port 8443 to proxy the viewer. Restrict Pi TCP 8443 to `group:theos-operators` in the tailnet policy. Exclude this endpoint from broader grants across both IP families. The group currently contains `parth-shastri@github`. Keep Funnel disabled for this endpoint. Jaeger has no configured password or per-user trace isolation. Theos authentication does not protect it. Operators can also use local access or authenticated SSH tunnels. Anyone with Jaeger access can inspect all stored traces. Per-user trace access requires a separate ownership-checking layer and is not implemented |
| Diagnostic retention | Keep SQLite events and usage unchanged. Rotate application logs by size and age, and bound Docker logs. Use seven-day Jaeger span expiry, a 512 MiB container limit, and memory pressure guards. Do not impose a 1 GB disk quota. Jaeger storage retains traces across restarts. Monitor disk growth separately |
| Turn recovery | Preserve the transcript and uncertain actions. Retry provider context rejection only with a smaller request, without repeating tools. An irreducible request remains a failure, never a fabricated successful answer |
| Checkpoint latency | Commit SQLite state and fsynced local objects before work proceeds. Use one background R2 worker with bounded batches, connection reuse, storage backoff, and a durable transfer journal. Publish remote recovery pointers only after their snapshots and sources are uploaded. Remote recovery can lag local recovery. Restart replication without repeating assistant tools |
| Parallel Gmail reads | Mark search, message, thread, draft-list, draft-read, and label-list tools safe for parallel execution. Preserve that declaration and view metadata through journal wrappers. Keep writes and approved sends ordered. Preserve each call ID, completed result, ownership check, and uncertain outcome |
| Provider diagnostics and retries | Separate HTTP response headers from first-chunk and full-generation timing. Retain validated request IDs, HTTP and provider status codes, known provider names, and allowlisted error classifications. Exclude raw error bodies and credentials. Retry transient accepted OpenRouter streams at most twice before any event, within the same model call. Start additional attempts only during the first 30 seconds. Do not retry partial output, invalid requests, authentication, quotas, or context errors through this path |
| Provider model fallback | OpenAI defaults to `gpt-5.6-luna`. OpenRouter defaults to `glm-5.3`, the highest tool-capable ZDR endpoint count in the 2026-10-15 OpenRouter snapshot. Map reasoning to a supported fallback effort. `AGENT_FALLBACK_MODEL` overrides the model or an empty value disables it. Other providers require an explicit compatible fallback. Use the same configured provider. Try once only when the primary provider failure occurs before any model event is forwarded. Do not fall back for known invalid-request, authentication, quota, policy, or context failures. Trace both model attempts separately with the primary failure classification and fallback model ID |
| OpenRouter performance routing | Use generic latency and throughput preferences for every OpenRouter model. Prefer p90 latency at most 15 seconds and p90 throughput at least 10 tokens per second. These are soft preferences. Supply no endpoint order or model-specific order map. Retain ZDR, eligible provider fallbacks, signed state, explicit request constraints, default reasoning, context limits, and retry bounds. Record fixed request controls and reported reasoning-token counts without private bodies |
| Pi Connect memory | Upgrade the host package to 2.13.0. Set its Go memory target to 192 MiB and check resident memory each minute. Restart only `rpi-connect.service` above 512 MiB. This is a service guard, not a hard kernel limit. Preserve SSH, Tailscale, Theos, and account isolation. Browser Connect access currently requires operator sign-in |
| Tool execution batches | Replace the hard 16-call response rejection with `ExecutionLimits.tool_batch_size`, default 16. Process every valid call in ordered batches. Only tools declared safe may overlap. Keep each call ID and approval check. Append each batch's results before the next batch. Tell the model to request at most 16 calls per response and provide explicit feedback after larger groups. Reject invalid arguments per call as `not_started` before approval or execution, with correction instructions and a new call ID. Keep `failed`, `denied`, and `unknown` outcomes distinct. Duplicate IDs and malformed response identities remain fatal before execution. Retain transcript and checkpoint guarantees. Record exact generated call counts in trace metadata and only fixed harness error codes in logs |
| Approval policy | Global approval prompts apply to Gmail draft sending and Zepto cart confirmation, checkout, order placement, and payment-related tools. Gmail approval binds the draft contents and checks them again immediately before sending. Search, read, draft creation, delivery-store setup, ordinary cart updates, all sandbox actions, deletion, and memory settings do not prompt. Keep owner isolation, validation, durable attempts, exact approval snapshots, and unknown-outcome recovery. Retire old pending cards for ungated tools without executing anything during cleanup |
| Sandbox creation lifetime | Default and Pi configuration are 3,600 seconds from creation. Cached and saved references retain their original deadlines. Activity cannot extend expiry. Check cached instances before use. Recreate only confirmed missing or expired instances. Preserve references on transient failures and never replay an operation automatically. Restore workspace checkpoints before saving a replacement instance. If lifecycle acquisition fails before an action starts, tell the model it may retry the same normal tool once; uncertain actions must not be repeated. Lifecycle controls stay internal; the model does not need them for routine recovery. Destroying an absent sandbox does not create one |
| Workspace retention | Theos file services own retention. Keep three recent checkpoints per session, current workspace and attachment sources, and current local and published remote pointers. Scan hourly with a one-hour grace period, bounded batches, and a durable deletion journal. Protect active sessions and pending recovery review. Retained snapshots pin their sources. Preserve research, uploaded-file catalog entries, browser state, transcripts, and generic harness behavior |
| Workspace tool names | Expose only `run_command(command?, timeout, inspect_images?)` and `attach_file(path)` for workspace work. Shell commands cover Python and file operations. Image-only calls can omit the command. Keep `history_read` and `history_search` separate. The runtime owns input staging, versioned session files, R2 replication, restoration, and immutable response attachments. Remove former catalog, transfer, Python-kernel, browser-wrapper, and image-view tools from new registries |
| Skill selection | Include installed skill descriptions in model context. Match task intent to descriptions and load relevant instructions before work without requiring skill names from the user. Do not load every skill or treat names as the whole selection policy. Supply report-style and document-format instructions automatically for document requests. New reports default to styled PDF. Explicit formats and existing document styles retain precedence. Count automatically supplied skills in turn stats. The shared sandbox image contains report-style files and the declared runtime dependencies for all eight skills; load other skill scripts and text resources from the host as needed |
| Model-call allowances | Theos disables call allocations and research deadlines by default through `Runtime(enforce_budgets=False)`. Preserve all budget fields and their validation for callers that explicitly enable bounded mode. Parent, delegate, summary, and recovery calls retain usage accounting without enforced call ceilings. Root traces mark enforcement false and limits as -1. Provider, context, output, tool, concurrency, approval, and cancellation limits remain active. See `docs/runtime/context-recovery.md` |
| Distribution | Self-hosted installations and an operator-hosted Telegram service |
| Health connection readiness | Verify the selected account through the stable v4 identity endpoint before saving new OAuth credentials. Use the existing Health scopes. Missing profiles need app setup or Fitbit migration. Preserve the previous account when verification fails. A linked profile does not guarantee synchronized readings |
| Google Health vitals | Import stable v4 daily HRV, SpO2, respiratory rate, and sleep skin temperature. Summarize available heart rate, HRV, SpO2, core temperature, glucose, and sleep breathing samples. Keep RMSSD and SDNN separate. Preserve units, missing values, and provider confidence bounds. Default summaries include vitals and coverage counts. Version caches and refresh older summaries on tool or Telegram reads. Send complete Telegram summaries through the existing message splitter |
| Google credential ownership | Each deployment operator supplies OAuth clients and an encryption key. Each browser or private Telegram user authorizes their own accounts |
| Browser account connections | Offer optional unconnected accounts at first setup. Ask for a preferred name only when missing. Reserve a disowned sign-in tab during Connect, then navigate it after discovery. Keep an explicit link for blocked popups. Successful callbacks return to Connections. Verify setup before closing callback tabs. Show cancellation, expiry, and retry states. Cancel setup preserves the prior account. Keep owner-bound consent and configured browser IDs outside reserved namespaces. Telegram-confirmed browser credentials reuse the enrolled Telegram owner. Do not merge separate browser and Telegram accounts |
| Connector visibility | List configured account connectors in Connections and mentions before owner authorization. Hide connectors without deployment credentials |
| Browser connection mentions | Show local provider logos for accounts and use-case SVG icons for all workspace services in Connections and `@` suggestions. Complete mentions at the composer caret with current account status and configured workspace services. Preserve draft text. Send mentions as ordinary user text without changing access or approval policy |
| Zepto account linking | Browser and private Telegram users authorize their own accounts through MCP OAuth. Theos encrypts credentials in SQLite. Use the localhost return handoff by default, with an optional public HTTPS callback |
| External memory | Separate Mem0 OSS REST service with explicit, owner-scoped tools. Use OpenRouter for Mem0 models. Mem0 Platform needs an adapter |
| Memory automation | Bounded private-chat retrieval when memory is enabled. Per-user explicit opt-in for future user-message consolidation through Mem0 inference |
| Scheduled agent tasks | Durable one-time and cron schedules run through the normal conversation runtime and approval policy. Interrupted or uncertain runs pause the schedule |
| Remote sandbox | Keep the Mac mini configuration, database, and server logs under `/Volumes/extssd/opensandbox`. Pin the native server to `1.1.1`. Use server proxy mode with `resolve_internal=false`. Keep launchd console logs under the user's Library because macOS blocks its removable-volume access. Docker storage remains on the SSD |
| Model context | Keep one rolling checkpoint in `src/harness/compaction.py`. Default to a 50% trigger and a 2.5% recent tail, both configurable. Use the conversation model for summaries unless `AGENT_COMPACTION_MODEL` selects another provider model. Summarize earlier history and a split turn separately. Include the covered original request in the checkpoint, then append only retained messages. Keep new unanswered user messages and unfinished tool batches verbatim. Preserve the full transcript. On provider overflow, retry with shorter summary tiers without replaying tools. `history_read` and `history_search` recover exact saved messages |
| Reply generation requirement | Main responses use the configured provider output limit, default 8,192. Do not clip generated answers. Summary calls use no tools and cap output at the configured tail ratio of the summary model's context. Explicit cancellation, provider timeouts, and output truncation remain distinct. Bounded callers retain research deadlines without cancelling an active answer |
| Explicit deep research | Start only through the browser mode or an explicit user command. Apply the mode to one turn. Normal questions receive focused delegate briefs and protected final response capacity. Deep research adds conversation-owned SQLite records, full source reading through Exa, structured notes, validated summary references, and the browser Research view. Retain original sources, notes, transcripts, reports, and summary checkpoints. Source references protect retrieval, not factual truth |
| Speech hosting | Separate services. Document Docker CPU, native Apple Silicon MLX/MPS, and hosted transcription. Generic hosted speech output needs an adapter or client changes |
| Final voice | Kokoro `am_michael(0.7)+bm_george(0.3)`, speed `0.9`, with the approved subtle robotic treatment in the separate `speech` gateway. Keep DSP dependencies out of the Pi application image. Authenticate gateway requests with `AGENT_KOKORO_KEY`. Existing environment overrides require an explicit rollout update. The louder audition is not the selected profile |
| Personality | Straightforward, commanding, self-assured, philosophical, and darkly witty, with deliberate cadence and restrained theatrical weight. Ordinary discouragement and procrastination receive firm, masculine encouragement and one achievable action. Challenge avoidance without insulting the user. Honor requested gentleness and treat serious distress with care. Describe these traits directly without naming a fictional character. Chat and speech preparation share one persona. Facts, source fidelity, requested tone, and urgency take precedence over style. Use original observations and verify attributed quotations. Keep research delegates and harness summaries factual. See `docs/personality.md` |
| Expressive TTS text | Every browser or tool synthesis request first uses one bounded, tool-free model call to write an expressive spoken rendition. Preserve facts, numbers, quotations, uncertainty, and action outcomes. Use words and punctuation rather than unsupported emotion tags. Retain display text and history. Record model usage under the owner and conversation. Fail preparation rather than silently reading plain source text |
| Code organization | Separate service directories with plain functions and small lifecycle classes |
| Shared Pi skills | Store operator-installed skills in `/home/neuron/.agents/skills`. Use skills.sh with a temporary Node 22 runtime. Theos mounts that same host directory read-only at `/skills` through `compose.skills.yaml`, `THEOS_SHARED_SKILLS_DIR`, and `AGENT_SKILLS_DIR`. Retain source licenses, installation metadata, file hashes, and local adaptations. Reapply report overrides after upstream updates |
| Shared sandbox runtime | Build the ARM64 image from `skills/sandbox-runtime/Dockerfile` on the Mac mini. Keep report scripts and style assets at `/opt/theos/report-style`. Install the locked PDF, DOCX, XLSX, OCR, browser, arXiv, and pinned Papers with Code dependencies in the image. Representative PDF, DOCX, XLSX, OCR, and browser checks passed under the existing one-CPU, 512 MiB sandbox limit |
| Paper research | Prefer the official `pwc-cli` skill from `huggingface/pwc-cli`. Use arXiv and Hugging Face skills as supplemental sources. Public catalog research needs no credentials. The shared sandbox image installs the CLI at the recorded source revision |
| Report appearance | New PDF and DOCX reports use the operator-supplied neutral `report-style`: Space Grotesk typography, green numbered headings, beige tables, dashed rules, yellow status badges, and consistent diagram colors. Bundle fonts in PDF and DOCX output and install them in the sandbox for chart labels and conversion. Code retains its monospace style. Explicit user styles take precedence. Preserve existing document styles during edits. Render and inspect every output page |
| Prompt organization | Store Theos prompts in Markdown Jinja templates under `src/theos/prompts`. Store harness production prompts under `src/harness/prompts`. Use plain `.md` filenames for normal Markdown previews. The shared package-aware renderer uses StrictUndefined and caches compiled templates without request data. Python resolves capabilities and external data. Templates compose text with conditionals and includes. Version templates with code and deploy them through normal releases |
| Compaction prompt ownership | The harness owns the exact production compaction prompts, including shared, initial, update, split-turn, and shortening instructions. Start the shared system prompt with an explicit context summarization assistant role, then state its task and constraints. Theos uses those defaults and can override individual prompts through `CompactionConfig`. Optional Theos override files live under `src/theos/prompts/compaction`. Omitted overrides use the corresponding harness production prompt. Theos currently ships no overrides. The harness owns prompt selection and the compaction algorithm. See `docs/runtime/prompts.md` for filenames and fields |
| Comments | Explain constraints and number the major workflow steps. Use nearby ASCII diagrams for message order and complex flows |
| Tests | Keep cases for distinct observable behavior, meaningful input boundaries, and important regressions. Consolidate related request and response assertions into contract tests. Remove constructor-only checks, framework introspection, and repeated examples of the same branch. Expand parameter matrices only when their interactions matter. Retain approvals, owner isolation, uncertain-action recovery, persistence, compaction, and supported provider contracts. See `docs/runtime/testing.md` |
| Documentation | Task-based Markdown guides, Simplified Technical English, and existing Excalidraw PNG diagrams |

Application and deployment environment variables use the `AGENT_` prefix.
The configured name supplies model instructions, browser labels, and Telegram greetings.
The package name, storage paths, and existing deployment resource names remain stable.

The user requested removal of unrelated starter examples and historical planning documents.
The required mock API fixture now lives under `tests/fixtures`.
Keep harness tests, provenance manifests, and editable architecture sources.
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

On 2026-10-17, the operator authorized merging PR #82, updating local `.env` and `.env.pi`, and publishing version `1.2.0`.
Prepare the version on a topic branch from `dev`, merge through a PR, and promote `dev` to `rpi` through a merge-commit PR.
Use the immutable tag `rpi-v1.2.0`. The `main` promotion is independent and was not requested.
Both local environment files and the Pi deployment environment now select the Michael/George blend, speed `0.9`, and the authenticated Mac mini gateway on port `8881`.
Preserve their unrelated settings and mode `0600`. Private `.before-1.2.0` backups retain prior values.
The native gateway source lives at `/Volumes/extssd/voice/theos-speech`, with launch agent `com.parthshastri.theos-speech`.
macOS blocked launchd from opening its Python entry script on the external SSD. Install its runtime and private environment under `~/.local/share/theos-speech`. Keep Kokoro and model storage on the SSD.
Keep its console logs under the user's `Library/Logs/Theos` directory.
Deployment remains unconfirmed until the release workflow and Pi manifest confirm activation.

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

## Checkpoint latency, provider diagnostics, and Pi memory, 2026-10-14

The operator requested latency fixes, safe parallel Gmail reads, provider diagnostics, and a Pi Connect memory correction.
The isolated Pi preflight used synthetic data, a temporary database, and the existing configured storage and model services.
Five local checkpoints took 16.9 to 17.7 milliseconds each. Background replication completed in 4.11 seconds.
All six synthetic remote objects were removed and the probe prefix was empty afterward.
A live model request with no tools returned the expected marker in 12.10 seconds.
The probe changed no production conversation records and sent no Telegram messages.

The old provider failure occurred after an accepted Azure stream and remains unclassified beyond its 502 code.
Its detailed payload was discarded. Provider-side disconnection, timeout, and overload are not established causes.
New diagnostics keep safe classifications and identifiers for later failures.
They cannot guarantee provider availability or recreate missing historical evidence.

The Pi Connect restart restored more than 7 GiB of available memory.
Package 2.13.0 and the service memory guard are installed. Connect resident memory was about 18 MiB afterward.
The guard checks each minute and restarts only Connect above 512 MiB.
Theos was about 55 MiB resident after host memory pressure ended.
Connect currently requires operator sign-in. SSH and Tailscale remain available.
The application changes still require the branch promotion and tagged release gates.

## Remote snapshot reconciliation, 2026-10-14

A remote checkpoint can predate external actions, including actions without captured call intents.
Remote restore resolves captured unanswered calls from saved results or records them as uncertain.
It also saves a separate owner-bound review marker that compaction cannot remove.
Restored conversations expose no tools until the operator checks and reconciles external effects.
The approval boundary also denies execution if a caller bypasses the empty tool registry.
Operator recovery code clears the marker through `confirm_restore_review` after reconciliation.
This method is not an agent tool and rejects confirmation while the session is running.
Local process recovery retains its existing journal behavior and does not create this review marker.

## Provider latency and endpoint preference, 2026-10-14

The operator requested the cause and correction for 143–379-second model calls.
Provider records show one successful Azure endpoint generation per slow call.
The calls used 20,575 and 40,952 input tokens, with 199 and 808 reasoning tokens.
Pi requested default reasoning, currently medium in the catalog, with an 8,192-token output allowance.
Default service tier and large cache hits exclude flex routing and excessive uncached context as complete explanations.

The responsive synthetic probe used 51,079 input tokens and medium effort. It completed in 2.96 seconds.
The same cached request forced to base Azure took 38.46 seconds and returned only 27 output tokens.
A saved-history probe preserved signed state and returned the expected marker in 9.65 seconds without any tool execution.
The evidence establishes intermittent upstream endpoint stalls, not Azure's internal resource or queue cause.

Prefer low latency with p90 performance thresholds. Pi prefers the ZDR-compatible `azure/eu` route.
Keep eligible fallback providers and all existing reasoning, context, output, retry, and recovery rules.
Record actual request controls and reported reasoning-token usage in spans without private request bodies.
Prepare release 0.1.15 through the normal topic PR, Pi promotion, and immutable release tag.
The active Pi configuration is now a regular `.env` file, not the earlier documented symlink.
Back it up before editing. Change only its four OpenRouter routing fields and retain all other settings.

## Release 0.1.18 preparation, 2026-10-15

The operator requested development checks, promotion PRs to `main` and `rpi`, and a new Pi release.
Prepare version 0.1.18 through a topic PR from `dev`.
This release includes shared sandbox dependencies, ordinary workspace tools, safe workspace recovery, and Telegram progress tracing.
Keep the open account connector PRs outside this release.
Use merge commits for both promotions after their destination checks pass.
Create immutable tag `rpi-v0.1.18` at the promoted `rpi` tip.
Deployment remains unconfirmed until the tagged workflow and active Pi manifest agree.

## Automatic routing for every OpenRouter model, 2026-10-14

The operator requested removal of endpoint orders for all OpenRouter models.
The proposed model-specific order map was never merged or deployed. Close its PR and remove the proposal.
Remove the global order field and both prepared order variables from the private Pi configuration.
Retain generic latency and throughput preferences. OpenRouter selects compatible ZDR endpoints for the selected model.
Reasoning, context and output limits, retries, signed state, approvals, and safe recovery retain their existing behavior.
Prepare release 0.1.16 through a topic PR, Pi promotion, and immutable release tag.

## Rolling summary and research scratchpad, 2026-10-18

The harness uses one rolling summary, with configurable 50% context trigger and 2.5% recent-tail defaults.
The harness owns shared summary rules and separate initial, update, split-turn, and shortening prompts.
Runtime supplies model settings, persistence, and usage callbacks.
Update prompts retain relevant prior information and apply user corrections, confirmed progress, and resolved blockers.
When compaction splits a turn, a separate call summarizes its original request and earlier progress.
Combine that result with the history summary before the retained messages.
Do not repeat a covered original request after the checkpoint.
Reuse previous history when no new history summary is needed. Update an existing checkpoint when its request is already covered.
Both summary parts must succeed before the checkpoint replaces the previous view.
Optional `CompactionConfig.additional_instructions` supplies summary focus.
Shortening tiers omit structured headings to avoid conflicting output requirements.
The summary model is configurable and defaults to the conversation model.
New unanswered user requests and unfinished tool batches stay verbatim. The saved transcript remains unchanged.
New checkpoints use memory schema version 5.
Recover the omitted request inside version 4 checkpoints from saved history until a successful compaction replaces them.
The active model writes summaries without tools. Large messages stay in history and receive an index marker in summary input.
History tools return exact saved text. Provider overflow retries use shorter summary tiers and never rerun completed tools.

Deep Research evidence stays in the separate `research_scratchpad` table.
Migration 013 renames the earlier evidence table and preserves its rows.
Compaction does not summarize or alter scratchpad records.
Gmail and Health service tools return compact summaries and fetch selected details by provider IDs or date/metric filters. Do not archive full provider responses or register generic provider-source readers.

## Runtime provider context limits, 2026-10-18

Read context and output limits from OpenRouter, Gemini, and Anthropic model metadata, then cache them for one hour. OpenAI's model endpoint does not publish context limits, so direct OpenAI uses a 272,000-token conservative cap for GPT-6 Luna and GPT-5.6 Luna. Other hosts may support more; use that host's metadata when available. Unknown models or providers use a 24,000-token fallback unless an operator sets `AGENT_CONTEXT_TOKENS`. An operator cap can lower, but never raise, a known provider limit.

## Temporary provider result files, 2026-10-18

Provider services decide when a normalized read result needs staging. Results under 8 KiB stay inline; larger results up to 1 MiB can be written under `/tmp/theos-results` through the sandbox peripheral.
The helper returns a path and bounded instructions rather than copying full results into model context. If staging fails or exceeds the file limit, it returns a bounded preview and asks for a narrower provider read.
Temporary result files are outside `/workspace` and are not checkpointed to R2. The runtime owns sandbox lifecycle; do not expose a model-facing `manage_workspace` tool.
Keep `upload_file` for selected owner files and Gmail attachments that need workspace analysis.

## Structured prompts and shared persona, 2026-10-18

Main prompts separate role, instructions, output rules, examples, and runtime context with Markdown headings.
Reusable fragments use only the sections they need. Templates remain ordinary `.md` files.
Place the persona near the main identity and keep dynamic preferences and retrieved memory in labeled context blocks.
The same persona guides chat and speech preparation. Speech source preservation takes precedence over style.
Keep factual research handoffs, titles, and generic harness compaction separate from user-facing personality.
The selected voice branch already supplies the Michael/George blend, speed 0.9, and `theos-subtle-v1` processing.
The operator requested removal of standalone upstream license files and attribution notices. Do not restore those copies.
Keep the project's root license and provenance manifests.
Exception: the operator explicitly removed `src/harness/compression_provenance.json`. Do not restore that file.

## Light navigation readability and favicon, 2026-10-18

Keep the existing frost, opacity, blur, saturation, and refraction settings.
Use darker text for light-mode sidebar labels, costs, account identity, and conversation actions.
The collapsed mobile sidebar trigger needs a header box so the existing optical layer can blur messages beneath it.
Apply this navigation change only in light mode. Preserve dark-mode colors and layout.
Use the existing Theos Daylight image as the browser favicon and touch icon.

## Binary workspace transfers and research reports, 2026-10-18

Use an inclusive HTTP byte range to read sandbox files, with one extra byte to detect the transfer limit.
The sandbox SDK's `offset` and `limit` arguments select text lines and can normalize binary CRLF bytes.
Preserve original bytes for image inspection, file delivery, workspace hashes, and restored files.
The lead researcher needs configured workspace tools to generate and deliver requested report files in the same turn.
Research delegates keep their existing read-only tools. Personal account tools remain excluded from explicit research.

## Reports serve the user, 2026-10-18

Reports must answer the user's question and support their understanding or decisions.
Lead with findings and implications. Use charts and diagrams where they make patterns, comparisons, or relationships easier to understand.
Select those visuals automatically. Users do not need to request charts or diagrams explicitly.
Verify plotted values, bar heights, and axis ticks against the data. Preserve Space Grotesk in standalone SVG charts through embedded fonts or text paths.

Use distinct revision tags for sandbox runtime builds. Retain image records referenced by running sandboxes.
Rebuilding a reused local tag removed image metadata during acceptance testing and broke OpenSandbox status requests for the old instance.
Keep agent activity, read counts, generation details, and provenance out of the main report unless explicitly requested.
Retain citations and concise material limitations without making them the report's purpose.
Do not impose arbitrary total Gmail message, page, or body limits. Read the evidence needed for the requested period and task.
Per-response pagination and body ranges remain bounded for transfer and context management. Continue them as needed.
Earlier 100-header and 30-body limits were acceptance-prompt sampling choices, not production limits.

## Production sandbox candidate, 2026-10-19

Use `theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3` for new local sandboxes.
The image adds locked Matplotlib with headless Agg and Space Grotesk defaults.
Export SVG text as paths and embed TrueType fonts in chart PDFs.
Keep the existing OpenSandbox interpreter entrypoint and one-CPU, 512 MiB resource request.
Exclude caches and environment files from the Docker build context.

The Mac mini retains this image, its runtime dependencies, and the older image required by the Pi.
Retire acceptance sandboxes before removing their images. Remove unused build cache without pruning service volumes.
The Pi environment and application stay unchanged until the separate release step.

## Navigation contrast in both themes, 2026-10-19

Apply the existing collapsed mobile topbar layout in both light and dark modes.
Use brighter dark sidebar text and text halos to preserve readability over reflected content.
Keep the existing frost, opacity, blur, saturation, and refraction settings.
This extends the earlier light-only navigation decision.

## Pi release 1.2.1 preparation, 2026-10-19

The operator requested the changes in PR #86 on `dev`, `main`, and `rpi`, followed by a Pi release.
Merge the topic PR into `dev`, then promote `dev` through separate merge-commit PRs to `main` and `rpi`.
Package version 1.2.1 uses the immutable tag `rpi-v1.2.1` from the current `rpi` tip.
The Mac mini already has sandbox image `theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3`.
The Pi still uses the 2026-10-15 image. Set the new tag in local `.env.pi` and the Pi deployment environment.
Preserve other private settings and file mode 0600. Prepare report skills and run the live sandbox probe before tagging.
Confirm the release workflow and active Pi manifest before claiming deployment.
The live sandbox preflight executes the copied sandbox client with its package identity so relative imports resolve.

## Telegram onboarding and sandbox progress, 2026-10-19

When a ready private user sends `/start`, ask before restarting onboarding.
The continue choice keeps the saved profile and conversation history available.
The restart choice collects the name and timezone again without deleting saved records.
Show `run_command` input as shell code, `browser` input as its `agent-browser` command, and `execute_code` input as Python code in Telegram progress events.

## Next.js frontend and browser authentication, 2026-10-20

The browser now runs in a separate Next.js App Router service under `web/`.
FastAPI owns the API, runtime, SQLite, and scheduler. It serves no frontend page or assets.
React defines the page structure. The mounted browser controller retains native behavior and cleans its listeners, timers, requests, observers, and audio.
The original stylesheet and image and font assets retain their bytes.
One hundred visual comparisons retained measured geometry at five widths in both themes.

Browser sign-in preserves configured and Telegram-owned identities through revocable opaque sessions.
Tokens no longer remain in browser storage. HTTPS cookies use Secure, HttpOnly, SameSite Strict, and host-only prefixes.
The API enforces absolute and idle expiry, logout revocation, configured token rotation, CSRF checks, and persistent login throttling.
The frontend service secret stays on the server. A configured trusted ingress can supply validated client addresses for separate login limits.
The terminal retains direct bearer access to the private API.

Compose retains host port 8080 for the frontend and uses private host port 8081 for the API.
Pi releases publish and record both immutable image digests. Rollback restores the prior pair and data volume.
The frontend source, dependencies, development steps, and migration configuration are documented in the browser, development, and deployment guides.
Local acceptance passed 1,030 Python cases, four proxy checks, sixteen production browser scenarios, and a 10 MiB upload/download.
Docker image builds remain CI checks because the local daemon was unavailable.
Production deployment and branch promotions have not occurred.

## Plain sidebar text, 2026-10-20

The operator rejected the white halo around sidebar text and requested the existing interface without typography degradation.
Remove the light and dark sidebar text shadows added by the 2026-10-19 navigation contrast change.
Keep the font, text colors, geometry, glass material, blur, refraction, and responsive behavior.
This decision supersedes the text-halo part of the earlier navigation contrast decision.

## Mobile conversation heading, 2026-10-20

The collapsed mobile topbar shows the active conversation title and conversation cost in both themes.
Use the existing title and usage updates, including streamed title changes and completed-turn costs.
Long titles truncate within the existing glass topbar. Desktop layout and glass settings stay unchanged.

## React workspace state and rendering, 2026-10-20

The operator requires a complete React migration, including messages, streaming, and interactions, with the exact existing interface in both themes and mobile.
React now owns messages, streaming state, approvals, attachments, voice controls, composer menus, settings, navigation, sign-in, research, connections, and charts.
Remove the mounted workspace controller and its DOM renderers.
The conversation reducer handles saved history and streamed events. Frame batches retain event order, partial replies, tool identities, and replacement answers.
Abort stale requests and release media resources when their owner leaves the page or account.
Keep native browser APIs for dialogs, popovers, focus, measurement, audio, and the existing optical effects.
React owns the optical layers and content wrappers. The effect helper creates only rendering resources.
Keep the stylesheet and font, logo, and provider assets unchanged from the accepted mobile-heading revision.
Bind activity results to their authenticated account and query before rendering.
Personal and administrator views must not reuse each other's results during navigation.
This supersedes the earlier decision to retain the mounted browser controller.

## Compact mobile panel navigation, 2026-10-20

The operator requests a round sidebar control wherever the mobile topbar would otherwise be empty.
Activity, administrator activity, connections, and tools place their heading beside this control in both themes.
Keep the control and heading fixed while the panel scrolls.
React portals move the existing panel heading and back control into the mobile header, without duplicate headings or actions.
Hide the pinned heading while the sidebar drawer is open.
Chat retains its conversation title and cost. Desktop layout rules and the existing glass material stay unchanged.
This requested layout change supersedes stylesheet preservation for these mobile headers.

Keep the mobile panel scroll area behind the entire navigation row.
Reserve its initial header space with padding inside the scroller, so content continues behind both frosted surfaces.
The separate round control and title tab use the same optical material and navigation shadow on every panel in both themes.

## Desktop tab header clarification, 2026-10-21

The operator rejected the combined desktop navigation row and clarified that this change applies only to larger screens.
Keep the original Theos topbar, its logo, and the original conversation title and cost toolbar.
Desktop Tools, Connections, Activity, and Admin use that conversation toolbar format above their scrolling content.
Place each tab title and muted subtext on the left, with Back to chat aligned on the right.
Remove the Theos logo from tab headers. Keep it in the main topbar.
Restore the accepted mobile conversation header, compact panel headers, and continuous frost from the preceding mobile revision.
Desktop tab content panels use the chat window's 26-pixel curved border, edge color, and shadow beneath their toolbars.
Daily chart hover selection requires pointer movement, so focus scrolling cannot overwrite keyboard selection under a stationary pointer.

## Browser OpenUI answers, 2026-10-21

Use OpenUI Lang for browser chat presentation only. Keep the OpenAI Responses runtime, tools, approvals, checkpoints, and SSE flow. Do not add the OpenUI Gateway or Query()/Mutation() in this release.
Define one pinned Zod component library for both the React renderer and the generated Python model prompt. Version the display format and component library. Keep generated prompt, schema, and manifest artifacts in `src/theos/prompts/openui/`.
Require `TheosAnswer` with a visible `AnswerSummary`. Preview streamed output, but enable actions only after a complete parse with the expected root and no parser errors, unresolved references, or orphaned statements. Hide invalid source and offer a user-triggered plain-text recovery turn with tools disabled.
Keep form edits in application display metadata. Bind actions to an owned saved message and route writes through existing validated Theos tools and approvals. Rendering a component must not perform a write.
Read aloud only the visible `AnswerSummary`. Terminal history uses a saved summary or a browser notice. A disconnected stream reloads saved history and never replays a turn automatically.

Local Docker deployment must load application settings from `/Users/nightowl/my_projects/theos/.env`, including its configured browser token.
Keep image references, the existing data volume, and the private frontend service secret in a separate deployment file.
Normalize OpenUI field wrappers before saving drafts or submitting actions. Include untouched form defaults and preserve restored edits.
Reset message display state before child effects publish the rendered summary and form defaults.

Keep visual answers inside the OpenUI component library and renderer. Library version 2 adds metric grids, bar and line charts, donut charts, goal rings, and tables.
Use the existing green palette, Space Grotesk, theme tokens, and glass controls. Keep version 1 answers renderable through the compatible additive schema.
Chart series must share a unit. Preserve missing samples as gaps and require an explicit source for goals or trends.
Scope drawer styles and optical effects to the navigation sidebar. OpenUI status notices must remain inline when the drawer opens or closes.
OpenUI evidence cards show readable domains, titles, excerpts, and paths. Display search terms and source filters without raw operator syntax.
Retain the exact query under collapsed Search details. Remove duplicate excerpt labels, and do not display a URL as a research source ID.

OpenUI evidence cards accept search-provided thumbnails, image descriptions, and logos through optional trailing fields. Preserve version 1 and 2 answers.
When search omits a logo, discover a raster icon from the source origin's HTML head before trying `/favicon.ico`. Keep the domain initial on failure.
Serve media through the authenticated Next.js `/api/search-image` route. Validate public addresses at socket lookup and on every redirect.
Bound image bytes, head reads, request time, concurrent downloads, and memory cache size. Never forward browser credentials to source sites.
Keep the existing image CSP. Do not load remote image URLs directly in the browser or add a third-party favicon service.

## OpenUI release preparation, 2026-10-21

Prepare version 1.3.0 for OpenUI answers and the separate Next.js frontend. Promote the integrated code to both `main` and `rpi` through separate PRs.
The Pi upgrade requires a private frontend service secret and the tested `v1.1.0-20261019-18e1cc81d4c3` sandbox image. Preserve all other Pi credentials.
Use the tagged release workflow and retain the previous image pair, volume, and environment backup for rollback.

Browser CI starts its long-lived API process with the synchronized virtual environment's Python executable.
Do not keep `uv run` alive across the job. It holds the cache lock and prevents setup-uv from pruning a cold cache.
Stop acceptance processes before post-job cache cleanup.

## Mobile keyboard release preparation, 2026-10-23

The operator requested PR #100 on `dev`, `main`, and `rpi`, followed by a minor Pi release.
Prepare package version 1.4.0 and immutable tag `rpi-v1.4.0` at the promoted `rpi` tip.
Use separate promotion PRs and merge commits. Preserve the existing glass material and private deployment configuration.
No database migration is required. Confirm the release workflow and active Pi manifest before claiming deployment.

## Mobile keyboard and conversation activity, 2026-10-23

Position the application frame with the visual viewport offset and layout containment, without a transform on the full frame.
Ignore invalid viewport heights. Refresh measurements after focus changes and page restoration, as well as viewport resize and scroll.
Keep native pinch zoom and preserve drafts through keyboard toggles.

Show one pulsing Thinking label and glowing orb in the conversation throughout the streamed turn, including tools and context preparation.
Stop the indicator on completion, approval waits, errors, and disconnects. Reduced motion keeps the label and orb static.
Keep tool states in tool events. Remove run state labels, including completed, from the composer.
Keep composer errors and recording feedback. Show a reopened running-turn notice in the conversation.
This supersedes earlier decisions to show run progress inside the composer.

Native simulator checks reproduced the blank keyboard view on iPhone 14 Pro with iOS 27.0.
A second keyboard cycle also exposed a remaining offset cap in the initial PR #104 build.
Safari reported `innerHeight=560`, visual height `447`, offset `236`, and root scroll `236`.
The cap reduced the offset to `113` and moved the application frame to `-123` pixels.
Use the full nonnegative visual viewport offset, including during keyboard dismissal. Do not cap it with `innerHeight`.
The corrected iPhone 17 Pro Max check retained the frame at zero with a `349`-pixel offset and preserved the draft across keyboard toggles.
The iPhone 14 Pro simulator was shut down before testing iPhone 17 Pro Max, as requested.

Keep the document backdrop at the theme canvas color. Paint the ambient glow once inside the application frame.
Fade the glow into the canvas at the bottom edge to avoid a hard boundary above the native keyboard accessory.
Apply the saved theme through a nonce-authorized script before React loads, so Safari samples the correct initial backdrop.
Do not reset that theme during hydration. Native Safari can retain its previous bar color after an in-page theme switch until reload.

## Mobile keyboard patch release, 2026-10-23

The operator requested deployment of the mobile keyboard and conversation activity fixes as version 1.4.1, with promotion to `main`.
Prepare package version 1.4.1 and immutable tag `rpi-v1.4.1` at the promoted `rpi` tip.
Use separate promotion PRs and merge commits for `main` and `rpi`.
No database migration or private environment change is required. Confirm the tagged workflow and active Pi manifest before claiming deployment.

## Unified workspace commands and private browser, 2026-10-26

The model uses `run_command` for execution and optional image inspection. It uses `attach_file` only for response attachments.
Selected uploads and Gmail attachments enter the session workspace automatically. Changed files use the existing local journal and background R2 worker.
Attachment snapshots retain exact bytes and metadata for remote session restoration. Deleted workspace files remain absent from the latest manifest.
History read and search remain separate. Existing transcripts retain old tool names.

Standalone browser CLI commands route to a dedicated browser sandbox per owner. Conversations use distinct tabs under an owner lock.
Screenshots, PDFs, explicit downloads, and selected uploads cross into the task workspace through runtime code.
Browser profiles stay outside task workspaces. Live authentication state and profile snapshots preserve login continuity across replacement.
Profile capture pauses writers briefly and retains SQLite journals. A separate watchdog resumes browser processes after capture failure.
The application encrypts snapshots in SQLite with a generated private `browser.key`. Stopped-application backups include this key.
Connections supplies private browser controls for login and verification. These actions create no chat messages or tool records.
Clearing browser login destroys that owner's browser and deletes saved credentials.

Local acceptance used the pinned browser CLI with a synthetic website and isolated profile.
Cookies, local storage, and IndexedDB survived replacement. DOM interaction and screenshot transfer passed.
This verifies the command and profile protocol locally. It does not confirm a deployed OpenSandbox or Pi release.

## Runtime checkpoint retention, 2026-10-26

The user requested collection of unreferenced immutable workspace versions. This is application storage policy, separate from the generic harness.
New checkpoint snapshots include current workspace and response-attachment sources. Historical workspace objects no longer accumulate in every new snapshot.
The collector preserves three recent snapshots by default, both recovery pointers, direct workspace and attachment roots, and all retained-snapshot references.
Legacy snapshots keep their original references while retained.

The background checkpoint worker also runs for local-only storage. Retention uses hourly scans, a one-hour grace period, and bounded continuation batches.
Reusing an existing content-addressed object refreshes its grace period. Active sessions and pending remote-recovery reviews defer collection.
SQLite migration 015 journals deletion before local or remote removal. R2 partial failures retry with backoff after restart.
A recreated blob remains pending until its older deletion finishes. Local checkpoint writes do not wait for R2 deletion.
The collector preserves unrelated research objects, uploaded-file catalog entries, browser profiles, and transcripts.
Upload intent records preserve uncertain remote writes across restart or configuration changes.
Uncertain pointer publications remain roots until a later publication is confirmed. Remote restore registers the fetched checkpoint as a recovery root.
No `src/harness` file changes are required.

## Slack connector planning, 2026-10-15

The operator requested a separate topic branch and a tool-coverage and complexity review.
Branch: `feature/slack-connector`, from remote `dev` at `8a4360f`.
Check internal or Marketplace app eligibility before the MCP connection. Review granular search scopes and workspace consent.
The connector remains proposed and unimplemented. Live authorization and discovery remain pending.
See [the plan](docs/connectors/slack-plan.md) and its tool inventory.

## Slack official MCP implementation, 2026-10-15

The operator requested existing connectors wherever possible and implementation on each separate branch.
Use the official remote Slack MCP server through a reviewed read-tool allowlist.
Keep provider tools on the remote server and account access in Theos.
The initial adapter supports one provider connection per owner without a schema migration.
Browser Connections and private Telegram commands share that owner's encrypted credentials.
Confidential OAuth uses a client secret and durable single-use state.
Slack public-client PKCE mode is not enabled. Other providers retain the shared adapter default of PKCE.
Refresh and disconnection share an owner lock. Configuration changes invalidate saved grants.
Tool discovery is paged. Unknown tools and writes stay unavailable.
Remote read results use the existing source and journal services.
The initial allowlist contains 18 tool identifiers, subject to discovery and provider permissions.
Tests use mock services. Live account consent and discovery remain pending.
See [setup](docs/slack-mcp.md).


## Slack branch synchronization, 2026-10-28

The operator requested a merge of current main into feature/slack-connector before live testing.
Preserve both branch histories with a merge commit. Keep the current Next.js frontend and native Telegram connection controls.
Register Slack in the shared account setup, callback proxy, connection cards, and composer mentions.
Cancel setup invalidates pending consent without deleting the previous Slack grant.
Use the current provider result staging service for large reads. Do not restore the retired source wrapper or static browser app.
The local Docker test uses a separate data volume and disables Telegram polling.
Live Slack authorization and read acceptance remain pending.

The saved local Slack OAuth grant survived the updated Docker deployment.
Live MCP initialization reports that the app is not enabled for Slack MCP server access.
The operator must enable MCP access in the Slack app settings before live tool discovery can pass.
