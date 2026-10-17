# Files and voice

Theos stores uploads and generated files in a private catalog.
Local files persist in the application data volume.
R2 archives and voice services are optional external integrations.

Read [speech hosting](speech-hosting.md) for Docker, native Apple Silicon, hosted providers, and live test procedures.

## Local files

Each file has an opaque ID, an owner, metadata, and a local path.
A supplied filename cannot select the storage path.
Downloads and file tools check the authenticated owner.

The default file limit is 10 MiB.
`AGENT_MAX_UPLOAD_BYTES` can set a limit from 1 KiB to 25 MiB.
Images also have a 25-million-pixel limit and content checks.
The client converts accepted BMP images to PNG for model input.
A model still needs image capability to inspect an image.

Telegram voice notes also remain in the file catalog after transcription.
A conversation reset retains uploaded and generated files.
There is no automatic file expiry policy.

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

| Tool | Action |
| --- | --- |
| `list_user_files` | List recent catalog entries |
| `archive_user_file` | Copy a local file to R2 |
| `restore_user_file` | Download an archived object to its catalog path |
| `delete_user_file` | Delete the remote object, local file, and catalog entry after approval |

Archiving does not delete the local file.
The object key uses `theos/` plus the opaque file ID.
`AGENT_NAME` does not change existing object keys.
R2 is not required for ordinary uploads or image input.
A full backup needs the local catalog and a separate policy for remote objects.

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
