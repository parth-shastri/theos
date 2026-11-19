# Files and voice

Theos stores uploads and generated files in a private catalog.
Without R2, file contents persist in the application data volume.
With R2, the data volume holds a temporary upload spool and the file catalog.
R2 replication and voice services are optional external integrations.

Read [speech hosting](speech-hosting.md) for Docker, native Apple Silicon, hosted providers, and live test procedures.

## Local files

Each file has an opaque ID, an owner, metadata, and a local path.
The path can be absent after verified R2 replication.
A supplied filename cannot select the storage path.
Downloads and workspace input transfers check the authenticated owner.

The default file limit is 10 MiB.
`AGENT_MAX_UPLOAD_BYTES` can set a limit from 1 KiB to 25 MiB.
Images also have a 25-million-pixel limit and content checks.
The client converts accepted BMP images to PNG for model input.
A model still needs image capability to inspect an image.

Telegram voice notes also remain in the file catalog after transcription.
A conversation reset retains uploaded and generated files.
The uploaded-file catalog has no automatic expiry policy. Runtime checkpoint retention applies separately to workspace versions and recovery snapshots.

## R2 archives

Configure all four fields together:

```dotenv
AGENT_STORAGE__ENDPOINT=https://account-id.r2.cloudflarestorage.com
AGENT_STORAGE__BUCKET=private-agent-files
AGENT_STORAGE__ACCESS_KEY=replace-me
AGENT_STORAGE__SECRET_KEY=replace-me
```

The credential needs object read, write, and delete access for the selected bucket.
The application uses an S3-compatible client.

One background worker uploads catalog files and checkpoint objects in bounded batches.
The worker verifies uploaded contents through an R2 read before removing the local copy.
Uploads, generated audio, response attachments, and workspace versions use this path.
Failed uploads retain their local contents and retry without repeating the assistant action.
Previously saved local files follow the same verification and eviction path after startup.

Downloads, transcription, email attachments, and workspace restoration read completed files directly from R2.
These reads use temporary memory and do not create a persistent local download cache.
New image messages retain file references in SQLite. The model and browser resolve them when needed.
Older inline image history remains readable. This change does not rewrite those historical database rows.
R2 outages can delay access to completed files whose local copies were removed.

After transfers complete, the indexed file and checkpoint directories can be empty.
SQLite, file metadata, logs, and running application processes still need local storage and memory.
An upload backlog or full backup temporarily needs additional disk space.

The runtime automatically saves changed `/workspace` files into the session checkpoint journal.
A background worker replicates those objects to R2. Storage outages retain pending transfers without repeating model commands.
Selected uploads enter `/workspace/uploads/` before the next model request.
Gmail attachment downloads return a ready workspace path when execution is configured.

The model uses `run_command` for filesystem work and `attach_file` for response attachments.
Attachment recovery retains the same file ID and exact bytes after remote restoration.
The model has no catalog listing, archive, restore, or transfer tool.

R2 is not required for ordinary uploads or image input. Without it, recovery uses the local application data directory.
A full backup includes the catalog and indexed local or remote file contents.
Remote-only contents enter temporary backup staging and disappear from staging when the backup finishes.
Pi deployment transfers the completed archive to R2 before removing its local copy.
Read the [backup procedure](operations.md#back-up) for manual archives and remote restoration.
Deleting a workspace file removes the current manifest entry. Saved response attachments and retained checkpoints preserve their recorded bytes.
The runtime retains three recent recovery checkpoints per session, plus current local and published remote pointers.
An hourly collector removes unreferenced versions after a one-hour grace period. Storage settings can change these defaults.
The collector records pending deletions before removing local or R2 objects. Failed remote deletions retry after restart.
It protects active sessions and defers collection when retained checkpoint references cannot be verified.
This policy belongs to Theos file services. It does not change the generic harness or its conversation compaction rules.

## Transcription

```dotenv
AGENT_TRANSCRIPTION_URL=http://speech.example.internal:8000/v1
AGENT_TRANSCRIPTION_KEY=replace-me
AGENT_TRANSCRIPTION_MODEL=whisper-1
```

The client appends `/audio/transcriptions` and sends the owned audio file.
The transcription credential is separate from `AGENT_API_KEY`.
A Telegram voice note automatically enters this path.
Browser audio uploads can use `transcribe_file` when requested.

The URL must match the service base path.
Include `/v1` only when that service requires it.
The returned transcript can enter model requests and saved conversation history.

## Speech replies

```dotenv
AGENT_KOKORO_URL=http://speech.example.internal:8880/v1
AGENT_KOKORO_VOICE=am_michael(0.7)+bm_george(0.3)
AGENT_KOKORO_SPEED=0.9
```

`send_text_to_speech` accepts text from 1 to 12,000 characters.
The client appends `/audio/speech` and requests MP3 audio.
It saves the result as `speech.mp3` in the private catalog.

For the approved subtle robotic effect, point `AGENT_KOKORO_URL` to the separate
[speech gateway](../speech/README.md) and set its bearer key in `AGENT_KOKORO_KEY`.
Direct Kokoro connections return the voice blend without the effect.
Every request first generates expressive spoken wording through the configured model.
This step retains the source facts and records its model usage.
See [personality and voice](personality.md) for the selected style and system prompt changes.
The normal file size limit applies to the saved result.
Telegram sends audio through its audio delivery path.
Browser chat supplies an authenticated download link.

The assistant image contains no transcription or speech model weights.
The operator runs those services separately.
A speech failure does not establish whether another external action succeeded.

Source: [file catalog](../src/theos/services/files/catalog.py), [voice client](../src/theos/services/voice/client.py), and [Telegram media](../src/theos/transports/telegram/media.py).

## Telegram calls

The optional private calling gateway rings the user's Telegram app from a separate regular Telegram account.
Theos uses the same Kokoro voice, speed, and gateway effects as app playback.
The existing bot continues to deliver messages. It cannot start private voice calls.
Read the [calling gateway setup](../calling/README.md) for account login, credentials, and deployment values.

Mapped owners can request a reminder with `delivery="phone"`. The selected deployment provider determines where the call rings.
Written reminders remain available. Pending approvals trigger a generic call alert after two minutes.
The user reviews and decides approvals in the authenticated application.
Telegram call audio travels directly to the private gateway. It requires no public media URL or Twilio number.

## Direct phone calls

Theos can call a mobile number through Twilio Voice. It uses the same Kokoro voice, speed, and speech gateway as app playback.
A phone reminder reads the saved text. An approval call asks the user to open Theos for the review.
Telephone audio has less bandwidth than app playback. [Twilio audio playback](https://www.twilio.com/docs/voice/twiml/play).

1. Create an API key in the Twilio Console. Grant the Restricted key permission to create Voice Calls.
2. Get a voice-enabled Twilio number. To reach an Indian mobile, use a caller number outside India.
3. Enable the destination country in Twilio Voice Geo Permissions.
4. Set the following values in the private deployment environment, then restart the application.

```dotenv
AGENT_TWILIO__ENABLED=true
AGENT_TWILIO__ACCOUNT_SID=
AGENT_TWILIO__API_KEY_SID=
AGENT_TWILIO__API_KEY_SECRET=
AGENT_TWILIO__FROM_NUMBER=
AGENT_TWILIO__RECIPIENTS={"workspace-owner":"+12025550100"}
AGENT_TWILIO__DAILY_LIMIT=20
```

Use E.164 numbers with country codes. Replace the example owner with the browser account ID or `telegram:<numeric-user-id>`.
A browser account linked through Telegram uses the same Telegram owner ID. Separately configured accounts have separate IDs.
List only owners who opted in. The mapping enables explicit phone reminders and pending approval calls for those owners.
Use matching Account and Key SIDs from the live Twilio account. The API Key Secret is the value issued when the key is created.
Twilio trial accounts restrict calls to verified recipients and the sign-up country.
[Restricted keys](https://www.twilio.com/docs/iam/api-keys/restricted-api-keys) · [Voice Geo Permissions](https://www.twilio.com/docs/sip-trunking/voice-dialing-geographic-permissions) · [India calling rules](https://www.twilio.com/en-us/guidelines/in/voice) · [Trial limits](https://www.twilio.com/docs/usage/trials).

Set `AGENT_WEB_URL` to the publicly reachable HTTPS origin of the existing Theos frontend.
Twilio fetches a short-lived MP3 through that origin when a user answers. The URL expires five minutes after the call attempt.
Keep `AGENT_FRONTEND_SECRET` set for the existing frontend proxy. Kokoro stays on its configured network.

In the connected account, ask Theos to call you in two minutes with a short test message.
Confirm that your phone rings and plays the configured voice. Check that the reminder also appears in the normal inbox.
For an approval test, leave a request pending for two minutes. Answer the call and make the decision in Theos.
Approval calls speak a generic message. Phone reminders use at most 360 characters.

The deployment defaults to 20 call attempts per rolling day. Calls can incur Twilio charges.
An expired or cancelled reminder can still have its saved text notification. Theos skips a phone reminder more than 15 minutes late.
If Twilio returns an ambiguous result, Theos records the attempt as uncertain. Theos does not dial again for that occurrence.
An accepted call means Twilio accepted the request. Confirm ringing and playback in the handset or Twilio call logs.
