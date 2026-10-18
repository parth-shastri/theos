import asyncio
import json
import shutil
import subprocess
from io import BytesIO

import httpx
import numpy as np
import pytest
import soundfile as sf

from theos_speech.effects import apply_voice
from theos_speech.server import Settings, create_app

KEY = "s" * 32
AUTH = {"Authorization": "Bearer " + KEY}


def waveform(duration=1, silent=False):
    time = np.arange(round(duration * 24000)) / 24000
    signal = np.zeros_like(time) if silent else 0.15 * np.sin(2 * np.pi * 115 * time)
    output = BytesIO()
    sf.write(output, signal, 24000, format="WAV")
    return output.getvalue()


@pytest.mark.parametrize("duration,silent", [(1, False), (0.1, False), (0.1, True)])
def test_effect_retains_duration_and_bounds_audio(duration, silent):
    audio, sr = sf.read(BytesIO(apply_voice(waveform(duration, silent))))
    assert sr == 24000 and len(audio) == round(duration * sr)
    assert np.isfinite(audio).all() and np.max(np.abs(audio)) <= 10 ** (-1.5 / 20)
    assert np.any(audio) != silent


async def request(upstream, payload, headers=AUTH):
    app = create_app(Settings(key=KEY, _env_file=None), upstream=upstream)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            return await client.post("/v1/audio/speech", json=payload, headers=headers)


async def test_request_authentication_and_pcm_contract():
    seen = []

    def endpoint(req):
        seen.append(req)
        assert "Authorization" not in req.headers
        assert json.loads(req.content) == {
            "model": "kokoro",
            "input": "Hello",
            "voice": "am_michael(0.7)+bm_george(0.3)",
            "speed": 0.9,
            "response_format": "wav",
        }
        return httpx.Response(200, content=waveform())

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as upstream:
        payload = {"input": "Hello", "response_format": "wav"}
        assert (await request(upstream, payload, {})).status_code == 401
        assert not seen
        response = await request(upstream, payload)
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    audio, sr = sf.read(BytesIO(response.content))
    assert len(audio) == sr


@pytest.mark.parametrize(
    "body", [{"input": " "}, {"input": "x" * 12001}, {"input": "x", "speed": 0}]
)
async def test_invalid_requests_never_reach_synthesis(body):
    def endpoint(req):
        pytest.fail("Invalid text reached the synthesis service.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as upstream:
        assert (await request(upstream, body)).status_code == 422


@pytest.mark.parametrize("status,body", [(503, b"private upstream detail"), (200, b"not audio")])
async def test_upstream_failures_do_not_return_audio_or_private_errors(status, body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(status, content=body))
    ) as upstream:
        response = await request(upstream, {"input": "Hello"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Speech generation failed."}


async def test_mp3_is_decodable():
    executable = shutil.which("ffmpeg")
    if not executable:
        pytest.skip("FFmpeg is required for the MP3 integration check.")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=waveform()))
    ) as upstream:
        response = await request(upstream, {"input": "Hello"})
    assert response.status_code == 200 and response.headers["content-type"] == "audio/mpeg"
    decoded = subprocess.run(
        [executable, "-v", "error", "-i", "pipe:0", "-f", "wav", "pipe:1"],
        input=response.content,
        capture_output=True,
        check=True,
    ).stdout
    audio, sr = sf.read(BytesIO(decoded))
    assert 0.95 <= len(audio) / sr <= 1.15 and np.any(audio)


async def test_synthesis_is_serialized():
    active = maximum = 0

    async def endpoint(req):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, content=waveform())

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as upstream:
        app = create_app(Settings(key=KEY, _env_file=None), upstream=upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                results = await asyncio.gather(
                    *[
                        client.post(
                            "/v1/audio/speech",
                            json={"input": "Hello", "response_format": "wav"},
                            headers=AUTH,
                        )
                        for _ in range(2)
                    ]
                )
    assert all(r.status_code == 200 for r in results) and maximum == 1
