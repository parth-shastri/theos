# Native MLX transcription

This separate service runs Whisper Large v3 Turbo on the Mac mini's Apple GPU.
The assistant and Pi images contain no MLX dependencies.
The service accepts the existing multipart transcription request and returns JSON with a `text` field.

The model ID is `mlx-community/whisper-large-v3-turbo`.
The selected model revision is `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`.
The dependency lock pins `mlx-whisper==0.4.3` and its dependencies.
See the [MLX model](https://huggingface.co/mlx-community/whisper-large-v3-turbo) and [MLX Whisper source](https://github.com/ml-explore/mlx-examples/tree/main/whisper).

## Request behavior

`GET /health` reports readiness only after Metal inference succeeds during startup.
`GET /v1/models` and `POST /v1/audio/transcriptions` require the configured bearer key.
The server rejects a different model ID rather than silently selecting its fixed model.

FFmpeg decodes uploaded audio, including Telegram OGG/Opus and browser WebM.
The defaults permit 10 MiB and five minutes per recording.
The service rejects longer recordings instead of returning a partial transcript.
The assistant's existing 30-second HTTP timeout still applies.

One dedicated worker loads the model and runs inference.
A concurrent transcription receives HTTP 503 instead of waiting in a queue.
Health checks remain available during inference.
Temporary audio files remain available until inference ends, then the service removes them.
The service disables access logs and does not log transcripts or decoder errors.

## Install on the Mac mini

Use an internal-disk runtime because macOS can block launchd from executing Python scripts on removable storage.
The live Mac mini also blocks model reads from that storage.
Keep the download on the external SSD and copy the active model to the internal runtime.
The active model requires approximately 1.6 GB of internal storage.
Keep Whisper Small on port `8001` for rollback.
The MLX service uses port `8002`.

1. Copy this directory from the repository to the Mac mini.

   ```sh
   rsync -a --exclude='.venv' --exclude='__pycache__' \
     --exclude='.pytest_cache' --exclude='.ruff_cache' \
     transcription/ parths-mac-mini:.local/share/theos-transcription/
   ```

2. Install the locked dependencies on the Mac mini.

   ```sh
   cd ~/.local/share/theos-transcription
   /opt/homebrew/bin/uv sync --locked --python 3.12 --no-dev
   ```

3. Create the model directory after the external SSD mounts.

   ```sh
   mkdir -p /Volumes/extssd/voice/models /Volumes/extssd/voice/cache/huggingface
   ```

4. Download the pinned model revision.

   ```sh
   HF_HOME=/Volumes/extssd/voice/cache/huggingface \
     .venv/bin/hf download mlx-community/whisper-large-v3-turbo \
     --revision a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb \
     --local-dir /Volumes/extssd/voice/models/whisper-large-v3-turbo-a4aaeec0636e
   ```

5. Copy the model files to the internal runtime.

   ```sh
   mkdir -p models/whisper-large-v3-turbo-a4aaeec0636e
   cp /Volumes/extssd/voice/models/whisper-large-v3-turbo-a4aaeec0636e/config.json \
      /Volumes/extssd/voice/models/whisper-large-v3-turbo-a4aaeec0636e/weights.safetensors \
      models/whisper-large-v3-turbo-a4aaeec0636e/
   ```

6. Install the login agent with the existing speech key.

   ```sh
   .venv/bin/python install.py \
     --host YOUR_MAC_MINI_TAILSCALE_IP \
     --model-path "$PWD/models/whisper-large-v3-turbo-a4aaeec0636e" \
     --key-file /Volumes/extssd/voice/.env
   ```

The installer reads `SPEECH_API_KEY` without printing it.
It writes a private `.env` and a login agent with mode `0600`.
Its environment variables use the `AGENT_MLX_` prefix defined in `server.py`.
`--key-name` selects another credential entry when needed.
Supply only loopback or the Mac mini's private Tailscale IP as `--host`.

The login agent uses the internal model with Hugging Face offline mode enabled.
It does not need the SSD or a model download during startup.
Launchd retries if the Tailscale address is unavailable during startup.
Automatic recovery still requires a macOS login, as with the existing speech gateway.

## Inspect and connect

1. Inspect the login agent on the Mac mini.

   ```sh
   launchctl print gui/$(id -u)/com.parthshastri.theos-transcription
   tail -20 ~/Library/Logs/Theos/transcription.stderr.log
   ```

2. Check the new endpoint from the Theos host.

   ```sh
   curl --fail http://YOUR_MAC_MINI_TAILSCALE_IP:8002/health
   ```

3. Preserve private backups of the active Theos environments.
4. Change only these settings in each active environment.

   ```dotenv
   AGENT_TRANSCRIPTION_URL=http://YOUR_MAC_MINI_TAILSCALE_IP:8002/v1
   AGENT_TRANSCRIPTION_MODEL=mlx-community/whisper-large-v3-turbo
   ```

5. Preserve the existing `AGENT_TRANSCRIPTION_KEY`.
6. Recreate only the Theos API with its existing image, Compose files, and data volume.
7. Check application readiness and transcribe an OGG/Opus fixture through the application client.

For rollback, restore the previous transcription URL and model from the private environment backup.
Recreate only the Theos API again.
The previous Speaches container and its cached Small model remain available on port `8001`.

## Check the service

```sh
uv sync --project transcription --locked
uv run --project transcription --no-sync ruff check transcription
uv run --project transcription --no-sync ruff format --check transcription
cd transcription
uv run --no-sync pytest -q
```

Linux CI checks the HTTP contract with an injected recognizer.
It does not install MLX or establish GPU inference.
Mac mini checks must cover actual inference, input formats, private-network access, and application configuration.
Synthetic speech checks do not establish recognition accuracy for a person's Indian accent.
