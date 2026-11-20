# Telegram calling gateway

Theos can ring a user's Telegram app and play a short reminder with its existing voice.
A separate regular Telegram account places calls through MTProto. The existing bot handles messages.
Telegram's call method supports user accounts. It does not support bots. [Telegram calling API](https://core.telegram.org/method/phone.requestCall)

This gateway owns the Telegram session and native audio dependencies.
Run it on the speech host or another private Mac or Linux host.
The main application sends MP3 bytes through an authenticated private HTTP connection.
Keep this service on localhost or a private network such as Tailscale.

## Create the calling account

1. Register a separate Telegram account with a spare phone number in the official Telegram app.
2. Name the account Theos so incoming calls identify the caller.
3. Sign into [my.telegram.org](https://my.telegram.org) with that account.
4. Open **API development tools** and create an application.
5. Save its `api_id` and `api_hash` in the gateway's private environment.
6. Give the calling account a public username so users can open its chat during setup.

Use the receiving account's numeric Telegram user ID as the recipient.
For a Telegram-linked Theos account, the authenticated `/api/me` response has an `id` such as `telegram:123456789`.
The numeric suffix is the receiving Telegram ID. A separately configured browser owner has its own ID.
Do not use a bot ID, group ID, phone number, or display name as a recipient.
[Telegram application credentials](https://core.telegram.org/api/obtaining_api_id)

## Install and authorize

The gateway supports Python 3.12 or 3.13 and requires host `ffmpeg` and `ffprobe` executables.
Its lock selects Telethon 1.46.0, PyTgCalls 3.0.1, and NTgCalls 3.0.7.
The native package publishes wheels for Apple Silicon macOS and Linux ARM64 or x86-64.
Install this project separately from the Pi application image. [PyTgCalls source](https://github.com/pytgcalls/pytgcalls)

From this directory, install the locked environment.

```sh
uv sync --locked
cp .env.example .env
chmod 600 .env
```

Edit `.env` with the application credentials, private data path, and a fresh shared gateway key.
Leave `AGENT_CALLING_RECIPIENTS=[]` for per-user onboarding.
Optional operator recipients can still use explicit numeric IDs or `AGENT_CALLING_RECIPIENT_USERNAME` during login.
Use `openssl rand -hex 32` to generate the key. Retain this same value for the application configuration below.
Use an absolute data path outside the source checkout.
For a remote Pi client, set the host to the gateway machine's private Tailscale address.

Authorize the calling account locally.

```sh
uv run --no-sync theos-calling-login
```

The terminal prompts for the calling account's number, login code, and optional two-step verification password.
Set the optional `AGENT_CALLING_PHONE` to supply the calling number from the private environment.
Enter these values directly in the local terminal. The login tool does not place a call.
It resolves the supplied username after authorization and rejects the calling account as its own recipient.
It saves the account session and a private `authorization.json` record under `AGENT_CALLING_DATA_DIR`.
For optional operator recipients, copy the record's `recipient_ids` array into `AGENT_CALLING_RECIPIENTS`.
New users verify their own accounts through Theos. They do not need entries in this environment variable.
Protect this directory as an account credential. Do not run login and the server against the session simultaneously.

Both commands accept `--env-file /absolute/path/to/private.env` for a configuration outside the checkout.

Start one gateway process after login.

```sh
uv run --no-sync theos-calling
```

`GET /ready` reports startup readiness. The service refuses startup when the account is unauthorized or a recipient is unavailable.
Startup never prompts for login. Keep the process running with the host's service manager after handset acceptance.
The gateway rejects incoming calls. Normal calls play the supplied MP3 and end the call.
Optional two-way calls receive bounded voice responses in memory. The gateway never opens the host's microphone or camera.

## Connect Theos

Set these values in the private Theos deployment environment.

```dotenv
AGENT_TWILIO__ENABLED=false
AGENT_TELEGRAM_CALLS__ENABLED=true
AGENT_TELEGRAM_CALLS__URL=http://private-gateway-address:8882
AGENT_TELEGRAM_CALLS__KEY=the-same-private-gateway-key
AGENT_TELEGRAM_CALLS__RECIPIENTS={}
AGENT_TELEGRAM_CALLS__DAILY_LIMIT=20
```

The selected speech gateway must remain configured through `AGENT_KOKORO_URL` and its existing credentials.
Enable one calling provider per deployment. Existing operator mappings remain supported as verified fallback recipients.
The global environment requires the enabled flag, gateway URL, shared key, and speech endpoint.
Recipient mappings are optional when users connect through onboarding.
Restart Theos after updating its environment.

## Connect each user

1. Open **Connections → Telegram calls** in the browser, or send `/calls` in the private bot chat.
2. Select **Connect Telegram calls**.
3. Open the calling account and send the prepared verification message.
4. Return to Theos and check the connection.
5. Select **Call me for the test** and answer in Telegram.
6. Choose reminder and approval calls, then confirm that you heard the message.

Setup is optional. Users can skip it and connect later. They do not supply API keys or create another calling account.
The verification link expires after ten minutes. It uses Telegram's [draft-message links](https://core.telegram.org/api/links#public-username-links).
Users must send the message themselves. Opening a link alone does not verify an account.
Telegram-owned Theos accounts require the same sender ID. Browser accounts prove control of the account that sends the challenge.
The gateway rejects forwarded messages, bots, groups, expired challenges, and reused challenges.
Verification stays outside the assistant's model history.
If Telegram blocks the test call, allow calls from the calling account in Telegram's privacy settings and try again.
The calling account's username is preferred. A phone-number link is used when the account has no username.

The app stores verified recipients and call preferences in migration 021.
The gateway stores verified connections beside its existing call ledger and account session.
Users can change each call preference or disconnect in Connections or `/calls`.
Disconnection immediately blocks new and queued application calls. It also revokes the gateway connection.
Written notifications remain available. With two-way calling disabled, resolve approvals in the authenticated Theos application.

## Two-way calls: local implementation

Both two-way flags default to false. Release 1.6.7 includes this conversation flow.
The application uses `AGENT_TELEGRAM_CALLS__TWO_WAY`. The gateway uses `AGENT_CALLING_TWO_WAY`.
The earlier `SPOKEN_APPROVALS` flags remain aliases for this same conversation flow.
The application also needs its existing transcription endpoint and credentials.
Missing transcription configuration retains ordinary call alerts. No extra provider account is required.

Reminder, approval, immediate, and test calls accept natural sentences and multiple replies on the same call.
Theos uses its normal runtime and tools for ordinary voice requests. It removes `call_user` during an active call.
When approval is pending, questions use the saved review. Other tasks and changed actions need that review resolved first.
Eligible calls read the complete review in the app's voice before accepting an explicit approval or decline.
The complete review prompt must fit 600 characters. Long, HTML, or opaque reviews retain the application review path.
Questions, conditions, unclear speech, unrelated sentences, and silence do not decide an approval.
A caller can say goodbye or end the call at any time. Ending the call leaves an undecided approval pending.
An explicit decision can also request the call to end. Ending a call does not undo an already recorded decision.

Incoming audio starts after Theos finishes speaking and a short guard interval passes.
The gateway receives up to thirty seconds of mono, 48 kHz, signed 16-bit PCM per response.
One second of trailing silence ends an utterance. Thirty seconds without speech ends the call.
Speech cut off at the response limit cannot authorize an action.
The call accepts up to twenty responses and lasts at most five minutes, including dialing and playback.
Approval calls also respect their original approval expiry. Each response can wait up to ninety seconds for application feedback.
The application bounds response processing to eighty seconds. It never opens the host microphone or camera.
This is turn-based audio. Interruption while Theos speaks is not implemented.

The private HTTP contract adds `interactive=true` and `dialogue_expires` to the existing call request.
Authenticated `GET /v1/calls/{id}/response` returns WAV audio with its `X-Theos-Voice-Turn` sequence number.
It returns HTTP 204 while waiting or HTTP 410 when unavailable.
Authenticated `GET /v1/calls/{id}/dialogue` reports the active sequence and whether it awaits feedback.
Authenticated `POST /v1/calls/{id}/finish?turn=N&end=false` supplies MP3 feedback and continues the same call.
The `end=true` option finishes after feedback. Authenticated `DELETE /v1/calls/{id}/dialogue` closes the call.
Duplicate feedback for the same sequence is idempotent. Changed or stale feedback cannot answer a later response.
The call ID and mode retain durable deduplication. No callback URL or public incoming endpoint is required.

The application binds each decision to the saved owner, recipient, approval, tool call, arguments, preview, and expiry.
It re-reads the provider preview before applying a decision through the existing runtime approval path.
The intent model uses the whole current utterance. A partial positive quote cannot authorize an action.
Migration 023 stores private transcripts, replies, response digests, and decision metadata.
Ordinary voice requests also enter their existing conversation history. Raw response audio never enters the file catalog, R2, or model history.
The recorded decision, voice outcome, and written notice commit together.
Failed feedback cannot erase a recorded decision or repeat an action.
Interrupted conversations remain uncertain after restart. They are never replayed or redialed automatically.

The pinned native binding changes streams only on the existing call.
Later stream changes bypass the high-level library helper because it can reconnect a missing call.
Keep the pinned adapter tests when updating PyTgCalls or NTgCalls.
Live handset input, human speech recognition, and consecutive feedback playback remain open acceptance checks.

## Delivery and recovery

`call_user(message)` queues an immediate call for the current activated private owner.
It accepts no recipient or credential arguments.
Calling discovery requires an enabled provider, complete credentials, a speech endpoint, and an activated private owner.
New connections activate only after verification, a test call, and the user's audio confirmation.
The Twilio provider also requires its public frontend media configuration.
With missing values, calling stays hidden and ordinary reminders remain available.
The reminder tool exposes `delivery="phone"` only when reminder calls are enabled for the current conversation.
Users who enable reminder calls receive phone delivery by default. Other users retain message delivery.
Existing operator mappings retain their original message default until preferences are saved.
Reminder audio uses at most 360 characters of literal saved text.
The gateway allows one active call, waits up to 25 seconds for an answer, and caps the call workflow at 90 seconds.
It rejects a concurrent call instead of adding a queue that could become stale.
Both services enforce a rolling daily limit, default 20 attempts.
This limit and the single active call apply to the shared calling account across all users.

The application retains written delivery and saves its call attempt before requesting a call.
The gateway saves the call ID before touching Telegram. Repeated IDs never start another call.
Interrupted or ambiguous attempts remain uncertain. Neither service redials them automatically.
Audio files are private temporary files and are deleted after success, failure, or cancellation.
Startup removes orphaned clips and marks interrupted accepted work uncertain.
Gateway call IDs remain as deduplication records. Back up the gateway directory to preserve these records and the account session.

An `accepted` application status means the gateway accepted work. It does not prove that the user answered or heard the message.
An authenticated `GET /v1/calls/{id}` returns gateway status for operator inspection.
`completed` means the connected call ended after playback or a remote hangup. Handset confirmation establishes audible delivery.

## Verification

Run the gateway's isolated checks from this directory.

```sh
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
```

Tests cover admission, recipient isolation, bounded audio, duplicate IDs, the daily limit, cleanup, and restart recovery.
The pinned native audio stack decodes a local synthetic MP3 with FFmpeg without contacting Telegram.
These checks use a fake Telegram caller. Real ringing and playback require the dedicated account and handset acceptance.

Routine CI runs the gateway's isolated unit and HTTP contract checks without system package installation.
The local `native_audio` check requires FFmpeg and verifies the pinned native decoder.
Run it on the speech host with `uv run --no-sync pytest -q -m native_audio`.
Real ringing and playback remain a handset acceptance check.
