# Self-host speech services and connect hosted providers

Theos calls separate HTTP services for transcription and speech generation.
Its application image contains no speech models.
The main `compose.yaml` starts only Theos.
This guide describes optional deployments, not bundled services.

Upstream instructions were checked on 2026-10-04.
The operator confirmed that Speaches listed the downloaded Whisper Small model on the Mac mini.
Transcription, Kokoro playback, and Telegram voice delivery still need live checks.

## Choose a deployment

| Option | Transcription | Speech output | Operations |
| --- | --- | --- | --- |
| Docker on a Mac mini | Speaches with faster-whisper on CPU | Kokoro-FastAPI on CPU | Compose manages both containers |
| Native Apple Silicon | MLX Whisper on the Apple GPU | Kokoro-FastAPI through PyTorch MPS | Separate environments and startup services |
| Hosted transcription | OpenAI or Groq file transcription API | Keep local Kokoro or host it separately | Provider credentials and usage charges |
| Remote server you control | Speaches on a Linux server | Kokoro-FastAPI on the same server | Private network, persistent storage, and server maintenance |

MLX applies to the native Whisper option below.
Native Kokoro uses MPS, not MLX.
Docker Desktop runs the CPU variants in this guide.
Kokoro documents Apple GPU support through native execution.
See [Kokoro deployment](https://github.com/remsky/Kokoro-FastAPI) and [Speaches installation](https://speaches.ai/installation/).

### Current client contract

| Direction | Request | Required response |
| --- | --- | --- |
| Transcription | Multipart `POST /audio/transcriptions`, bearer credential, `model`, and `file` | JSON with a `text` field |
| Speech output | JSON `POST /audio/speech`, model `kokoro`, configured voice, and format `mp3` | MP3 bytes |

The base URL must include `/v1` when the service requires that prefix.
Theos does not send a speech authentication header.
There is no `AGENT_KOKORO_KEY` or configurable speech model setting.
The transcription credential is separate from the chat model credential.
The client sends the original audio without format conversion or automatic chunking.
Its shared HTTP client uses a 30-second timeout, including the read timeout.
Long CPU requests and initial model loads can exceed that timeout.

See the [voice client](../src/theos/services/voice/client.py) and [runtime HTTP configuration](../src/theos/runtime/engine.py).

## Docker on a Mac mini

Run this section on the Mac mini.
It assumes Docker Desktop, Tailscale, and an external SSD mounted at `/Volumes/extssd`.
Use a separate Compose project for speech.

### Prepare storage

1. Open Docker Desktop settings.
2. Select **Resources → Advanced → Disk image location**.
3. Choose `/Volumes/extssd/docker` and apply the change.
4. Create the speech directory and Whisper cache.

   ```bash
   mkdir -p /Volumes/extssd/voice/whisper-cache
   cd /Volumes/extssd/voice
   ```

Docker stores images and container data in its disk image.
Moving only the Compose file does not move that data.
Kokoro includes models in its image.
Whisper downloads models into the mounted cache below.
See [Docker storage on macOS](https://docs.docker.com/desktop/troubleshoot-and-support/faqs/macfaqs/).

### Create and start the containers

1. Save this file as `/Volumes/extssd/voice/compose.yaml`.

   ```yaml
   name: theos-voice

   services:
     kokoro:
       image: ghcr.io/remsky/kokoro-fastapi-cpu:latest
       restart: unless-stopped
       ports:
         - "127.0.0.1:8880:8880"
       logging:
         driver: json-file
         options:
           max-size: "10m"
           max-file: "3"

     whisper:
       image: ghcr.io/speaches-ai/speaches:latest-cpu
       restart: unless-stopped
       ports:
         - "127.0.0.1:8001:8000"
       environment:
         WHISPER__INFERENCE_DEVICE: cpu
         WHISPER__COMPUTE_TYPE: int8
         ENABLE_UI: "false"
         LOG_LEVEL: info
         HF_HUB_DISABLE_PROGRESS_BARS: "1"
       volumes:
         - /Volumes/extssd/voice/whisper-cache:/home/ubuntu/.cache/huggingface/hub
       logging:
         driver: json-file
         options:
           max-size: "10m"
           max-file: "3"
   ```

2. Download the images.

   ```bash
   docker compose pull
   ```

3. Start the containers.

   ```bash
   docker compose up -d
   ```

4. Inspect startup status and logs.

   ```bash
   docker compose ps
   docker compose logs --tail=50
   ```

The example uses upstream tags that can change.
After a successful test, replace each tag with its tested image digest.
Run `docker compose images` to identify the local images.
Run `docker image inspect IMAGE --format '{{json .RepoDigests}}'` to get their digests.
Keep the SSD mounted before Docker starts.
Enable Docker Desktop startup at login if required.
The restart policy applies after Docker starts, not before macOS login.

### Download Whisper Small

1. Check server health.

   ```bash
   curl --fail-with-body http://127.0.0.1:8001/health
   ```

2. Download the multilingual Small model.

   ```bash
   curl --fail-with-body -X POST \
     http://127.0.0.1:8001/v1/models/Systran/faster-whisper-small
   ```

3. Confirm that the local model list includes `Systran/faster-whisper-small`.

   ```bash
   curl --fail-with-body http://127.0.0.1:8001/v1/models
   ```

The health response only confirms that the HTTP server responds.
The model list confirms discovery of cached files, not successful transcription.
See [Speaches model management](https://speaches.ai/usage/model-discovery/).

### Handle download errors

1. Read the traceback before changing the container.

   ```bash
   docker compose logs --tail=120 whisper
   ```

An error about `tqdm` and a missing `_lock` points to the download progress code.
The Compose example disables Hugging Face progress bars as a workaround.
After adding that setting, recreate Whisper with `docker compose up -d --force-recreate whisper`.
See [Hugging Face environment settings](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).

A separate observed failure returned HTTP 500 from Hugging Face's Kokoro catalog query.
That Speaches version queried the catalog before it downloaded Whisper.
The direct download below bypasses that catalog query.
It still requires Hugging Face model downloads to work.

2. If the traceback identifies that catalog failure, download the repository directly into the same cache.

   ```bash
   docker compose exec -T \
     -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
     whisper /home/ubuntu/speaches/.venv/bin/python - <<'PY'
   from huggingface_hub import snapshot_download

   path = snapshot_download(
       repo_id="Systran/faster-whisper-small",
       cache_dir="/home/ubuntu/.cache/huggingface/hub",
       max_workers=1,
   )
   print("Model downloaded to:", path)
   PY
   ```

3. Restart Whisper after the download finishes.

   ```bash
   docker compose restart whisper
   ```

4. Check `/v1/models` again after startup.

This workaround produced the confirmed local model listing.
It does not establish that every Hugging Face outage has the same cause.
See [direct repository downloads](https://huggingface.co/docs/huggingface_hub/guides/download).

## Native macOS with MLX Whisper and MPS Kokoro

This option requires an Apple Silicon Mac.
Run these commands on the Mac mini, outside Docker.
Do not run both deployment options on the same ports.
For an existing Docker deployment, stop its speech containers with `docker compose stop` from the speech directory.

### Prepare native dependencies

1. Install the tools.

   ```bash
   brew install uv ffmpeg espeak-ng
   ```

2. Create the SSD directories.

   ```bash
   mkdir -p /Volumes/extssd/voice/cache/huggingface
   mkdir -p /Volumes/extssd/voice/cache/uv
   mkdir -p /Volumes/extssd/voice/python
   mkdir -p /Volumes/extssd/voice/tmp
   ```

3. Set these variables in each terminal before starting a native service.

   ```bash
   export HF_HOME=/Volumes/extssd/voice/cache/huggingface
   export UV_CACHE_DIR=/Volumes/extssd/voice/cache/uv
   export UV_PYTHON_INSTALL_DIR=/Volumes/extssd/voice/python
   export TMPDIR=/Volumes/extssd/voice/tmp
   ```

Models, project environments, and these caches use the SSD.
Homebrew uses its usual installation directory.
These shell variables do not persist in a new terminal or a `launchd` job.

### Start Kokoro

1. Clone the native server.

   ```bash
   cd /Volumes/extssd/voice
   git clone https://github.com/remsky/Kokoro-FastAPI.git
   cd Kokoro-FastAPI
   ```

2. Create its Python environment.

   ```bash
   uv venv --python 3.12
   ```

3. Start the native MPS server.

   ```bash
   HOST=127.0.0.1 PORT=8880 bash start-gpu_mac.sh
   ```

The upstream script installs dependencies and downloads models before starting the API.
Leave the terminal open during the initial test.
See the [native startup script](https://github.com/remsky/Kokoro-FastAPI/blob/master/start-gpu_mac.sh).

### Start MLX Whisper

1. Open another terminal and set the SSD variables above.
2. Clone the native transcription server.

   ```bash
   cd /Volumes/extssd/voice
   git clone https://github.com/chaosslabs/whisper-server-apple-silicon.git
   cd whisper-server-apple-silicon
   ```

3. Install its dependencies.

   ```bash
   uv sync --python 3.12
   ```

4. Start its HTTP server.

   ```bash
   WHISPER_SERVER_HOST=127.0.0.1 \
   WHISPER_SERVER_PORT=8001 \
   uv run python app.py
   ```

This server fixes its model to `mlx-community/whisper-large-v3-turbo`.
It accepts the request's `model` field but does not use it to select another model.
The first transcription downloads the model into the Hugging Face cache.
It does not enforce an API key.
See the [server source and instructions](https://github.com/chaosslabs/whisper-server-apple-silicon).

After testing, record the tested Git commits and dependencies before future updates.
For automatic native startup, configure separate `launchd` jobs with absolute paths, working directories, SSD environment variables, and log paths.
The SSD must be available when those jobs start.
This repository does not supply or install those jobs.

## Connect either deployment over Tailscale

Run these commands on the speech host.
Both deployment options bind to loopback on ports 8880 and 8001.
The forwarding rules expose them only through Tailscale.
Access follows the tailnet policy.
The examples do not configure application passwords.

1. Forward Kokoro.

   ```bash
   tailscale serve --bg --tcp=8880 tcp://127.0.0.1:8880
   ```

2. Forward Whisper.

   ```bash
   tailscale serve --bg --tcp=8001 tcp://127.0.0.1:8001
   ```

3. Inspect the forwarding rules.

   ```bash
   tailscale serve status
   ```

These rules use distinct ports from the sandbox service.
Do not reset existing Serve rules.
See [Tailscale TCP forwarding](https://tailscale.com/docs/reference/tailscale-cli/serve).

4. Set these values in the Theos host's private `.env`.

   ```dotenv
   AGENT_KOKORO_URL=http://SPEECH_HOST:8880/v1
   AGENT_KOKORO_VOICE=af_heart
   AGENT_TRANSCRIPTION_URL=http://SPEECH_HOST:8001/v1
   AGENT_TRANSCRIPTION_KEY=not-needed
   AGENT_TRANSCRIPTION_MODEL=Systran/faster-whisper-small
   ```

   Replace `SPEECH_HOST` with the speech host's Tailscale IP or DNS name.
   `not-needed` is a nonempty placeholder, not a secret or an authentication control.
   For the native Whisper server, use `AGENT_TRANSCRIPTION_MODEL=mlx-community/whisper-large-v3-turbo` to describe its fixed model.

5. Restart Theos after changing its environment.

   For a Compose deployment, run this from the Theos directory:

   ```bash
   docker compose up -d --force-recreate theos
   ```

## Enable a Whisper API key

Speaches supports bearer authentication through its `API_KEY` setting.
This is a speech credential, separate from the sandbox API key and Telegram access code.
The native MLX server in this guide does not implement this setting.
See [Speaches configuration](https://github.com/speaches-ai/speaches/blob/master/src/speaches/config.py).

1. Generate a credential on the Mac mini.

   ```bash
   openssl rand -hex 32
   ```

2. Store the result in `/Volumes/extssd/voice/.env`.

   ```dotenv
   SPEECH_API_KEY=replace-with-generated-key
   ```

   Preserve other entries if this file already exists.
   This file belongs to the speech Compose project, not the Theos project.

3. Restrict access to the credential file.

   ```bash
   chmod 600 /Volumes/extssd/voice/.env
   ```

4. Add this entry under `whisper.environment` in the speech Compose file.

   ```yaml
   API_KEY: ${SPEECH_API_KEY:?Set SPEECH_API_KEY in the speech .env}
   ```

5. Recreate only Whisper from the speech directory.

   ```bash
   cd /Volumes/extssd/voice
   docker compose up -d --force-recreate whisper
   ```

6. Set `AGENT_TRANSCRIPTION_KEY` to the same credential in the Theos host's private `.env`.
7. Recreate or restart Theos to load that credential.
8. Check that an unauthenticated model request fails.

   ```bash
   curl -i http://127.0.0.1:8001/v1/models
   ```

   Expect an authentication error, not a successful model list.
   `/health` remains public and is not an authentication test.

9. Test the same request with the credential.

   ```bash
   docker compose exec -T whisper /home/ubuntu/speaches/.venv/bin/python - <<'PY'
   import os
   import urllib.request

   request = urllib.request.Request(
       "http://127.0.0.1:8000/v1/models",
       headers={"Authorization": "Bearer " + os.environ["API_KEY"]},
   )
   with urllib.request.urlopen(request, timeout=10) as response:
       print("Authenticated model-list status:", response.status)
   PY
   ```

   Expect HTTP 200.
   Subsequent API download and transcription requests also need the bearer header.
   Keep Tailscale forwarding enabled for remote access.
   The key does not encrypt HTTP traffic outside the Tailscale connection.

Kokoro cannot use this credential through the current Theos client.
It needs a compatible private gateway or speech authentication support in Theos.

## Hosted options

Hosted transcription sends audio to the selected provider.
Review its current prices, retention terms, region availability, and account limits before use.
Provider limits do not override Theos's upload limit, which defaults to 10 MiB.
Theos forwards the original format, including Telegram voice-note formats.
Test a real voice note against the chosen provider.
An unsupported format requires conversion outside this client or a future client change.

### OpenAI transcription

1. Create an API credential in the operator's OpenAI project.
2. Configure Theos with that credential.

   ```dotenv
   AGENT_TRANSCRIPTION_URL=https://api.openai.com/v1
   AGENT_TRANSCRIPTION_KEY=replace-with-openai-api-key
   AGENT_TRANSCRIPTION_MODEL=whisper-1
   ```

   `gpt-4o-mini-transcribe` is another documented file-transcription model.
   Confirm model access and input format support before selecting it.
   This uses the file transcription API, not Realtime or a ChatGPT subscription.

3. Restart Theos and test transcription.

See [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text).

### Groq transcription

1. Create a Groq API credential.
2. Configure Theos with that credential.

   ```dotenv
   AGENT_TRANSCRIPTION_URL=https://api.groq.com/openai/v1
   AGENT_TRANSCRIPTION_KEY=replace-with-groq-api-key
   AGENT_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
   ```

   Groq also documents `whisper-large-v3`.
   Model access, rate limits, and pricing depend on the provider's current offering.

3. Restart Theos and test transcription.

See [Groq speech-to-text](https://console.groq.com/docs/speech-to-text).

### Hosted speech output

The current speech client can use a remote Kokoro-FastAPI server with the same HTTP contract.
For example, an operator can run the Kokoro container on a private Linux server.
Keep it reachable through a private network, then set `AGENT_KOKORO_URL` to that server's base URL.
No local model files are required on the Theos host.

Managed speech APIs are not interchangeable with the current Kokoro client.
For example, OpenAI's speech API requires authentication and its own model and voice values.
Changing only `AGENT_KOKORO_URL` will not make that API work.
See [OpenAI speech generation](https://developers.openai.com/api/docs/guides/text-to-speech).

A compatible gateway must accept the current Kokoro request, translate model and voice values, add provider authentication, and return MP3 bytes.
Keep the provider credential at that gateway and restrict access to it.
Theos does not implement this gateway or generic hosted speech configuration.
Hosted transcription with self-hosted Kokoro works within the current client contracts.

## Test speech before Telegram

Run these commands on the speech host for the self-hosted options.
For remote testing, replace `127.0.0.1` with its Tailscale address.

1. Generate a short MP3.

   ```bash
   curl --fail-with-body \
     http://127.0.0.1:8880/v1/audio/speech \
     -H 'Content-Type: application/json' \
     -d '{"model":"kokoro","input":"Hello, this is a speech test.","voice":"af_heart","response_format":"mp3"}' \
     --output /tmp/theos-speech-test.mp3
   ```

2. Play the result on macOS.

   ```bash
   afplay /tmp/theos-speech-test.mp3
   ```

3. Transcribe the generated audio.

   ```bash
   curl --fail-with-body \
     http://127.0.0.1:8001/v1/audio/transcriptions \
     -F 'file=@/tmp/theos-speech-test.mp3' \
     -F 'model=Systran/faster-whisper-small'
   ```

   For native MLX, use `model=mlx-community/whisper-large-v3-turbo`.
   Expect JSON with a `text` field containing approximately the spoken sentence.
   Allow the first native request to finish its model download before testing through Theos.

4. Send a real voice note to the enrolled Telegram bot.
5. Ask the bot to reply with an audio message.
6. Record the results in [acceptance](runtime/acceptance.md).

Incoming Telegram voice notes automatically use transcription.
Speech output uses `send_text_to_speech`, not an automatic voice-reply mode.
The generated recording tests connectivity and inference, not recognition of the user's accent.

### Indian English and mixed-language checks

Whisper Small is multilingual.
Its model card does not establish an Indian-accent accuracy score for this deployment.
Test 5–10 recordings with normal speaking speed, Indian names, dates, amounts, background noise, and Hindi–English mixing when relevant.
Compare missed words and latency before selecting a larger model.
See the [Whisper Small model card](https://huggingface.co/Systran/faster-whisper-small).

## Memory and operations

For a 16 GB M4 Mac mini, budget approximately 3–6 GB for both Docker speech services and Docker overhead.
This is a planning estimate, not a measured result or a memory limit.
Kokoro's dependencies, audio length, concurrency, and cache behavior affect actual usage.
The upstream faster-whisper CPU benchmark reports 1,477 MB for Small INT8 on different hardware.
See the [upstream benchmark](https://github.com/SYSTRAN/faster-whisper#small-model-on-cpu).

An 8 GB Docker Desktop memory limit is a starting budget for speech and light sandbox work together.
All sandbox containers share that budget.
Keep one speech worker initially.
Additional Kokoro workers load additional model copies.
See [Kokoro worker configuration](https://github.com/remsky/Kokoro-FastAPI/blob/master/docs/configuration.md).

1. Inspect container usage during real requests.

   ```bash
   docker stats --no-stream
   ```

2. Inspect Memory Pressure in macOS Activity Monitor.
3. Adjust workload concurrency or model size if memory pressure rises.

The external SSD supplies storage, not additional RAM.
Native inference has different memory behavior from the Docker estimate.
Keep model downloads outside live request tests where possible.
No automatic provider fallback, audio chunking, or speech-specific timeout setting exists in the current client.
