# Feature and acceptance checklist

## Calendar OpenUI components, 2026-10-28

Library version 3 adds an agenda, event card, and availability timeline. Saved versions 1 and 2 remain renderable.
Calendar views preserve all-day exclusive ends, IANA timezones, and daylight-saving offset changes.
The availability calculation clips and merges busy intervals. Failed, missing, or malformed results leave unknown gaps.
Source-provided event and meeting links remain safe links. Event descriptions display as literal text.

All 27 frontend unit tests, 48 focused Python checks, and 80 OpenUI browser scenarios passed.
The browser checks covered four widths in both themes, keyboard inspection, reloads, partial results, invalid dates, and unsafe links.
The Calendar views made no turn requests during browser inspection. Tests used synthetic events and mocked provider responses.
Formatting, Python lint, generated artifact validation, and production frontend compilation passed.
Mobile light and desktop dark screenshots passed visual review. Native ARM64 API and frontend image builds passed.

Both local services now run the Calendar OpenUI images on ports 8080 and 8081.
Readiness, installed version 3, generated component instructions, and meeting-link fields passed direct checks.
The existing account connections and data volume survived replacement. No live Calendar event was created or changed for these checks.
Live model selection of the new views and production deployment remain unverified.

## OpenUI summaries and completed thinking, 2026-10-28

Text-only summary facts now use label/value rows. Completed thinking retains its disclosure and shows `Thought for x s` from the saved generation duration.
Reasoning-only messages hide their separate role and metadata footer. Hidden OpenUI tool phases retain their reasoning after reload.
Older summaries without timing show `Thought`. Active reasoning uses one thinking indicator.

Approval reviews now use a neutral panel with a fixed heading and decision controls. Long review contents scroll inside the panel.

All 22 frontend unit tests, 27 focused Python checks, and 64 OpenUI browser scenarios passed.
Browser checks covered four widths in both themes, streamed completion, disclosure identity, and reload restoration.
Approval checks covered exact arguments, disabled controls, rejected submissions, and accepted denial. These checks used synthetic data and an isolated local API.
Formatting, OpenUI artifact validation, and the production frontend build passed. Mobile light and desktop dark screenshots passed visual review.

The native ARM64 frontend image built and replaced only the local frontend container on port 8080.
The existing API container stayed running. Both readiness endpoints passed. The saved Slack summary displayed the updated rows and completed thought labels.
Production deployment remains pending.

## Optional connection onboarding and account returns, 2026-10-24

Telegram offers configured, unconnected accounts after the name and timezone questions.
Browser setup reuses the saved profile and asks for a name only when missing.
Both transports share the optional setup completion marker.

Connect reserves a disowned browser tab before asynchronous discovery. A blocked popup retains an explicit sign-in link.
Successful callbacks return to Connections. Callback tabs close themselves only after the selected account passes verification.
Cancellation invalidates pending consent without deleting the previous account.
Zepto stages new credentials until MCP initialization and tool discovery succeed. Failed or interrupted setup discards staged credentials.
The existing localhost handoff remains available. A hosted HTTPS callback still requires provider allowlisting.

The complete Chromium suite passed 120 cases, with 16 desktop-only skips for mobile viewport scenarios.
Four focused WebKit connection cases passed at 320px. Screenshots passed review at 320px, 390px, and 1280px.
The focused Python suite passed 78 cases. Eighteen Node checks, formatting, OpenUI validation, and the production frontend build passed.
A local combination of PRs #108 and #109 merged cleanly and passed 1,053 Python tests, with three live checks deselected.
These checks used disposable accounts, the fake model, and mocked provider responses. No production account was authorized or deployed.

## Mobile Return key, 2026-10-24

At widths up to 700px, Return inserts a new line in the composer, including while suggestions are visible.
The keyboard hint and accessible instructions match this behavior. The send button submits the draft.
Desktop Enter sends the draft. Shift + Enter inserts a new line.

The existing workspace and activity checks passed 24 Chromium cases across four widths and both themes.
Six workspace cases passed in WebKit at 320px, 390px, and 1280px.
They checked multiline drafts, saved history, suggestion behavior, explicit sending, and desktop keyboard submission.
Fifteen Node checks, three focused Python browser checks, formatting, OpenUI artifact validation, and the production frontend build passed.
Browser checks used the fake provider and disposable local storage. This change has not been deployed to the Pi.

## iPhone keyboard layout and navigation arrows, 2026-10-23

The application frame follows visual viewport height and vertical offset, including scroll-only keyboard movement.
Fixed navigation stays inside the frame. Native dialogs use the same visible bounds in the browser top layer.
Keyboard dismissal clears stale offsets. Pinch zoom retains native browser control.
Sidebar and sign-in actions use decorative SVG arrows, so iOS cannot replace them with emoji.

The regression test reproduces a 116-pixel composer gap on unchanged `dev` during a simulated 96-pixel viewport shift.
The fixed layout keeps the composer within 24 pixels of the keyboard boundary and preserves the draft.
Checks cover long drafts, navigation, dialogs, token sign-in, dismissal, and zoom.

The existing Chromium suite passed 56 cases across four widths and both themes.
Eight keyboard cases passed in Chromium and WebKit at 320 and 390 pixels in both themes.
Fifteen Node checks, eleven focused Python browser checks, formatting, generated OpenUI validation, and the production frontend build passed.
The full WebKit run passed 60 cases and failed four mobile chart-selection cases during window resizing.
The same chart failure reproduced on unchanged `dev` at `f09e307`. It is separate from the keyboard fix.

Physical iPhone keyboard animation and Home Screen mode remain unverified. The Pi deployment is unchanged.

## Browser OpenUI answers, 2026-10-21

Implementation is on `feature/openui-browser`. Local Docker results appear under [local replacement](#local-openui-docker-replacement-2026-10-21).

Release checks remain open:

- Confirm `npm run openui:check` passes and the generated prompt, schema, and manifest match `web/src/openui/library.js`.
- Check a simple answer, evidence links, streamed rendering, and invalid output in both themes and on mobile. Confirm invalid output hides source and only exposes a user-triggered text recovery.
- Save and reload reminder drafts. Check timezone and daylight-saving validation, recurrence, and the existing tool approval path.
- Confirm read aloud uses only `AnswerSummary`, terminal history uses the saved summary or notice, and an interrupted browser stream does not replay the turn.
- Run the project CI and browser acceptance before merge.

## OpenUI visuals and drawer isolation, 2026-10-21

OpenUI library version 2 adds metric grids, bar and line charts, donut charts, goal rings, and tables.
Each component remains registered in the OpenUI library. Generated artifacts supply the matching schema and model instructions.
The renderer still accepts version 1 answers. Existing fact cards now use metric tiles with the workspace palette and typography.

The health conversation reproduced a mobile drawer collision. A status notice inherited global `aside` layout and covered navigation.
Drawer styles now target the navigation sidebar. Status notices remain inline in the answer.
Reminder controls share the glass picker, a matching calendar, and weekday buttons. Menu cleanup retains its element before React clears the ref.

Eight Node checks passed, including schema registration, exact axis values, signed scales, and missing-data gaps.
Forty browser scenarios passed at 320, 390, 768, and 1280 pixels in both themes against the built containers.
They covered version 1 restoration, drawer isolation, calendar selection, popover dismissal, saved draft edits, chart inspection, and exact-value tables.
The Python suite passed 1,025 tests, with five skipped and three live checks deselected.
Generated-artifact validation, Prettier, Ruff, whitespace checks, and both native ARM64 image builds passed.

The local API image is `theos:local-openui-visuals-final-20261021`.
The frontend image is `theos-web:local-openui-visuals-complete-20261021`.
The deployment retains the root `.env` and existing data volume. A verified SQLite backup preceded replacement.

The same local work then improved OpenUI evidence cards using the saved search conversation.
Cards show a readable domain, title, excerpt, path, and result count. The default query label excludes operator syntax.
Source filters remain visible as chips. Collapsed Search details retains the exact provider query.
URLs no longer appear as research IDs, and snippet prefixes no longer duplicate the Excerpt badge.
Ten Node checks and all 48 browser scenarios passed, including unsafe-link rejection and version 1 search restoration.
The final local API is `theos:local-openui-search-20261021`. The frontend is `theos-web:local-openui-search-ready-20261021`.
Both retain the repository root `.env` and existing volume.

## OpenUI search images and logos, 2026-10-21

OpenUI evidence cards accept optional search thumbnails, image descriptions, and source logos. Saved version 1 and 2 answers remain compatible.
Desktop cards place images beside excerpts. Mobile cards place images above excerpts. Failed thumbnails collapse and failed logos retain domain initials.
When provider metadata omits a logo, the frontend server reads the source origin's declared raster icons before trying its conventional favicon.
The authenticated same-origin endpoint retains the existing CSP and sends no browser credentials to source sites.
Public address validation runs during socket lookup and after each redirect. Image bytes, HTML reads, time, concurrency, and cache size have explicit bounds.

Fifteen frontend checks passed. They covered public DNS, alternate IP encodings, redirects, media bounds, icon discovery, and metadata fallback.
Forty container browser scenarios passed at 320, 390, 768, and 1280 pixels in both themes.
They covered loaded and failed media, image sizing, keyboard links, saved answers, query cleanup, charts, forms, and the navigation drawer.
Focused Python checks passed 28 tests, with one skipped. Provider mappings retain the original Exa and Brave result fields.
Formatting, lint, generated artifacts, whitespace checks, and native ARM64 builds passed.

A live configured search returned three NASA thumbnails. The image endpoint served all three and discovered NASA's declared PNG icon.
Native desktop and mobile checks found and fixed inherited chat image margins and width limits.
The local API and frontend now use `theos:local-openui-media-20261021` and `theos-web:local-openui-media-20261021`.
Both containers are healthy. All 42 root `.env` values match the application container, and the file remains byte-for-byte unchanged.
Configured token sign-in passed. SQLite integrity passed and all 111 file records remain available.
A verified consistent database backup preceded replacement. Acceptance evidence is in `.theos/local-deployment/acceptance-openui-media-20261021/`.
A live model search created Official NASA James Webb Image Galleries with a rendered NASA preview and source logos.
Native checks confirmed desktop and mobile layouts and restoration after reload. The old image pair and disposable test stack were removed.

## Desktop tab header clarification, 2026-10-21

The original Theos topbar and conversation title and cost toolbar are restored.
Desktop Tools, Connections, Activity, and Admin place their tab title and subtext in a matching toolbar above the scrolling content.
Back to chat appears on the right. Tab headers contain no Theos logo, while the main topbar retains its logo.

Native comparison covered all four tabs in both themes at 1280 pixels.
Each matched the original conversation toolbar's position, height, 17-pixel title, 650 font weight, line height, and letter spacing.
Subtext retained the conversation cost's 11-pixel font and muted theme color. Back controls retained a 12-pixel right inset.
The 768-pixel desktop view retained its logo and labeled back action without horizontal overflow.
The 431-pixel mobile panel retained its earlier compact header, and the 320-pixel chat retained its full title and cost bar.
The browser reported no errors or warnings. The production ARM64 frontend image built successfully.

Desktop tab content panels now match the chat window's 26-pixel curved border, edge color, and shadow.
Native comparison confirmed exact border and shadow values for all four tabs in both themes at 1280 pixels.
The 431-pixel mobile panel retained its existing border, radius, and compact header without horizontal overflow.

CI exposed a mobile chart hover update that replaced keyboard selection when focus scrolled the chart beneath a stationary pointer.
Daily chart hover updates now require pointer movement. Arrow keys retain focus and selection during scrolling.

## Compact mobile panel navigation, 2026-10-20

Empty mobile topbars now use a round 60-pixel sidebar control.
Activity, administrator activity, connections, and tools pin their existing heading and back control beside it.
The drawer hides the pinned heading. Chat retains its conversation title and cost header.
React moves each heading through a portal, so there is only one heading and back action per panel.

Native inspection covered 320 and 431 pixels in light and dark themes without horizontal overflow.
Activity retained its header at eight pixels from the top after scrolling 827 pixels.
Connections, tools, and administrator navigation retained visible headings and back controls.
The preview reported no browser errors or warnings. Production Next.js and ARM64 frontend image builds passed.
Desktop layout rules, fonts, colors, and glass settings remain unchanged.

The panel scroll area now extends behind both frosted header pieces.
Internal padding preserves the initial content position without clipping scrolled material below the header.
Native inspection covered Activity, Admin, Connections, and Tools in both themes at 431 pixels.
All eight views retained matching optical tint, blur, saturation, and navigation shadows.
The scroll area began at four pixels, while the separate header pieces remained fixed at eight pixels.
The 320-pixel Tools view also retained this scroll area without horizontal overflow.
The browser reported no errors or warnings. The production ARM64 frontend image built successfully.

## React workspace ownership, 2026-10-20

React state now owns chat messages, streaming, approvals, attachments, voice controls, composer menus, settings, navigation, sign-in, research, connections, and charts.
The old workspace controller and its Markdown, select, and chart DOM renderers are removed.
The stylesheet and visual assets retain their bytes from the accepted mobile-heading revision.

Native comparisons covered desktop messages at 1280 by 720 pixels and mobile views at 431 by 827 pixels.
Compared message, Markdown, reasoning, tool, composer, settings, picker, connection, and chart geometry and styles matched the original frontend.
Mobile message comparisons covered both themes. The title and cost retained the accepted header layout without horizontal overflow.
Markdown retained code-copy controls, table regions, disabled task checkboxes, literal HTML, blocked unsafe links, and remote-image links.

The disposable preview exercised streamed text and reasoning, tool updates, compaction, replacement answers, file controls, and approval decisions.
An interrupted stream retained its partial reply, stopped thinking feedback, released controls, and displayed the existing recovery message.
Settings save retained the draft. Sign-out cleared it, and cookie sign-in restored the workspace.
Five existing frontend contract checks passed after migration to the React reducer, hooks, chart data, and optical effects.
Prettier, Ruff for the changed checks, the production Next.js build, and the ARM64 frontend image build passed.
Live microphone capture, speech synthesis, Telegram confirmation, and connector writes were not exercised in this preview.

The full local Python suite passed 1,030 tests, with three credential-dependent checks excluded, after the React migration.
Four proxy checks, Ruff, Prettier, and a fresh production Next.js build also passed.
CI exposed stale personal totals during navigation to the administrator dashboard.
Activity results now retain their authenticated account and query, so each view renders only matching data.
Browser acceptance waits for chart data and checks both dashboard scopes and uncaught page errors.

## Mobile conversation heading, 2026-10-20

The collapsed mobile topbar shows the active conversation title and conversation cost in light and dark themes.
The title and cost share the desktop update paths. Long titles truncate within the existing 60-pixel glass header.
Native inspection at 344 by 741 pixels confirmed both themes, visible costs, and no horizontal page overflow.
Selecting another saved conversation updated both values. The drawer retained its existing layout and hid the heading while open.
The production frontend image built successfully and replaced the local web container. Both local services report healthy.

## Plain sidebar text, 2026-10-20

The sidebar no longer applies white or dark text halos.
The stylesheet differs from the pre-migration baseline only by removal of seven text-shadow lines.
All seven font, logo, and provider icon assets match the baseline bytes.

Native browser comparison covered light and dark themes at 519 by 741 pixels.
Thirty sidebar elements retained their font settings, colors, backgrounds, and glass filter styles.
Visible geometry matched after accounting for the drawer's open or closed position.
The settled light view retained the original blurred green backdrop without the white glyph outline.
The rebuilt local frontend is healthy. The backend and existing conversations remain available.

## Separate Next.js frontend and browser sessions, 2026-10-20

The Next.js frontend and FastAPI API run as separate processes and Compose services.
FastAPI no longer serves the browser page or static assets.
React components retain the original workspace structure. The stylesheet, font, logos, and provider icons retain their original bytes.

The full Python suite passed 1,030 tests, with three credential-dependent checks excluded.
Six session checks cover cookie attributes, CSRF, rotation, expiry, logout, role boundaries, and login throttling.
The existing Telegram enrollment and connected-terminal checks retain their owner and approval rules.
Four Node checks cover the proxy's credentials, origin checks, separate cookies, validated ingress addresses, and immediate SSE delivery.

Sixteen production browser scenarios passed at 320, 390, 768, and 1280 pixels in both themes.
They cover cookie sign-in, reload, logout revocation, CSRF rejection, streaming, settings, native glass pickers, workspace navigation, and draft preservation.
Nonce values differ between requests. Production CSP permits no arbitrary inline scripts.
A separate HTTP smoke check uploaded and downloaded a 10 MiB file byte-for-byte through Next.js.
API routes bypass middleware body cloning. The upstream stream client retains disconnect cancellation without idle timeouts.

The [visual comparison](nextjs-ui-comparison.json) records 100 pairs against commit `0fc71659b90a8d5253e95cf5bd9a1296f5ff4e5a`.
Checks covered ten workspace states at 320, 390, 700, 768, and 1280 pixels in both themes.
Measured geometry matched in every pair. Isolated glass pixels differed by at most one channel level out of 255.
No captured state had horizontal overflow or an unexpected browser error.
These checks used a fake provider, reduced motion, and disposable databases.

Production Next.js and Python package builds, Ruff, Prettier, workflow validation, dependency-lock validation, and both Compose configurations passed.
The Python wheel contains the API migrations. The source distribution contains frontend sources without Node modules or build caches.
The npm production dependency audit reported no known vulnerabilities.
Docker was unavailable locally, so image builds and live container replacement remain CI checks.
The release workflow publishes separate immutable image digests. Deployment tests cover replacement and rollback of both services.
No branch promotion or production deployment occurred.

## Direct motivation, 2026-10-18

The shared persona now specifies firm, masculine encouragement for ordinary discouragement and procrastination.
It calls for one achievable action, respects requested gentleness, and treats grief or serious distress with care.
The main prompt includes a low-motivation example.

All 33 focused prompt, speech, identity, and override checks passed. No pytest cases were added.
Four tool-free live model probes covered discouragement, procrastination, requested gentleness, and grief.
The first two gave direct next actions. The latter two adjusted their tone to the request and context.

## Local account and light navigation checks, 2026-10-18

The ARM64 image completed explicit research, Gmail search/body/thread reads, and a bounded spending-analysis scenario.
Research returned six primary documentation links and saved its evidence separately from conversation compaction.
Gmail reads exercised temporary result files and selected message and thread access.
The spending answer retained four inspected source IDs and evidence amounts. Its two currency subtotals passed an independent arithmetic check.
The answer reported sample coverage and exclusions. No Gmail write tool ran.
Private mailbox contents and amounts remain outside project artifacts.

A synthetic long conversation reproduced low-contrast sidebar labels behind the original glass material.
Darker light-mode ink resolved the cost, identity, and conversation-action labels without changing frost parameters.
The mobile header now supplies a box for the existing optical layer.
Native checks passed at 320px, 390px, and 1280px without horizontal overflow.
Computed dark-mode header, toggle, sidebar, optical layer, cost, identity, and conversation-action styles matched the baseline.
The page declares the existing Theos image as its PNG favicon and touch icon.

## Structured prompts and shared voice, 2026-10-18

All 27 prompt templates now use explicit sections or sectioned composition.
Main chat separates identity, persona, instructions, response format, examples, and runtime context.
Preferences and retrieved memory use labeled context blocks.
Chat and speech preparation include the same persona. Source preservation takes precedence during speech preparation.
Delegates, titles, and harness summaries retain factual task roles. Compaction selection and split-turn ordering remain unchanged.

The full local suite passed 1,021 tests, with three live-provider tests excluded.
The 18 focused speech and identity checks passed after the final composition change.
Existing checks now verify persona delivery to the speech request and the main prompt's section order.
No new pytest cases were added. Python lint, formatting, lock validation, and whitespace checks passed.
The wheel contains all 27 templates and no standalone upstream license or notice copies.

Four tool-free live model probes covered decisive advice, uncertain actions, duplicate receipt evidence, and requested gentleness.
The uncertain backup remained uncertain. Matching receipt IDs did not establish separate payments.
A separate speech probe preserved `16:30`, `3`, and `2500 USD` exactly.
These probes used synthetic examples. The connected local account checks are recorded above.

The speech gateway and client match `feature/philosophical-voice`.
Configured synthesis uses `am_michael(0.7)+bm_george(0.3)` at speed `0.9`.
The reachable gateway reported profile `theos-subtle-v1`.
A live synthesis request returned decodable MP3 audio with the selected blend and speed.

## Test consolidation, 2026-10-18

The local suite passed 1,017 cases, down from 1,153. Three live provider checks remain deselected.
The cleanup removed 136 cases through redundant-check removal, smaller independent-flag matrices, and consolidated request and response contracts.
Approval, ownership, recovery, persistence, compaction, and provider failure scenarios remain covered.
Source coverage retained the same 11,171 executed lines and 3,218 branch outcomes.
Application source hashes remained unchanged. The retained estimator contracts reject a constant-one estimator.
Python lint, formatting, and whitespace checks passed for the changed tests.
See [test selection](testing.md) for the retained-case policy and coverage commands.

## Packaged Markdown prompts, 2026-10-18

Theos runtime prompts and harness production prompts now live in separate package-owned `.md` directories.
Jinja supplies includes and text conditions. Python retains capability checks, data retrieval, and compaction decisions.
Theos can override individual compaction prompts through `CompactionConfig`. Missing overrides retain harness production defaults.
See [prompt templates](prompts.md) for the supported filenames and fields.

The full local suite passed 1,153 tests, with three live checks deselected.
Prompt checks cover conditional composition, missing variables, literal inserted data, isolated renders, and per-operation overrides.
Baseline comparisons retained exact text across 32 chat combinations and all six summary operations.
They also retained delegate, speech, title, recovery, skill, tool-batch, and checkpoint wrapper text.
A clean wheel installation loaded and rendered all 27 prompt resources outside the repository with core dependencies only.
Python lint, formatting, lock validation, and whitespace checks passed.
These checks used scripted model responses and local data. They did not deploy a release.

## Temporary provider result files and workspace tools, 2026-10-18

Selected Gmail search, message, thread, and draft reads, plus Health summary and export-status reads, keep normalized results up to 8 KiB inline. Larger results up to 1 MiB use temporary files under `/tmp/theos-results`, outside the durable `/workspace` checkpoint tree.
If staging fails or the result is too large, the tool returns a bounded preview with instructions to narrow the provider read. Model-facing file and execution tools can inspect selected sections.
The model-facing `manage_workspace` lifecycle tool is removed. Sandbox recovery remains automatic, and `upload_file` remains for selected user files and downloaded attachments.

`tests/test_result_files.py` checks inline results, temporary staging, bounded fallback, and the size limit.
`tests/app/test_integrations.py` checks temporary sandbox writes and the available sandbox tool list.
`tests/app/test_sandbox_recovery.py` checks lifecycle recovery through the internal sandbox service.

## Rolling summary and research scratchpad, 2026-10-18

The harness keeps one rolling summary and the full transcript.
It defaults to a 50% trigger and a 2.5% recent tail. Both ratios and the summary model are configurable.
The harness owns shared summary rules and initial, update, split-turn, and shortening prompts.
Runtime supplies model settings and persistence and usage callbacks.
Split turns use separate history and turn-prefix summary calls.
The checkpoint contains the covered original request and precedes the retained messages.
New unanswered user requests and unfinished tool batches remain verbatim.
Provider overflow retries use shorter summary tiers and do not repeat completed tools.
Large messages remain available through exact history tools.
Deep Research evidence remains in the separate `research_scratchpad` table.

`tests/test_compaction.py` checks summary updates, tool batches, retry tiers, and exact history reads.
It checks separate split-turn calls, prompt selection, optional focus, and context order without request replay.
It checks atomic failure when either summary is unavailable and retains unfinished tool batches during overflow recovery.
Shortening checks verify that the three length tiers omit structured heading requirements.
`tests/app/test_text_summary_state.py` checks checkpoints, version 4 recovery, schema migration rollback, and scratchpad independence.
Prompt checks use scripted model responses.
The local suite passed 1,117 tests, with three live checks deselected.
Python lint, formatting, and whitespace checks passed for the changed code.

## Runtime provider context limits, 2026-10-18

OpenRouter, Gemini, and Anthropic context and output limits come from their model metadata and are cached for one hour. Direct OpenAI uses a conservative 272,000-token cap for GPT-6 Luna and GPT-5.6 Luna; available model profiles differ by host, and OpenAI's model endpoint does not return a context limit.
Unknown models or providers use a 24,000-token fallback unless `AGENT_CONTEXT_TOKENS` is set. Explicit context settings can reduce known limits but cannot exceed provider metadata or the conservative OpenAI cap.

`tests/app/test_context_policy.py` checks provider metadata, both OpenAI Luna aliases with and without an operator setting, cache behavior, and the unknown-model fallback.

## Browser glass UI and expanding composer, 2026-10-17

The focused browser and dashboard suite passed 48 tests after the workspace-panel changes.
JavaScript syntax, Prettier, and whitespace checks passed.

PR validation on 2026-10-18 passed 1,135 tests with three live-provider tests excluded.
The isolated validation environment used the locked server and terminal dependencies.
One 30ms recovery test timed out on the initial run. All 21 recovery tests and the full rerun passed.
Ruff lint and formatting, dependency-lock validation, and both package builds passed. The wheel includes all six updated browser assets.

Headless Chromium checks covered widths from 320px through 1440px without horizontal overflow.
Both themes passed compact and expanded composer checks at five widths, including the 700px sidebar breakpoint.
Checks covered the plus menu, file selection, uploaded attachments, settings saves, commands, selected research mode, and empty-input collapse.
The idle readiness note and its layout space are absent.

Additional checks covered chat submission, Markdown replies, multiline drafts, short viewports, drawer focus, navigation, dialogs, and reduced motion.
The preview used disposable SQLite data and a fake provider. It changed no production records and called no external model.
Physical iOS and Android keyboard checks remain pending.

The native wheel and source distribution built successfully on this device.
An isolated Python environment runs the installed wheel on loopback port 8082 with a separate test account and local database.
Readiness and authenticated access passed. Served CSS and JavaScript match the built wheel.
A live `gpt-6-luna` request returned the expected marker in 8.65 seconds with no tool calls.
The local browser signed in and displayed the updated UI. Telegram polling remains disabled for this test instance.

The composer uses a floating optical layer with a 10px blur and rim refraction in Chromium.
Its CSS fallback uses a 12px blur.
Native browser checks covered idle and expanded inputs at five widths in both themes.
Input and button rows measured 44px. Microphone and send retained an 8px gap during focus and draft changes.
Short-viewport checks covered 140px drafts, selected research mode, reserved reply space, and menus above the input.
Scrolling placed chat content behind the composer.

Mobile has no header or conversation toolbar. A standalone button opens the sidebar.
The sidebar contains the Theos name, theme button, settings, and conversation actions.
Desktop retains its header and conversation toolbar.
The background tint starts along the full bottom edge at 26% opacity in light mode and 12% in dark mode.
The light tint fades through a 9% middle stop. The dark middle stop uses 5%.
The top-corner tint uses 3% in light mode and 2% in dark mode.
Sidebar and dialog fills use 26% opacity in light mode and 28% in dark mode.
Their optical layers use a 7px blur with rim refraction in Chromium, or a 9px CSS fallback.
Opening a pane animates its edge highlights. Pointer interaction moves the local light position.
The refined highlight mask measures 0.75px and uses short arcs with softer permanent borders.
Controls inside these surfaces use simple fills.
Twenty native browser checks covered the upward mode menu and settings across five widths in both themes.
Mode checks covered adjacent icons, selection, arrow keys, Home, Enter, Escape, and restored trigger focus.
Tab closes the mode menu and advances focus to the message input.
All menus stayed above the composer and within the viewport. Microphone and send retained their 8px gap.
At 320px by 500px, expanded settings scrolled 551.5px inside the fixed optical frame.
Settings and saved research close the mobile sidebar before their dialogs open.
Closing either dialog restores focus to the sidebar button.
JavaScript syntax, formatting, and whitespace checks still pass.

Model and reasoning pickers use glass listboxes above the dialog's scroll frame.
Checks covered field alignment and viewport bounds at 320px through 1440px in both themes, including a 500px viewport height.
Model changes updated reasoning choices. Escape closed only the picker, and Cancel restored the saved choices.
An isolated conversation saved `gpt-5.6-luna` with low reasoning, then restored `gpt-6-luna` with default reasoning.
No model request ran during this settings check.
Model, reasoning, message-mode, add-options, and command menus retained 4px between adjacent rows during selection changes.
Focus rings measured as inset shadows, without paint outside the option. The selected model and adjacent focus row remained separate in both themes.

The local microphone check activated three animated waves and measured a smoothed voice level of 0.840.
Cancel cleared the recording state and volume styles and stopped all three wave animations before transcription.
A synthetic audio test checks volume response, silence decay, audio-resource cleanup, and reduced-motion behavior without microphone capture.

The header's private-workspace label and dot are absent. Status feedback stays inside the composer.
Native checks verified rotating idle prompts and the focused **Start Typing...** placeholder.
At 320px, empty placeholders stay on one line and drafts wrap without horizontal overflow.
Microphone and send retain an 8px gap. Light user bubbles and the send button share `rgb(51, 101, 78)`.
Dark user bubbles retain their previous fill.
A synthetic recording test covers transcription progress, successful insertion, existing drafts, failure, and cancellation.
Successful transcription clears feedback without a readiness note. Failed transcription preserves the draft and error.

Usage views and Connections now share the glass material with the top navigation.
Native checks covered desktop usage and 320px mobile usage and Connections without horizontal overflow.
The seven-day picker reloaded all charts. Optical filters remained bounded at 23 after the usage refresh.
The usage header retained its themed logo and return button after 662px of internal scrolling.
Returning to chat preserved the conversation. Dark Connections displayed three account cards and eight workspace services within the viewport.
The chart fixture covered 90 days, eight models, long identifiers, and missing prices with synthetic data only.
Chart tests cover price gaps, small costs, keyboard selection, redraws, grouped rankings, exact rows, and empty states.
Glass tests cover top-navigation decoration, detached-filter cleanup, mouse hover tracking, and touch-only press feedback.
Interface labels use sentence case. No uppercase text transform remains. User content and technical identifiers keep their original case.
Phone prompts use three short words. A 320px check kept the input at 44px without overflow.
The philosophical rotation fits at 320px with a 14px idle placeholder. Typed text remains 16px.
Focus retained **Start Typing...**. Resizing to 1280px restored the longer desktop prompts.
The composer regression test covers both prompt sets and viewport changes during focus.
Saved user and assistant messages display the local year, verified as **17 Oct 2026 18:58** in the browser.

## Philosophical personality and approved speech, 2026-10-17

The full local application suite passed 1,131 tests, with three credential-dependent tests excluded.
The separate speech gateway passed 11 checks locally and on the M4 Mac mini.
Both packages built, dependency locks validated, and Python lint, formatting, JavaScript syntax, and whitespace checks passed.

Browser playback and speech tools now prepare expressive spoken wording before synthesis.
Checks cover ownership, conversation usage, unchanged history, rejected numeric edits, empty and truncated output, unexpected tool calls, and preparation failure.
Preparation failure does not send plain source text to Kokoro.
The gateway checks cover authentication, upstream failures, decodable MP3 output, short replies, silence, output bounds, and serialized synthesis.

Live `gpt-6-luna` probes through the configured OpenRouter provider produced spoken phrasing with contractions, pauses, and emphasis.
The final three writing probes took approximately 1.8 to 4.3 seconds.
Live gateway calls on the Mac mini returned 6.6 to 7.5 seconds of MP3 audio in approximately 2.0 to 2.3 seconds.
The processing chain correlated at 0.9998 with the user-approved subtle audition when given the same source waveform.

Whisper retained the first two probes' meaning. The numeric probe retained all written values before synthesis,
but its audio transcript rendered `2500 USD` ambiguously. Direct, unprocessed Kokoro audio produced the same ambiguity.
Human verification of numeric pronunciation remains open. This is not a confirmed effect-processing regression.

These probes used an isolated candidate directory on the Mac mini. They sent no Telegram messages and changed no deployed assistant configuration.
The normal release process must activate the personality, expressive writing, gateway URL, and private speech key.

## Release 0.1.9 preflight

The combined research and shared-skills code passed 950 deterministic tests, with three live tests excluded.
The Pi retained healthy release `rpi-v0.1.8` during preparation.
Read-only Telegram authentication and polling checks passed. Public readiness and the private Jaeger services API also passed.
The Pi runner is online. Shared skills are mounted read-only, and the private environment has mode `0600`.
The environment has no legacy context or model-call overrides. Provider capacity and proportional research allowances can use their defaults.
Release `rpi-v0.1.9` deployed through workflow `38144121306` after one automatic rollback and a configuration correction.
Preflight had created an empty `/data/skills` directory in the candidate volume, which backup restore correctly rejected.
The corrected read-only mount at `/skills` leaves the candidate data volume empty until restore.
A disposable rehearsal verified that mount and restored the existing backup with a passing SQLite integrity check.
The retry used the same immutable image and tag. The failed attempt and backup remain available.

Post-deployment checks passed package version 0.1.9, schema 10, SQLite integrity, and all three research tables.
Browser-token authentication passed, and anonymous API access remained rejected.
A live model probe returned `RELEASE_OK` without creating conversation records or sending Telegram messages.
Telegram authentication and polling checks, public readiness, and the private Jaeger services API passed.
The running container reads all eight shared skills through the read-only `/skills` mount.
The installed terminal client reports version 0.1.9 and passes startup and dependency checks.

## Pi Jaeger through Tailscale Serve

On 2026-10-11, the Pi enabled persistent HTTPS Serve on port 8443 for its loopback Jaeger viewer.
The endpoint is `https://neuralbox-pi.tail61f0ca.ts.net:8443/`.
The operator group currently contains `parth-shastri@github`.
Tailscale accepted seven policy tests before saving the restriction.
These tests cover operator access, nonoperator denial over IPv4 and IPv6, and other service access.
The nonoperator sources are synthetic policy-test addresses. No live nonoperator device was available.
The Mac received HTTP 200 from the viewer with successful certificate validation.
The Jaeger v3 services API returned `theos`. The viewer displayed the existing four-span Pi trace `ff2e20f09a5c2efd423cddf0c87844a3`.
Serve status contains only the HTTPS proxy and no Funnel configuration.
Jaeger port 16686 and OTLP port 4318 still listen on host loopback.
SSH access and public Theos readiness passed after the policy change.
Seven-day retention, application data, model instructions, and the deployed application release remain unchanged.

## Explicit deep research and protected final summaries

PR #42 adds a turn-specific research mode, saved SQLite research records, and the browser Research view.
Normal queries receive focused delegate briefs and protected final summary capacity without research records.
The final suite passed 948 tests, with three credential-dependent live tests excluded.
Application lint, formatting, JavaScript syntax, lock validation, and package builds passed.

Deterministic checks cover explicit entry points, normal follow-ups, source and conversation ownership, full reports, source extraction, and restart persistence.
They also cover replaced notes, repeated summaries, missing reference rejection, original user corrections, and parent and delegate final summaries after exhaustion.
Small and concurrent budgets stay within the shared ceiling.
Proportional checks cover omitted counts, independent explicit overrides, configurable ratios, and totals from one to 100.
A 50-call runtime check enforces 17 research and handoff calls for each of two concurrent delegates.
The parent and delegates consume 36 shared calls in that check; summary and final reserves remain within the total.
At 30 calls, automatic defaults retain 24 research, five summary, and one parent response slot.
At 50, they derive 40 research, nine summary, and one parent response slot.
For agents, only the provider output parameter enforces generation length. Application code does not cut answers.

The local ARM64 Docker test instance on port 8082 passed readiness with migration 010 and the existing persistent test volume.
A real OpenRouter browser turn researched Python sorting against official documentation.
It saved a plan, complete source text, a finding with source IDs, and a cited report.
One source extraction failed. Later source reads succeeded, with the largest saved source containing 187,428 characters.
The Research dialog displayed the report and saved records.
A normal follow-up returned `NORMAL_OK` without creating another research run.
The model did not require context compaction during this live check. Forced summaries use deterministic harness tests.
This check does not confirm deployed Telegram, Pi release, or real-model summary accuracy.

See [research behavior](deep-research.md) and the [call budget map](call-budgets.md).

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
| Rolling summary, history retrieval, and bounded research delegates | `harness/compaction.py`, `harness/tools.py`, `runtime/`, `services/research/` | `test_compaction.py`, `test_text_summary_state.py`, `test_integrations.py` |
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
| Sandbox creation, reconnection, expiry, destruction | `services/sandbox/` | Lifecycle and owner isolation in `test_sandbox_recovery.py`, `test_integrations.py` |
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

## Google Health vitals, 2026-10-24

New Health consent verifies the linked profile before saving credentials.
Four connection cases cover success, an empty identity, a missing profile, and a service outage.
Failures retain the previous credentials. The check adds no scope or account identifier to model context.
The expanded focused suite passed 82 Health, browser account, OAuth, staging, integration, and Telegram cases.
A local combination with the shared connection flow in PR #108 passed 1,053 Python tests, with three live checks deselected.

The importer now reads daily HRV, SpO2, respiratory rate, and sleep temperature.
It also reads heart rate, HRV, SpO2, core temperature, glucose, and sleep breathing samples.
Daily provider values remain separate from sample statistics. RMSSD and SDNN retain separate fields and millisecond units.
Default tool summaries include vitals and counts of days with readings. Selected metric reads retain only the requested categories.
Cache version checks refresh older summaries on tool and Telegram reads. Telegram sends complete summaries through its existing splitter.

The v4 field names and units were checked against Google's public discovery schema, revision `20261021`, and vitals reference.
The focused suite passed 63 cases across Health contracts, integrations, result staging, OAuth, and Telegram onboarding.
Checks covered pagination, duplicate readings, invalid values, local dates, cache upgrades, owner isolation, and failed-import preservation.
Telegram checks reconstructed a complete response longer than 4,000 characters from its delivered parts.
Configured lint, formatting, whitespace checks, and package builds passed. The wheel includes the new vitals normalizer.
These checks used fixtures. They did not query a connected Health account or deploy a release.

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
| Transcription and Kokoro | Transcribe audio and play generated speech | Mac mini inference, gateway encoding, and transcription checked on 2026-10-17. The user approved the subtle audition. Numeric pronunciation needs a listening check. Deployed Theos voice delivery remains pending |
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

Parents and delegates share provider capacities and compaction at 70 percent of the configured context window.
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

The shared-default follow-up passed 891 tests, with three credential-dependent live checks excluded.
Four added checks cover the shared fallback across entry points and summaries without a generation cap.
Known output settings still take precedence. Small-window fixtures use explicit output settings.
Ruff checks, formatting, and source and wheel builds passed.

## Pi configuration, provider failures, and approval reviews

The 2026-10-11 local update sets the output default to 8,192 tokens and the compaction trigger to 70 percent.
The private local Pi environment uses a 100,000-token context cap. Explicit conversation output settings and trigger ratios retain precedence.
Release 0.1.10 preparation on 2026-10-12 passed 973 deterministic tests, with three live tests excluded.
Provider checks cover HTTP failures, timeouts, broken streams, OpenRouter stream errors, compaction failures, final-response failures, and failed delegates.
Failed generations withhold answer text. Failed turns preserve evidence in storage without returning raw findings as answers.
Approval checks cover unchanged snapshots, nested fields, multiline code, Markdown, Unicode chunks, and buttons after the complete review.
An isolated browser with synthetic approvals passed desktop light and dark checks and a 390px mobile check without horizontal overflow.
Python style, browser syntax, Prettier, lock validation, and package builds passed.
Live provider and Telegram checks and deployment to Pi were pending at release preparation.


## Unified context and workspace validation, 2026-10-12

This section supersedes the earlier local context-recovery prototype and its test results.
The implementation uses one pinned compression policy, with Theos adapters for model calls, saved sources, and workspaces.
The old complete-evidence chunk compressor, tokenizer preview policy, and fixed repeated-retrieval cutoff are removed.
Theos call allocations and research deadlines remain disabled. Their configuration and optional bounded mode remain available.

The full suite passed 990 tests, with three credential-dependent tests excluded.
The checks cover protected head and tail, tool-call pairing, distributed samples, iterative summaries, provider usage anchors, and summary failures.
They also cover provider capacity parsing, native output requirements, source ownership, pending transfers, uncertain actions, and workspace restoration.
The suite replaces obsolete chunk-count assertions with tests for the single-summary policy.
Changed Python files pass Ruff and formatting checks. Lock validation and package builds pass.
The compression license and source manifest ship in the wheel.

### Actual Pi failure replay

The replay used the captured Pi conversation and the live configured model through the existing OpenRouter adapter.
It preserved every original message and used only local history retrieval tools.
It made no new Gmail queries and sent no Telegram messages.
With one configured total call and zero configured summary calls, enforcement remained disabled.

The final replay completed 10 model requests and 37 history tool calls.
It recovered all nine expected purchases for September 12 through October 12, with correct separate currency totals.
All expected source reads, named merchants, and selected individual amounts passed.
Estimated input plus reserved output remained within 100,000 tokens for every request.
Tool-output pruning supplied enough space, so this replay needed no auxiliary summary call.
Separate deterministic tests exercise successful iterative summaries and failed auxiliary calls.

An additional fault-injection replay rejected the already-pruned request without reporting a smaller provider capacity.
It did not produce a useful answer. The compressor could not safely make that small request smaller.
The runtime now preserves this failure category and does not retry the same rejected request through a second response path.
The pinned upstream recovery also stops when compression cannot reduce a rejected request.
This test does not support a universal no-failure claim.

### Live R2 and sandbox checks

A disposable workspace calculated the expected total and saved nested input/output files in R2.
The first check exposed the SDK's shallow default directory listing. The recursive traversal fix passed the repeated check.
A separate live model task received the recovered report and a request for a PDF, without an explicit sandbox instruction.
The model chose the sandbox, copied the complete source, ran calculations, and produced a two-page PDF.
All expected totals, selected amounts, and named merchants passed text extraction checks.
The source, script, and PDF had saved R2 object states.

After sandbox destruction, a replacement sandbox restored the PDF byte-for-byte from saved workspace objects.
An independent PDF reader detected an incorrect cross-reference pointer in the generated file.
The validation step normalized that table, checked the corrected file with strict parsing, and saved another R2 version.
This artifact correction does not establish that every generated document will pass independent validation without repair.

Private exports, reports, expectations, credentials, and service-test outputs remain outside the repository.
These checks cover saved-evidence recovery and report creation. They do not cover new account consent, fresh Gmail queries, or Telegram delivery.
The Pi was last confirmed on `rpi-v0.1.10` at revision `67cccab0add9249a564790e1edaee54ebf9531ba`.
The current changes remain local and are not deployed.

## Text summaries integrated with recovery, 2026-10-13

The integration stays on `fix/context-overflow-recovery` and uses the pinned Markdown summary template.
Generated summaries do not use JSON. The obsolete research JSON validator is removed.
Code supplies exact anchors, owned research IDs, and recorded unknown outcomes independently of summary prose.
Requests receive a bounded index. Saved memory retains the full index across context updates and provider changes.
Lean remains the default tail. The larger current tail and recent user count are configurable.
Theos call budgets and research deadlines remain disabled by default. Summary calls still enter usage records.

The full local suite passed 1,006 tests, with three credential-dependent tests excluded.
New checks cover fresh and iterative text templates, model-written reference replacement, missing IDs, and 350-record indexes.
They also cover both tail modes, retained user messages, credential redaction, and excluded opaque provider data.
Storage checks cover publication before answer generation, SQLite rollback, delegate isolation, and full references after R2 restoration.
Changed Python files and CI style targets pass Ruff and formatting checks. Lock validation and package builds pass.
The context guide's prose lint reports 1.17 findings per 100 words.

The prior recovery replay and workspace results above belong to the baseline recovery implementation.
This summary integration did not repeat those live checks. It is not deployed.


## Full request fit and approval display, 2026-10-14

This update stays on the existing recovery branch and PR #55.
The full local suite passed 1,025 tests, with three credential-dependent tests excluded.
The tests cover successful, oversized, truncated, and failed summaries followed by full request checks.
Four consecutive provider overflows recover with smaller requests and one tool execution.
Other checks cover opaque replay cuts, pending parallel calls, active user corrections, required schemas, and irreducible inputs.
Saved transcript, uncertain outcomes, source ownership, transaction rollback, and checkpoint restoration tests still pass.

Compaction events reach parent and research clients without private summary prose.
Browser tests cover separate compression identifiers, cancellation, and stream disconnects.
Telegram tests check editable tool status, compaction status, complete reviews, topic routing, and Unicode entity offsets.
Zepto cart tests show `3900` as `₹39.00` while preserving raw prices, quantities, identifiers, and approval snapshots.

Changed Python files and CI style targets pass Ruff lint and formatting checks.
JavaScript syntax, Prettier, lock validation, package builds, and whitespace checks pass.
The context guide's prose lint reports 1.14 findings per 100 words.
A local mock preview used the real approval fields, browser component, stylesheet, and Telegram text/entities.
Desktop and 390-pixel phone layouts passed visual inspection. Expandable details expose raw paise and identifiers.
This preview did not send Telegram messages, call Zepto, or approve an action.

No fixed count stops fit cuts or provider context retries.
Recovery stops when no smaller safe request remains. Required content can still exceed a provider window.
Unavailable providers, canceled turns, and failed persistence remain distinct failure conditions.
These changes remain undeployed. Live Telegram approval and provider acceptance checks remain pending.


## Latest fit loop live replay and 0.1.11 preparation, 2026-10-14

The replay used the original captured Pi session with the latest request fit implementation.
It used the configured live model and local history tools, without production database writes, new connector queries, or Telegram delivery.
Theos call budgets remained disabled. Every attempted request fit the configured 100,000-token window with 8,192 tokens reserved for output.
Both successful runs preserved the original transcript and recovered all nine expected purchases with separate currency totals.

The first normal run returned the expected facts but did not reread all earlier receipts.
The replay checker also failed to recognize two original reads made by tool call ID.
The corrected checker accepts message indices, tool call IDs, and resolved original indices, while requiring successful history reads.
A stricter normal repeat explicitly required original evidence before totals. All 21 checks passed, with seven model requests and 17 history calls.

The fault-injection run rejected four consecutive requests without reporting a smaller provider window.
All 23 checks passed, with 21 model attempts and 36 history calls.
The five requests across those rejections decreased from 4,054 estimated input tokens to 804.
The runtime completed five compaction operations without a failed compaction event.
The run read all nine required original receipts. Only local history tools executed.
These replays needed no auxiliary summary call. Deterministic tests still cover failed and oversized summary output.
Private sessions, instructions, answers, logs, and expectations remain outside the repository.

The full release preparation suite passed 1,032 tests, with three credential-dependent tests excluded.
Python style, browser syntax, lock validation, package builds, and whitespace checks passed.
The release draft's prose lint reports 0.76 findings per 100 words.
Version 0.1.11 prepares the current recovery, summary, workspace, and approval changes for promotion.
The existing private local Pi environment needs no changes. Context, output, and trigger settings remain 100,000, 8,192, and 0.7.
Deployment confirmation belongs to the tagged release workflow. The replay does not establish live Telegram delivery.


The first Pi promotion CI run exposed a timing race in the bounded write-timeout test on Python 3.12.
Setup could exceed 150 milliseconds before the tool started, which correctly records failed rather than unknown status.
The corrected test expires research after the write starts and uses a separate 50-millisecond tool timeout.
It patches application clocks only, leaving the event loop clock intact. Production behavior does not change.

## Temporary Telegram activity and approval notifications, 2026-10-14

The local suite passed 1,045 tests, with three credential-dependent tests excluded.
Finished tool and compaction messages disappear. Final stats include elapsed time, call count, outcomes, and successfully loaded skills.
Runtime checks include delegate calls and display queue overflow without losing counters.
Transport checks cover complete answers, partial answers, failures, cancellation, topics, and failed message deletion.

Approval checks cover one notification per card, complete multipart reviews, attached reviews, and duplicate progress events.
Approved and denied cards disappear after decisions. A replacement bot reads saved message references and removes the complete review.
Polling removes expired cards and cards resolved by another client. Failed deletion removes buttons and retains references for another attempt.
SQLite retains original approval snapshots and decisions. Existing recovery and transcript checks still pass.
Python lint, formatting, and whitespace checks passed. These changes have not deployed or sent live Telegram messages.

## Recoverable tool batches and model feedback, 2026-10-14

The local suite passed 1,063 tests, with three credential-dependent tests excluded.
A 35-call response completed with batch sizes of one, eight, and sixteen. All call IDs and result order remained intact.
The direct executor also bounded parallel groups. Model requests included explicit oversized-batch feedback and instructions against resubmitting completed or uncertain calls.
Cancellation in a later batch retained earlier results and one unknown outcome. Resumption completed remaining calls without repeating that uncertain action.

A 17-action application check created every required approval. One approved action executed once while the other sixteen were denied.
Approval arguments and saved results retained their original identities. Invalid calls produced saved `not_started` results and allowed correction with new IDs.
Argument size, nesting, list size, schema, and unknown-tool checks stopped affected calls before execution.
Executed failures and uncertain outcomes retained distinct statuses. Duplicate IDs still stopped before any tool executed.

Trace checks retained the full 35-call count while content capture included only the first sixteen calls.
Log checks accepted only fixed harness error codes and excluded private values.
These checks used local fixtures. They did not query Gmail, send Telegram messages, or deploy the change.

## Sandbox recovery, approval policy, and skill selection, 2026-10-14

The final full local suite passed 1,091 tests, with three credential-dependent tests excluded.
Skill checks passed with multiline descriptions and captured first-request instructions. Python lint and whitespace checks passed.
Approval checks cover the global Zepto-only policy and retirement of old pending cards without execution.
Sandbox checks cover fixed creation deadlines, concurrent replacement, reconnect, transient failures, and explicit lifecycle actions.
Workspace checks restore saved files before scanning a replacement instance.
Transient failures retain the saved sandbox reference and do not replay commands.

The Pi preflight passed on revision `363c4aa` before merge.
It changed the private deployment environment to a 3,600-second sandbox lifetime and updated installed document styles.
The disposable live probe verified remote creation, unchanged cached expiry, confirmed missing-instance replacement, and a successful command afterward.
The probe removed its temporary sandbox. It did not change production conversation records or send Telegram messages.
See [the preflight run](https://github.com/parth-shastri/theos/actions/runs/38507638730).

Skill checks expose installed descriptions for selection by task intent without loading unrelated workflows.
Document requests receive actual installed report-style and format instructions before the first model request.
This validation does not establish real-model workflow selection or a completed styled document.
Tag deployment still must pass the ARM64 image, backup, readiness, restart, and rollback gates.

## Gmail send approval correction, 2026-10-14

Version 0.1.13 restores explicit Gmail send approval after the 0.1.12 policy change.
The full local suite passed 1,095 tests, with three credential-dependent tests excluded. Python lint, formatting, and whitespace checks passed.
The focused account, policy, browser catalog, and regression checks passed 54 tests.
They verify no send before approval, one unchanged approved send, denial, and rejection after a draft edit.
A separate check verifies that the service guard rejects a send without the active approved call.
The final draft check also rejects edits between approval resumption and send execution.
Duplicate approval decisions cannot send the email again.

## Shared skill sandbox runtime, 2026-10-15

The ARM64 image `theos/sandbox-skills:v1.1.0-20261015` was built on the Mac mini and configured for new OpenSandbox instances.
The dependency audit covered all eight installed skills: XLSX, PDF, arXiv search, Hugging Face papers, DOCX, Papers with Code, report style, and code review.
The image includes the required Python libraries, LibreOffice, Pandoc, Poppler, Tesseract, Chromium, Node.js, `agent-browser`, and the pinned Papers with Code CLI.
Report style assets and builders live in the image at `/opt/theos/report-style`; `report-style` now instructs the model to construct and deliver the requested report.
Workspace actions are exposed as ordinary tools such as `run_command`, `read_file`, and `browser`; model-facing workspace instructions do not identify the execution backend.

An authenticated Theos-to-Mac OpenSandbox run verified the Python kernel packages, paper and document CLIs, styled PDF and DOCX generation, LibreOffice conversion, XLSX recalculation, OCR, browser navigation, and sandbox file return under the existing one-CPU, 512 MiB limit.
The Pi now reads the new image setting. Theos returned ready on its original data volume, and the existing SQLite database passed its integrity check.
The Mac mini OpenSandbox health endpoint returned healthy. These checks did not send Telegram messages or verify a live report request through the model.
These checks use HTTP mocks and send no real email. No environment change or migration is required.

## Workspace lifecycle recovery, 2026-10-15

The runtime handles workspace reconnection, confirmed expiry or loss, and checkpoint restoration before exposing a workspace operation to the model. A connection failure before the operation begins tells the model that it may retry the same ordinary tool call once. The model does not need to invoke lifecycle controls for recovery.
Failures after an operation starts remain distinct: if checkpointing fails, the tool reports an unknown outcome and tells the model not to repeat the operation automatically.

## Runtime latency and safe replication, 2026-10-14

The complete local suite passed 1,106 tests, with three credential-dependent tests excluded before the final retry-window test.
Focused checks also passed after that test and the diagnostic changes.
Storage tests cover blocked uploads, unavailable storage, worker restart, failed pointer publication, and transfer fairness across owners.
A blocked upload does not delay a newer local checkpoint.
Pending objects retain their local files and journal entries.
Remote pointers advance only after the corresponding objects are uploaded.
Recovery preserves unknown external actions and never repeats tools to repair storage.

Three mocked Gmail thread reads overlap while preserving their owner, result order, call IDs, and durable results.
Writes and approved sends retain sequential execution and existing approval checks.
Transient provider retries preserve the exact request and ZDR.
A completed tool executes once across two injected provider failures.
Partial output and a long failed stream do not restart generation through this path.
Diagnostic tests reject private provider prose, raw metadata, and malformed identifiers.
Timing tests check phase ownership, HTTP headers, first-chunk timing, and request identifiers.

The Pi preflight used the edited code under a temporary source path and a separate temporary database.
Five synthetic checkpoints took 16.9 to 17.7 milliseconds each. R2 replication completed in 4.11 seconds afterward.
The bucket contained no remaining probe objects after cleanup.
A live provider request with no tools returned the expected marker in 12.10 seconds.
It sent no Telegram messages and changed no production session records.
The Pi Connect package is 2.13.0 and its resident-memory guard is active.
Application deployment confirmation still requires the tagged release workflow and active Pi manifest.

The final source PR passed 1,108 tests on Python 3.12 and 3.13 before the remote-restore correction.
Additional restore checks cover snapshots with unanswered calls and snapshots before any call intent.
Saved working context and ordinary history both retain one uncertain result per unresolved call.
Tool access stays paused until explicit operator reconciliation, even if a caller bypasses the empty registry.
Other owners cannot confirm that review. Local process recovery keeps its existing behavior.

## Provider routing and latency, 2026-10-14

The provider records attribute the 143.049-second and 378.893-second calls to one Azure endpoint generation each.
Their reasoning usage was 199 and 808 tokens. Their native input usage was 20,575 and 40,952 tokens.
Both used the default service tier and completed with tool calls.
The provider catalog currently reports medium default effort. Pi does not request a higher effort.

The 51,079-token synthetic probe kept medium reasoning and the 8,192-token output allowance.
Automatic routing took 2.94 seconds. The preferred Azure EU profile took 2.96 seconds.
The same request forced to the base Azure endpoint took 38.46 seconds with a cache hit and only 27 output tokens.
The probe executed no tools and wrote no production records.
A separate saved-history probe retained all 39 messages and signed reasoning, then returned the expected marker in 9.65 seconds.
It generated no tool calls and executed no actions.

Routing tests preserve ZDR, signed state, tool results, output limits, and explicit endpoint allowlists.
Trace tests expose fixed request controls and counts without private bodies or arbitrary options.
Reasoning usage remains part of total output usage. It does not increase cost accounting.
Existing tests retain single execution across provider retries and paused tools after remote restore.
The full local suite passed 1,116 tests, with three credential-dependent checks excluded.
Tagged deployment and the active Pi manifest must confirm application activation.

The automatic-routing correction checks encoded requests for all seven OpenRouter model aliases.
Every request retains ZDR and generic performance preferences without an endpoint order.
Runtime configuration contains no model-specific order map. No provider call is required for these checks.

## User reports and report typography, 2026-10-18

Local browser scenarios exercised public-source research and read-only Gmail spending analysis.
The research parent now retains workspace tools to create and deliver requested documents.
Delegates retain their separate read-only tool set.

The first document runs exposed binary corruption in bounded sandbox reads.
The SDK limit counted lines rather than bytes. Byte ranges now preserve PDF, DOCX, PNG, and checkpoint content.
The focused recovery and integration checks passed. The full local suite passed 1,021 tests before the report wording and font changes.
CI also passed on Python 3.12, Python 3.13, and ARM64.

After the transfer fix, one deep research turn delivered a four-page PDF and an editable five-page DOCX.
Both files passed structural checks. Native Word rendering retained the diagrams and active source links.
A synthetic spending scenario verified refunds, duplicates, pending transactions, malformed amounts, date boundaries, and separate currencies.
An independent audit matched the earlier mailbox report totals to its transaction CSV and inspected source bodies.

The earlier 100-header and 30-body limits came from the acceptance prompt.
Production instructions now require task-driven pagination and relevant body, thread, and attachment reads without an invented total allowance.
An uncapped scenario retrieved 181 unique headers across 21 search results and completed 34 message-body calls.
A provider timeout interrupted delivery. Recovery reused the saved workspace and retried outstanding message reads.
Recovery delivered a three-page PDF with daily spending bars and a category comparison, plus the transaction CSV.
All pages passed visual inspection. Font inspection confirmed Space Grotesk in the report and chart labels.
The delivered CSV matched the independently audited snapshot: 33 rows, separate currencies, and no repeated purchase keys.
The audit matched counted amounts to retrieved bodies or source headers. One counted row relied on two retrieved headers.
Password-protected or unavailable statement attachments remain explicit coverage limitations.
No scenario used Gmail write tools.

Report instructions now lead with findings, implications, and actions for the user.
They exclude agent activity logs from the main report and select useful visuals without a separate user request.
The first natural-language visual scenario still produced tables without a diagram.
The revised skill explicitly requires a diagram for choices or multistep processes and a chart for supported spending comparisons.
A fresh request for a concise decision guide did not mention visuals.
The completed response included a decision diagram in both its two-page PDF and editable two-page DOCX.
All four rendered pages passed visual inspection. Word retained the editable prose and tables.

Report builders now use bundled Space Grotesk for prose, tables, headings, and diagram labels.
PDF HTML embeds its font data. DOCX embeds regular and bold font parts.
The sandbox installs the same font for charts and document conversion. Code retains its monospace face.
The font data comes from the existing browser asset and needs no runtime CDN request.

An isolated ARM64 acceptance image rendered both formats under the existing one-CPU, 512 MiB sandbox limit.
PDF font inspection confirmed Space Grotesk in both the PDF and native Word conversion.
A separate Word conversion on a host without the font installed also used the embedded Space Grotesk faces.
The rendered smoke pages passed visual inspection. The focused prompt and identity checks passed 24 tests.
The configured CI lint and formatting checks passed. No additional pytest cases were added.
CI passed on Python 3.12, Python 3.13, and ARM64 for the font commit `4d24332`.

A separate chart scenario used a synthetic CSV with 22 rows across three months and two currencies.
The request asked for spending analysis and did not mention charts or diagrams.
The completed two-page PDF contained stacked monthly category bars and a separate USD chart.
All 26 derived CSV rows matched independent calculations of gross expenses, refunds, and net spending.
Transfers were excluded and currencies retained separate scales. Chart labels matched the derived totals.
The geometry check caught two truncated tick labels: 2,500 and 7,500 appeared as `2k` and `7k`.
The correction uses `2.5k` and `7.5k`. Both PDF pages and the standalone chart preview passed inspection after correction.
Independent geometry checks verified the tick values, all 12 INR stack segments, and all three USD bars.
Space Grotesk covered the prose and chart labels. Only unsupported currency and arrow glyphs used fallback fonts.
The corrected standalone SVG embeds its font data. The derived CSV remained byte-for-byte unchanged.
An uncertain workspace checkpoint interrupted delivery. Recovered files passed validation without repeating the generation command.
The cause was the acceptance image tag being rebuilt while a sandbox still referenced its old image record.
Docker Desktop removed that record. OpenSandbox status returned HTTP 500, while direct execution and file reads still worked.
The local runtime now uses a distinct revision tag. Keep referenced image records until their sandboxes expire.
A fresh sandbox using that revision delivered the verified PDF, chart PNG, and CSV through normal Theos tools.
All three delivered files matched the verified sources byte-for-byte. PDF structure and PNG decoding also passed.

The local application uses the updated prompt image and the isolated font runtime for new sandboxes.
At this stage, PR #86 was open. No connector PR, production deployment, or branch promotion had merged.

## Final sandbox candidate and Docker cleanup, 2026-10-19

The ARM64 image `theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3` built from the shared runtime Dockerfile.
Its local image digest is `sha256:977e17829f78f5aee9c02bab0d1ec3457688c37093b181f4fae37875ab34a311`.
A fresh sandbox passed creation, status inspection, file transfer, execution, and destruction through OpenSandbox.
The checks used the normal one-CPU, 512 MiB resource request.

Matplotlib generated bar and line charts with checked values and accurate axis labels.
Space Grotesk was the default chart font. SVG exports used text paths.
The PDF and editable DOCX contained both a chart and a decision diagram.
Both rendered pages passed visual inspection. Font inspection confirmed Space Grotesk in both document conversions.
Spreadsheet formula recalculation, OCR, Chromium automation, and Papers with Code checks also passed.
A separate fresh Python kernel imported Matplotlib and pandas and returned the expected result.
The existing integration and sandbox recovery tests passed 14 cases.

The local application now selects the final sandbox image. Its data volume and generated files remain intact.
The Mac mini cleanup removed three test sandboxes, four obsolete image tags, and temporary build directories.
Docker reported 32.09 GB of removed build cache. No service volume was pruned.
Mem0, its dashboard, PostgreSQL, Kokoro, and Whisper remain running.
The previous production sandbox image remains available for the Pi. The Pi environment remains unchanged.
At this stage, PR #86 was open. No branch promotion or Pi deployment had occurred.

## Navigation visibility in both themes, 2026-10-19

The collapsed mobile topbar now uses the existing light-mode layout in both themes.
Dark sidebar labels, conversation titles, costs, and account text use brighter ink.
Text halos separate navigation labels from reflected content in both themes.
No blur, saturation, opacity, refraction, or glass material setting changed.
Computed sidebar and optical styles matched the baseline after excluding inherited color on a nonexistent border.

Browser previews at 320 and 390 pixels showed readable labels over normal, white, and green surfaces.
Both topbars retained their glass layers while messages scrolled beneath them. No horizontal overflow occurred.
The live 1280-pixel workspace retained its conversation list, costs, account, and stored report links after container replacement.
The served stylesheet matches the verified source bytes. The application readiness check passed.
The existing focused glass, composer, view, and replacement checks passed 12 tests.

The local container runs `theos:local-acceptance-navigation-20261019-74cc202` with the final sandbox image.
PR #86 merged into `dev` on 2026-10-19. Promotions and Pi deployment remain pending.

## Local OpenUI Docker replacement, 2026-10-21

The `feature/openui-browser` worktree built both native ARM64 images.
The local API runs `theos:local-openui-tested-20261021`. The frontend runs `theos-web:local-openui-final-20261021`.
All 42 application settings match `/Users/nightowl/my_projects/theos/.env`. Browser sign-in passed with that file's configured owner token.
The existing data volume retained 62 records and 111 files. SQLite integrity passed before and after replacement.
A consistent database backup preceded replacement.

The Python suite passed 1,025 tests, with five skipped and three live checks deselected.
Generated OpenUI artifacts, formatting, Python lint, four frontend proxy tests, and sixteen container browser scenarios passed.
Container smoke checks covered readiness, authentication, CSRF rejection, a 10 MiB file transfer, SSE chat, non-root execution, and history after restart.

Additional image checks covered exact summary values, safe links, four viewport widths, reminder defaults, edited drafts after reload, and form submission.
Owner isolation, invalid fields, malformed-source fallback, and user-triggered text recovery passed.
These checks found and corrected wrapped field values, missing untouched defaults, and summary initialization that cleared saved display data.
A live configured model returned a valid OpenUI answer without tools. The deployed browser rendered it and restored it after reload.
These results cover the local deployment. They do not establish Pi deployment or live reminder delivery.

## Mobile keyboard and turn activity, 2026-10-23

An injected zero-height keyboard measurement collapsed the previous application frame to zero pixels.
The corrected hook retains the last valid height and refreshes after focus changes and page restoration.
The application frame uses viewport positioning and layout containment instead of a full-frame transform.

The production Chromium suite passed 76 cases. The focused WebKit suite passed 20 cases.
Each suite skipped 12 mobile-only cases at desktop widths.
Checks cover repeated keyboard toggles, viewport panning, restored pages, preserved drafts, dialogs, navigation, and native pinch zoom.
A staged SSE fixture verifies continuous turn activity across model completions and tool events, with no run labels in the composer.
The label pulses and the orb glows during the turn. Reduced motion disables both animations.
Reducer checks cover completion, approval waits, failures, and disconnect cleanup. Errors remain visible.

The 12 focused Python checks and 15 Node checks passed.
Formatting, generated OpenUI validation, the production frontend build, and whitespace checks passed.
Mobile WebKit screenshots retained the composer, navigation, tool state, and active turn indicator.
Physical iPhone keyboard animation and Home Screen behavior still need confirmation. This change does not deploy a release.

## Native iOS Simulator viewport correction, 2026-10-23

The iPhone 14 Pro simulator on iOS 27.0 reproduced the reported blank keyboard view on the open installed site.
The initial PR #104 build passed its first Safari keyboard opening but failed a second opening with a draft.
Native measurements on iPhone 17 Pro Max identified the remaining offset cap.
Safari reported an inner height of 560 pixels, visual height of 447 pixels, and offset and root scroll of 236 pixels.
The cap used 113 pixels and placed the application frame at minus 123 pixels.
The corrected hook uses the full nonnegative visual viewport offset until Safari clears it.

On iPhone 17 Pro Max, the corrected frame stayed at zero pixels while Safari reported a 349-pixel offset.
The composer stayed visible with the full software keyboard. The draft survived dismissal and a second opening.
The iPhone 14 Pro was shut down before the iPhone 17 Pro Max checks, as requested.
Native screenshots and numeric measurements were saved outside the repository in the user's Desktop verification folder.
Temporary diagnostic requests were removed from the implementation after these measurements.
The final native checks cover Safari on iPhone 17 Pro Max. Final Home Screen mode and physical-device checks remain pending.

The final source passed 76 existing Chromium scenarios and four new Safari-offset regression cases in a targeted rerun.
The focused WebKit suite passed all 24 applicable cases. Sixteen mobile-only cases were skipped at desktop widths in each full matrix.
The 12 focused Python checks, 15 Node checks, formatting, generated OpenUI validation, and production frontend build passed.

## Keyboard background boundary, 2026-10-23

The ambient gradient ended at the application frame while the native keyboard gap used the plain document backdrop.
The document now keeps the theme canvas color. The frame paints the glow once and fades into that canvas at its bottom edge.
Native iPhone 17 Pro Max screenshots show the keyboard boundary in both themes without the previous hard green edge.
The saved theme now applies before React loads through a script with the existing request nonce.
Native Safari starts with the correct dark backdrop after reload. Its bar color can still remain stale during a live theme switch.
The bootstrap check blocks React scripts and confirms the saved theme takes precedence over the system theme under the production CSP.
The final source passed 48 focused Chromium cases, 24 focused WebKit cases, 12 Python checks, and 15 Node checks.
Each browser matrix skipped 16 mobile-only cases at desktop widths. Formatting, generated OpenUI validation, and the production build passed.

## Unified command tools and private browser, 2026-10-26

New tool registries expose `run_command` and `attach_file` for workspace work.
History read and search remain separate. The former catalog, transfer, Python-kernel, browser-wrapper, and image-view tools are absent.

The Python suite passed 1,064 tests. Three credential-dependent live checks remained excluded.
Checks covered automatic input staging, file deletion across replacement, image pixels in model requests, restart recovery, and immutable attachments.
Remote attachment recovery retained the original bytes and file ID. A failed R2 download left the session empty for another restore attempt.
Browser checks covered owner isolation, separate conversation tabs, encrypted profile storage, and private sign-in routes.
A snapshot-process failure resumed the monitored browser process through the independent watchdog.
Lint, formatting, lock validation, and whitespace checks passed.

A local protocol check used `agent-browser` 0.38.1 with an isolated Chromium-compatible browser and a synthetic HTTP website.
Navigation, element references, form input, and screenshot transfer passed.
Cookies, local storage, and IndexedDB survived replacement through the profile capture and restore path.
The browser used no personal profile or production account.
These checks do not verify a deployed OpenSandbox transport, ARM64 resource limits, or Pi activation.

The frontend production build and all 18 frontend unit tests passed.
The Browser sign-in scenario passed at 320, 390, 768, and 1280 pixels in both themes.
The scenario verified private input, keyboard navigation, profile deletion, and the absence of chat turns.
Mobile and desktop screenshots passed visual inspection. No horizontal overflow occurred.

## Runtime checkpoint retention, 2026-10-26

The Python suite passed 1,075 tests. Three credential-dependent live checks remained excluded.
Eleven retention scenarios covered current workspace roots, response attachments, retained snapshots, and published recovery state.
Checks also covered grace periods, active sessions, recovery review, corrupt snapshot isolation, and bounded deletion backlogs.
R2 partial failures retained deletion jobs after restart. Recreated content survived an in-flight deletion without blocking local checkpoint writes.
The worker resumed replacement uploads after deletion completed. Interrupted uploads retained remote deletion intent when storage was temporarily disabled.
Uncertain pointer updates preserved every possibly published snapshot until a later update was confirmed.
Remote restoration registered its fetched checkpoint as a recovery root.

The Connections fixture now waits for sign-in completion before navigation.
The previous CI trace showed startup navigation replacing the Connections view before the Zepto Connect click.
All 40 Connections browser scenarios passed at four widths in both themes.
Frontend formatting and all 18 frontend unit tests passed.
Python lint, formatting, lock validation, package contents, and whitespace checks passed.
The wheel contains the retention service and migration 015. No generic harness source changed.
No deployed R2 objects were deleted during these checks.

## Telegram connector controls, 2026-10-26

Telegram onboarding now opens native sign-in cards for Gmail, Google Health, and Zepto.
Cards provide status, retry, cancel, and account navigation buttons.
Google callback confirmations include a button to return to the account list.
`/connections` and the existing account commands use these controls without creating conversations or model turns.

Zepto's localhost flow uses a **Paste return link** button and a native reply prompt.
Theos saves only recent prompt message IDs in owner-scoped records.
Prompt replies, plain callback links, and callback captions are encrypted before inbox persistence.
The handler consumes them outside model history and removes visible pasted messages when Telegram permits it.
Verification status hides the paste action after the one-use callback is accepted.
Setup cancellation preserves existing account credentials.

The full local Python suite passed 1,068 tests, with three live checks deselected.
The focused connector and transport checks passed 73 tests.
Checks cover delayed Zepto links, reply prompts, Google callbacks, expiry, denial, retry, cancellation, owner isolation, and plaintext redaction.
Configured lint, formatting, whitespace checks, and the Python package build passed.
No live Telegram message or provider authorization was used. Native device checks and deployment remain pending.

## Slack official MCP connector, 2026-10-15

The full local suite passed 1,156 tests, with three credential-dependent checks excluded.
The focused shared and Slack checks passed 34 tests.
They cover confidential user OAuth, durable single-use state, callback replay, encrypted restart access, and token refresh.
The Slack adapter uses a client secret without enabling Slack's public-client PKCE mode.
Other providers keep PKCE as the shared adapter default.
The default Slack scopes exclude private search and writes. Provider permission checks still apply to every call.
A private-search refusal remains a failed read. It returns no source page and does not expose private provider error text.
Tests also cover paged discovery, schema rejection, private transports, optional outages, and complete source ownership.
The shared wire check uses the real MCP client against a mock HTTP transport. It does not repeat failed reads.
Python lint, formatting, JavaScript syntax, lock validation, package builds, and whitespace checks passed.
The setup guide's prose lint reports 1.57 findings per 100 words.
These checks used local fixtures. Eligible app registration, workspace consent, live tool discovery, and deployment remain pending.


## Slack synchronization with main, 2026-10-28

The Slack topic branch merges main at c42b61a with both histories preserved.
The connector uses the current Next.js workspace, callback proxy, optional onboarding, and native Telegram controls.
Setup cancellation preserves the existing grant. Large reads use the current bounded result staging service.
The retired static browser app and connector source wrapper remain removed.
Provider assets retain their source notice and updated provenance manifest.

The full Python suite passed 1,139 tests, with three live checks deselected.
The focused account and transport suite passed 73 tests after the final adjustments.
All 18 frontend unit tests and 48 Chromium connection scenarios passed.
Browser checks covered four viewport widths and both themes, including Slack sign-in, cancellation, and callback restoration.
Lint, formatting, OpenUI validation, lock validation, package builds, and native ARM64 Docker builds passed.
Both isolated Docker services are healthy. Next.js uses localhost port 8080 and the private API uses port 8081.
The test retains its separate data volume and disables Telegram polling.

The saved Slack OAuth grant survived replacement and appears connected.
Live MCP initialization returned HTTP 400 and RPC code -32600 because the Slack app lacks MCP server access.
Enable MCP access in the app settings before repeating discovery and a read.
No Slack message was sent. Live provider reads and permission-removal acceptance remain open.


## Live Slack MCP discovery and channel search, 2026-10-28

The operator enabled MCP access in the registered Slack app.
The existing encrypted OAuth grant then passed authenticated discovery without reconnecting.
Five reviewed tools became available: slack_read_channel, slack_read_thread, slack_search_channels, slack_search_public, and slack_search_users.
A new isolated browser conversation ran slack_search_channels once with a one-result public-channel limit.
The provider returned one channel and isError=false. The tool and turn both completed in 8.84 seconds.
The existing journal and SSE delivery recorded one completed call. No Slack write tool ran.
Channel names, account credentials, and provider response contents remain outside these notes.
Private conversation access, permission removal, and live disconnection remain unverified.

## GitHub official MCP connector, 2026-10-15

The full local suite passed 1,153 tests, with three credential-dependent checks excluded.
The final focused suite passed 31 tests after the callback URI and Git tree toolset checks.
Checks cover encrypted account recovery, owner binding, PKCE, callback replay, cancellation, and token rotation.
They also cover refresh/disconnect races, session teardown, paged discovery, schema rejection, and private transport access.
A real MCP client read two discovery pages through a mock HTTP transport. A failed tool call executed once.
A scripted runtime read saved the complete result and returned a bounded source page. Other owners could not read that source.
An optional connector outage left ordinary chat available. Unknown tools and write tools remained unavailable.
Python lint, formatting, JavaScript syntax, lock validation, package builds, and whitespace checks passed.
The setup guide's prose lint reports 1.20 findings per 100 words.
These checks used local fixtures. Live GitHub App authorization, repository access, and deployment remain pending.


## GitHub synchronization with dev, 2026-10-28

Slack PR 75 merged into dev after all required GitHub CI checks passed.
The GitHub branch merges dev at f0e523a and retains the tested shared MCP account adapter.
GitHub now uses the current Next.js workspace, callback proxy, optional setup, composer mentions, and native Telegram controls.
Canceling setup preserves the previous grant. Large reads use the current bounded result staging service.
The removed static browser app and connector source wrapper remain removed. Provider attribution remains available.

The full Python suite passed 1,148 tests, with three live checks deselected.
The focused connector and transport suite passed 82 tests. All 18 frontend unit tests and 56 Chromium connection cases passed.
Browser cases covered GitHub, Slack, and Google sign-in, cancellation, and callback restoration across four widths and both themes.
Lint, formatting, OpenUI validation, lock validation, package builds, and native ARM64 API/frontend image builds passed.
The isolated Docker frontend and API are healthy on localhost ports 8080 and 8081.
Slack retains its connected grant and all five previously discovered read tools.
The GitHub frontend callback reaches the API and returns the expected invalid-state response for a synthetic state.

The private environment still lacks GitHub OAuth credentials. Live authorization, discovery, and repository reads remain pending.
These checks used mocked providers for GitHub. No live GitHub account was connected.


## Signed GitHub events and private notifications, 2026-10-28

The GitHub connector now receives signed POST /webhooks/github deliveries through the production Next.js byte proxy.
Migration 016 stores subscriptions, encrypted pending payloads, delivery IDs, private inbox notices, and Telegram delivery status.
Opted-in owners receive direct mentions, assignments, review requests, and failed workflows they triggered.
The worker verifies the current GitHub identity and repository access before routing and before a Telegram send.
Event content never starts a model turn. Browser and Telegram owners retain their existing identity boundaries.

The full Python suite passed 1,164 tests, with three credential-dependent checks deselected.
The 20 frontend unit tests and 64 Chromium connection scenarios passed.
Eight alert scenarios passed again after the final theme-color change at four widths in both themes.
Mobile previews passed visual review at 320 and 390 pixels. Tests use synthetic titles and provider fixtures.
The checks cover signatures, byte limits, changed payloads, duplicates, access revocation, opt-in revisions, and owner isolation.
They also cover queue restart recovery, uncertain Telegram sends, disabled-feature retention, and notification acknowledgement.
Lint, formatting, OpenUI validation, package builds, wheel contents, and native ARM64 API/frontend image builds passed.
Both isolated Docker services are healthy. SQLite schema 16 passed integrity checking in a consistent local snapshot.

A synthetic UTF-8 ping traversed the public temporary HTTPS tunnel, the webhook-only origin, Next.js, and the API.
A valid signature returned 202. The same delivery returned duplicate=true. A changed payload returned 403.
The tunnel returned 404 for the app root and /api/me, and 200 for its readiness route.
The operator authorized this temporary tunnel. Its processes, URL, and port are recorded only in the ignored local test folder.
A signing secret was generated in the ignored private .env. It was not included in source or build output.

These checks do not establish a real GitHub App delivery or a live Telegram send.
GitHub OAuth credentials, provider setup, per-owner opt-in, and actual event delivery still need live acceptance.
The production Theos deployment is unchanged. The temporary tunnel remains active for the requested local test.

## General evidence and pagination guidance, 2026-10-28

The shared chat prompt no longer contains mailbox-specific coverage rules.
General guidance requires enough evidence for the task and distinguishes partial coverage, estimates, and exact counts.
Gmail and shared MCP tool descriptions explain page limits and continuation parameters.
Staged-result guidance distinguishes a complete response from complete provider coverage.

The 86 focused prompt, account, connector, Gmail, checkpoint, and result-staging tests passed.
Ruff lint, formatting, and patch whitespace checks passed.
The local API image rebuilt successfully. Both Docker services returned healthy.
The running API exposes the updated GitHub and Gmail descriptions and retains both connected account grants.
The installed prompt and staging helper contain the new guidance.
These checks verify configuration and existing contracts. Model behavior after the prompt change remains unverified.

## GitHub live account reads, 2026-10-28

The operator created the GitHub App and authorized its localhost callback.
The local Docker workspace retained the encrypted account grant after restart.
Authenticated discovery exposed reviewed GitHub tools in the existing browser conversation.
The operator's repository-activity request completed identity, repository-search, and commit-list reads through the model.
Large responses were staged without truncating the returned page. The first answer stopped after one full commit page.
The later prompt change clarifies evidence coverage and pagination. A fresh model pagination check remains pending.
No GitHub write tool ran. Real notification delivery and private Telegram acceptance remain unverified.

## Google Calendar basic operations, 2026-10-28

The Calendar service uses existing Google OAuth and HTTPX with separate owner-bound encrypted credentials.
It supports calendar lists, event search and details, free/busy reads, and regular single-event creation, updates, and deletion.
Updates and deletion require the event version and use If-Match. Attendee and recurring-event mutations remain unavailable.
The service validates local times, daylight-saving ambiguity, and exclusive all-day end dates.
Unknown writes are not retried. Creation includes a known event ID for read-only reconciliation.
Calendar disconnection removes its local grant without revoking other grants in the shared Google project.
The generic harness and general agent instructions remain unchanged. No database migration or provider SDK was added.

All 1,199 Python tests passed, with three live checks deselected. The Calendar module has 35 contract cases.
The 20 frontend unit tests and 72 Chromium connection cases passed across four widths and both themes.
Ruff lint, formatting, OpenUI validation, and patch whitespace checks passed.
Native ARM64 API and frontend images built successfully. Both isolated Docker services are healthy on ports 8081 and 8080.

The operator registered localhost and deployment callbacks and authorized the local Calendar connection.
A normal browser model turn completed calendar_list_calendars, calendar_list_events, and calendar_free_busy through the normal journal and delivery path.
Calendar listing returned four calendars without another page. Event search returned zero events for the selected one-hour interval.
Availability returned no calendar errors. The three reads completed in a 4.7-second turn without any Calendar writes.
Event titles, descriptions, locations, and attendee data were excluded from the user-facing result and these notes.

The operator then approved one temporary primary-calendar event for October 29, 09:00-09:05 Asia/Kolkata.
The normal model turn created that event, read its version, moved it to 09:05-09:10, read its new version, and deleted it.
Journal inspection confirmed exactly one create, one update, and one delete for the same event, without attendees.
One read call was rejected by local argument validation and corrected before the remaining operations completed.
A separate read-only request to Google returned HTTP 200 with event status cancelled, confirming no active test event remained.
Production deployment and live Telegram acceptance remain pending.
