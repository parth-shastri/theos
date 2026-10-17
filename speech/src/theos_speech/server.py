"""Private HTTP gateway for Kokoro and the approved Theos voice effects."""

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .effects import apply_voice


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_SPEECH_", env_file=".env", extra="ignore")

    upstream_url: str = "http://127.0.0.1:8880/v1"
    key: SecretStr = Field(min_length=32)
    host: str = "127.0.0.1"
    port: int = Field(default=8881, ge=1, le=65535)
    ffmpeg: str = "ffmpeg"


class SpeechInput(BaseModel):
    model: Literal["kokoro"] = "kokoro"
    input: str = Field(min_length=1, max_length=12000)
    voice: str = Field(default="am_michael(0.7)+bm_george(0.3)", min_length=1, max_length=200)
    speed: float = Field(default=0.9, ge=0.5, le=2)
    response_format: Literal["mp3", "wav"] = "mp3"

    @field_validator("input")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Supply speech text.")
        return value


async def encode_mp3(wav: bytes, executable: str) -> bytes:
    """Encode through pipes without a shell or persisted private speech files."""
    process = await asyncio.create_subprocess_exec(
        executable,
        "-v",
        "error",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-f",
        "mp3",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(30):
            output, _ = await process.communicate(wav)
        if process.returncode or not output:
            raise ValueError("Audio encoding failed.")
        return output
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def create_app(settings: Settings, *, upstream=None):
    """Keep a single HTTP pool and bound synthesis and DSP to one active request."""

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as http:
            app.state.upstream = upstream or http
            yield

    app = FastAPI(lifespan=lifespan)
    lock = asyncio.Lock()

    @app.get("/health")
    async def health():
        return {"status": "ok", "profile": "theos-subtle-v1"}

    @app.post("/v1/audio/speech")
    async def speech(body: SpeechInput, request: Request):
        expected = "Bearer " + settings.key.get_secret_value()
        supplied = request.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "Speech authentication required.")
        async with lock:
            try:
                response = await request.app.state.upstream.post(
                    settings.upstream_url.rstrip("/") + "/audio/speech",
                    json={**body.model_dump(), "response_format": "wav"},
                )
                response.raise_for_status()
                audio = await asyncio.to_thread(apply_voice, response.content)
                if body.response_format == "mp3":
                    audio = await encode_mp3(audio, settings.ffmpeg)
            except (httpx.HTTPError, ValueError, RuntimeError, OSError, TimeoutError):
                raise HTTPException(502, "Speech generation failed.") from None
        media_type = "audio/mpeg" if body.response_format == "mp3" else "audio/wav"
        return Response(audio, media_type=media_type, headers={"Cache-Control": "no-store"})

    return app


def main():
    import uvicorn

    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)
