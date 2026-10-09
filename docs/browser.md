# Browser chat

The browser supports private conversations, files, model choices, approvals, and an administrator dashboard.
It stores conversation history in SQLite across restarts.
The server presents the configured `AGENT_NAME` on the login page and conversation labels.

## Configure a user

1. Generate a random token.

   ```sh
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

2. Add the token to `AGENT_USERS` in `.env`.
3. If the user needs the administrator dashboard, add the user ID to `AGENT_ADMINS`.
4. Recreate the container after the configuration change.

```dotenv
AGENT_USERS={"owner":"replace-with-at-least-32-random-characters"}
AGENT_ADMINS=["owner"]
```

Each token identifies one user.
Tokens must be unique and contain at least 32 characters.
Empty user and administrator maps disable browser account access.

## Open a conversation

1. Open `http://127.0.0.1:8080` through local access or an [SSH tunnel](DEPLOYMENT.md#private-browser-access).
2. Enter your token.
3. Select **New conversation**.
4. Open **Settings** in the header.
5. Select an allowed model and reasoning effort.
6. Select **Save settings**.
7. Enter your message.
8. Select **Send**.

The browser keeps the token in tab session storage until sign-out.
It sends the token in the authorization header.
It does not place the token in a URL.
The conversation list contains only browser sessions for that user.
The sidebar contains conversations and workspace links.
Use the sidebar icon beside the logo to hide or show conversations.

## Files and approvals

Use the attachment button to upload files.
The default file limit is 10 MiB.
Image checks also apply before the model receives an image.
Generated file links require the same authenticated owner.

Approval cards show the tool and saved action details.
Select **Approve** or **Deny** after reviewing the action.
The card clears when the server accepts the decision, before the resumed reply finishes.
The tool row then shows its current state without a duplicate waiting row.
After a connection error, the browser refreshes saved approvals when the server is reachable.
Approvals expire after 15 minutes.
The [tool catalog](tool-catalog.md#approval-boundary) lists protected actions.

## Continue or reset

**Resume** continues saved work after an interruption or model-call limit.
Reopen the conversation if a browser stream disconnects.
The runtime can finish a turn after the browser stops reading events.
Check the saved result before repeating an external action.

**Reset** clears the current history and approval history.
It retains personal records, files, and conversation model settings.
Model changes require a finished turn with no pending approvals.

## Personal activity and administrator access

**Activity & usage** appears for every signed-in user.
It shows only that user's conversations, model requests, token counts, costs, and tool activity.
The login token supplies the owner for every query.
Administrators also see only their own data in this view.

**Admin dashboard** appears for configured administrators.
It shows workspace totals and usage per user across all transports.
It also shows conversation IDs, model usage, traces, job status, and application logs.
Conversation titles and message history do not appear in the administrator response.

Charts summarize daily model requests, recorded cost, input/output tokens by model, and main-agent tool starts.
Choose **Last 7 days**, **Last 30 days**, or **Last 90 days**.
Chart dates use UTC and include today. Workspace totals and tables cover all time.
Model request counts include title and delegate requests.
Charts include complete records across transports, beyond the recent-row limits in diagnostic tables.

Hover over or tap a daily chart to inspect its values.
Select a model or tool bar for its breakdown. Expand **View chart data** for accessible exact values.
Cost charts exclude unpriced requests and show their count. Hollow points mark days without a recorded price.

The server enforces owner scope and administrator access independently of the visible buttons.
See [observability](base-infra/observability.md).

These access checks do not encrypt database contents.
An operator with database access can still read saved content.
User public-key onboarding and encrypted personal storage remain planned.

## Costs, thinking, and tools

The sidebar shows your total cost across transports.
The conversation header shows the cost of the selected conversation, including usage before a reset.
Use `/usage` to open cost, request, and token cards.
The cards compare the selected conversation with your totals across transports.
Unpriced requests remain visible. Use **Refresh usage** to reload the totals.
New browser conversations receive a short title from the selected model after the first completed exchange.
The title can update once after three user messages clarify the topic.
Custom titles remain unchanged. A naming failure keeps the first-message fallback and the completed reply.
Title generation uses only bounded opening message text, has no tools, and contributes to usage totals.
Set `AGENT_AUTO_TITLES=false` to disable model-generated titles.
Costs use OpenRouter-reported amounts when available, then configured USD token estimates.
Missing rates show **Unavailable**. Mixed priced and unpriced usage shows **partial**.
Administrator cost tables include all saved conversations, including Telegram and terminal sessions.

Expand **Thinking** in chat to read the model's reasoning summary when available.
The section starts collapsed and also appears in saved conversations.
This display control does not change reasoning effort.
A glowing dot shows active thinking before reasoning text arrives and while the model generates its reply.
The dot uses the companion orb style from mini-theos and stops when the model finishes.
The browser respects the reduced-motion preference.

Select **Tools** to search the tools available to the current conversation.
Expand a tool to read its description and input schema.
Protected tools show **Approval required**.
Expand a tool call in chat to inspect its inputs, result, and status.
The view uses the runtime registry and does not execute tools.

## Markdown in chat

Thinking summaries and assistant replies render Markdown during streaming and after reloads.
Supported formatting includes headings, emphasis, lists, quotes, links, task lists, tables, inline code, and fenced code blocks.
Tables and code blocks scroll within the message on small screens.
Select **Copy** on a code block to copy its code.

Raw HTML appears as text. Unsafe links cannot execute scripts, and remote images appear as links.
Speech playback uses the rendered text without code toolbar labels.

The composer starts with one line and grows with longer drafts, up to 140px.
Attachment, command, microphone, and send icons share the input row.
On mobile, recording hides attachment and command buttons until recording stops.
Dropdown arrows have a 14px right margin and reserved space for long values.

## Commands and generation settings

Type `/` in the message field to see commands and descriptions.
Use the arrow keys to select a suggestion.
Use **Enter** or **Tab** to insert it, then **Enter** to run it.
Use **Escape** to close suggestions.
`/help` and the slash icon show the command list and keyboard controls.
Select a command in the help dialog to run it or see its options.
Commands include `/new`, `/reset`, `/resume`, `/model`, `/reasoning`, `/settings`, `/tools`, `/connections`, `/usage`, and `/voice`.
Selecting `/model` or `/reasoning` opens a menu of supported options.
Submitting either command without an argument also opens its option menu.
`/thinking` remains a compatibility alias for `/reasoning`. It does not appear as a duplicate command.
`/settings` opens Settings. `/usage` opens the usage cards.
These controls do not send a prompt to the model.
`/resume` continues the saved model turn.

Type `@` at the start of a word to mention a connection.
Suggestions include `@gmail`, `@health`, `@zepto`, and configured workspace services such as `@sandbox`.
Each suggestion shows whether the account is connected, needs sign-in, or is not configured.
Use the arrow keys to select a suggestion, then **Enter** or **Tab** to insert it.
You can insert mentions anywhere in a draft, including multiple mentions in one request.
For example: `@gmail find the latest receipt and @zepto search for milk`.
Mentions enter the conversation as user text. They do not connect accounts or approve tools.
Connect an account through **Connections** when its suggestion shows **Sign-in required**.
Provider icons identify Gmail, Google Health, and Zepto in Connections and mention suggestions.
Workspace services use icons for execution, memory, search, storage, transcription, speech, weather, and skill resources.
The same icons appear in Connections and mention suggestions.

OpenRouter exposes the six requested choices plus the existing default model.
The aliases are `gpt-5.6-luna`, `sonnet-5.5`, `deepseek-flash-v4.1`, `gemini-3.8-flash`, `glm-5.3-flash`, and `qwen-3.8-27b`.
The runtime maps these aliases to provider model IDs.
An explicit operator allowlist controls which choices appear.

Select **Settings** in the header to configure the selected conversation.
The form contains the model, supported reasoning choices, generation parameters, and voice controls.
Expand **Generation parameters** in Settings for advanced controls.
`/voice` opens the same form at the voice controls.
Parameters include output token limit, temperature, Top P, Top K, seed, and repetition penalties where supported.
Empty fields use provider defaults.
SQLite saves generation values across restarts.
Select **Save settings** to apply all changes together. **Cancel** or **Escape** discards the draft.

Changing models removes unsupported values and bounds the output token limit.
The [OpenRouter catalog](https://openrouter.ai/api/v1/models) supplied the capability snapshot on 2026-10-06.

## Message tokens, timing, and timestamps

Each assistant reply shows output tokens, generation duration, and a timestamp below its text.
During streaming, the token estimate and elapsed time update automatically.
The `~` prefix marks an estimate from visible text and reasoning.
The final count uses provider usage when available, including reasoning tokens where the provider includes them.
Replies without provider usage retain the estimate.
Each model generation has its own duration. Tool execution and title generation do not add to that duration.

User messages also show their timestamps.
Dates use the browser's local time, such as `6 Oct 14:32`.
Hover over the timestamp for the full date, time, and timezone.
New timestamps and final durations survive conversation reloads and application restarts.
Older messages retain their token counts, with an estimate when usage is unavailable. They receive no invented timestamps or durations.

## Microphone and speech playback

Configure the [voice services](speech-hosting.md) to enable microphone transcription and TTS playback.
Select the microphone icon and allow microphone access in the browser.
The message box glows with the theme accent during recording.
Microphone volume controls the glow intensity. Silence returns it to a soft baseline.
The glow stops when recording ends. Reduced motion keeps a static recording glow.
The local audio analyzer closes on stop, cancellation, errors, and page exit.
Select the stop icon to transcribe the recording or the cancel icon to discard it.
Recordings stop after two minutes or at the configured upload limit.
Review the transcript in the message field before sending it.
Microphone access requires HTTPS or localhost and browser MediaRecorder support.

Select the speaker icon on a reply to read it aloud.
The button shows a loading indicator while the service prepares audio, then a stop icon during playback.
Select the stop icon to stop playback. Select the speaker again to replay the cached audio.
Only one reply plays at a time. A conversation change stops playback.
Enable **Read new replies aloud** in voice settings for automatic playback in this tab.
Some browsers require another click on the speaker icon before audio can start.
Speech supports replies up to 12,000 characters.
The UI uses the configured transcription and Kokoro services, independently of native model audio support.
Audio files require the signed-in owner's token.

The login, header, and empty conversation use theme-specific logos from mini-theos.
Dark mode uses `design-lab/public/assets/theos-icon.png`. Light mode uses the app's Daylight icon.
The theme button shows a sun or moon for the available theme change.
Chat messages and the composer share a left gutter instead of a fixed, centered message column.
Attachment and command icons sit on the left. Microphone and send icons sit on the right.
Multiline drafts grow automatically. Streaming preserves your position when you scroll to earlier messages.
The mobile sidebar closes after navigation, with the backdrop button, or with **Escape**.
The [asset manifest](browser-asset-provenance.json) records its source and hash.

## Connections

The operator configures optional services through the existing environment settings.
Users authorize their own Gmail, Google Health, and Zepto accounts.

1. Select **Connections** or use `/connections`.
2. Select **Connect** for an available account service.
3. Select **Continue sign-in**.
4. Authorize the account with its provider.
5. Return to **Connections** to check the saved connection.

Google Health consent includes nutrition writes.
Connection enables exports of existing unsynced meals and future meal changes.
See [Google Health](google-health.md) before consent.

For Zepto's localhost callback, paste the complete return URL into the connection form.
Select **Finish connection**.
The return URL goes to the authenticated account endpoint, never to model history.
Public HTTPS callbacks complete the handoff directly when the provider permits that URI.
Unfinished Zepto setup expires after ten minutes and does not survive a server restart.

Use **Cancel setup** to invalidate a pending connection.
Use **Disconnect** to remove local credentials and cancel pending setup.
Health disconnection also cancels incomplete imports and meal exports.
Use the provider's account settings to remove remaining remote access when needed.

The view refreshes account status while open.
**Connected** means Theos has saved authorization. It does not prove that every provider request will succeed.
**Workspace services** shows configured sandbox, memory, search, storage, transcription, speech, weather, and skill resources.
**Configured** does not prove service reachability or a successful live operation.
Sandbox tools already work in browser conversations when enabled.
Shell, Python, and browser execution require approval.
See [sandbox setup](sandbox.md) for the server and remote browser dependencies.

## Account boundaries

The browser token supplies the owner. A request or model cannot select another owner.
Personal records, files, and credentials belong to that owner across private conversations.
Conversation history, approvals, tool checkpoints, and sandbox references remain separate for each conversation.
An approval cannot authorize another conversation's action.
Google and Zepto callbacks bind consent to the owner who started setup.
Gmail sending retains draft review and approval. All Zepto tool calls retain approval.

The application has no automatic account-linking flow between browser and Telegram identities.
Browser IDs cannot start with `telegram:`, `telegram-group:`, or `terminal:`.
Keep each browser ID stable when rotating its token.
Groups and terminal sessions receive no account tools.

Source: [browser application](../src/theos/transports/browser/app.py), [connection routes](../src/theos/transports/browser/connections.py), and [browser assets](../src/theos/transports/browser/static/).
