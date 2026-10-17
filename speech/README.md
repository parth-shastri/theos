# Theos speech gateway

Run this separate process on the speech host, beside Kokoro-FastAPI.
The assistant and Pi image do not install its audio dependencies.
The gateway applies the approved subtle voice treatment and returns MP3 audio.
It contains no speech model weights and stores no requests or generated audio.

## Selected voice

| Setting | Value |
| --- | --- |
| Kokoro voice | `am_michael(0.7)+bm_george(0.3)` |
| Generation speed | `0.9` |
| Base pitch | `-1.2` semitones |
| Bass and dynamics | 65 Hz high-pass, 140 Hz shelf at +2 dB, 2:1 compression |
| Parallel lower voice | -3 semitones, 8 ms delay, gain `0.055`, filtered to 100–2,000 Hz |
| Metallic resonance | 3.5/7 ms taps, gain `0.045`, filtered to 250–3,000 Hz |
| Ring modulation | 68 Hz, gain `0.009`, filtered to 180–3,200 Hz |
| Output | -23 LUFS target, -1.5 dBFS sample ceiling, MP3 at 128 kbps |

This is an original mixed voice with a quiet robotic texture.
The profile name is `theos-subtle-v1`.
The [effect implementation](src/theos_speech/effects.py) records the complete processing chain.
Short replies retain their duration. Only their loudness measurement receives silence padding.

## Start on the Mac mini

Install FFmpeg with Homebrew before the first run.
Keep Kokoro on its existing port, `8880`.

1. Copy this `speech` directory to `/Volumes/extssd/voice/theos-speech`.
2. Run `uv sync --locked --no-dev` from that directory.
3. Create a private `.env` file with these settings:

   ```dotenv
   AGENT_SPEECH_UPSTREAM_URL=http://127.0.0.1:8880/v1
   AGENT_SPEECH_KEY=replace-with-a-random-secret-of-at-least-32-characters
   AGENT_SPEECH_HOST=127.0.0.1
   AGENT_SPEECH_PORT=8881
   AGENT_SPEECH_FFMPEG=/opt/homebrew/bin/ffmpeg
   ```

4. Set the file mode to `0600` and run `uv run --no-dev theos-speech`.
5. Check `http://127.0.0.1:8881/health` for profile `theos-subtle-v1`.
6. Expose this loopback port through the existing private network or an authenticated tunnel.
7. Set these values in the assistant's private environment:

   ```dotenv
   AGENT_KOKORO_URL=https://your-private-speech-gateway/v1
   AGENT_KOKORO_KEY=the-same-private-gateway-secret
   AGENT_KOKORO_VOICE=am_michael(0.7)+bm_george(0.3)
   AGENT_KOKORO_SPEED=0.9
   ```

Existing environment values override the assistant's new defaults.
Restart the assistant through its normal release process after changing its environment.
Do not put the upstream Kokoro URL in `AGENT_KOKORO_URL` when you want the robotic effect.
Direct Kokoro connections still work, but return the unprocessed voice blend.

`GET /health` checks the gateway process, not the upstream model or FFmpeg.
`POST /v1/audio/speech` requires the bearer key and accepts `mp3` or `wav` output.
The gateway serializes synthesis and processing. It never forwards its bearer key to Kokoro.
It returns a generic HTTP 502 on synthesis, decoding, or encoding failure, without retrying the request.
There is no fallback to unprocessed audio.

## Check a change

Run `uv sync --locked`, then `uv run pytest -q` from this directory.
The tests use synthetic signals and an HTTP fixture, with no model download.
The MP3 check requires FFmpeg.
The separate speech workflow checks Linux. Native Mac mini checks use the live Kokoro endpoint.

Dependencies: [FastAPI](https://github.com/fastapi/fastapi), [HTTPX](https://github.com/encode/httpx),
[Pedalboard](https://github.com/spotify/pedalboard), [NumPy](https://numpy.org/),
[SciPy](https://scipy.org/), [SoundFile](https://github.com/bastibe/python-soundfile),
[pyloudnorm](https://github.com/csteinmetz1/pyloudnorm), and [FFmpeg](https://ffmpeg.org/).
`uv.lock` pins the Python dependencies. The system provides FFmpeg.
