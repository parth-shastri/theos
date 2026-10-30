"""Serve Whisper on Apple Silicon through the existing transcription contract."""

import secrets
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL = "mlx-community/whisper-large-v3-turbo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_MLX_", env_file=".env", extra="ignore")

    key: SecretStr = Field(min_length=32)
    model_path: Path
    host: str = "127.0.0.1"
    port: int = Field(default=8002, ge=1, le=65535)
    ffmpeg: str = "ffmpeg"
    max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_seconds: int = Field(default=300, gt=0)


class Whisper:
    """Load and use the Metal model on one dedicated worker thread."""

    def __init__(self, settings):
        self.settings = settings

    def warm(self):
        import mlx.core as mx
        import mlx_whisper

        if not mx.metal.is_available():
            raise RuntimeError("Apple Metal is unavailable.")
        if (
            not (self.settings.model_path / "weights.npz").is_file()
            and not (self.settings.model_path / "weights.safetensors").is_file()
        ):
            raise RuntimeError("Download the MLX model before starting the service.")
        self.transcribe = mlx_whisper.transcribe
        # Exercise inference before readiness. Keep audio and transcripts out of logs.
        self.transcribe(
            np.zeros(16000, dtype=np.float32),
            path_or_hf_repo=str(self.settings.model_path),
            verbose=None,
        )

    def __call__(self, path):
        decoded = subprocess.run(
            [
                self.settings.ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(path),
                "-t",
                str(self.settings.max_seconds + 1),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=True,
        )
        audio = np.frombuffer(decoded.stdout, dtype=np.float32).copy()
        if not audio.size or audio.size > self.settings.max_seconds * 16000:
            raise ValueError("Audio duration is outside the supported range.")
        return self.transcribe(audio, path_or_hf_repo=str(self.settings.model_path), verbose=None)[
            "text"
        ].strip()


def create_app(settings: Settings, *, recognizer=None):
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-whisper")
    lock = threading.Lock()
    engine = recognizer if recognizer is not None else Whisper(settings)

    @asynccontextmanager
    async def lifespan(app):
        import asyncio

        try:
            await asyncio.wrap_future(worker.submit(engine.warm))
            yield
        finally:
            worker.shutdown(wait=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.path != "/health":
            expected = "Bearer " + settings.key.get_secret_value()
            supplied = request.headers.get("Authorization", "")
            if not secrets.compare_digest(supplied.encode(), expected.encode()):
                return JSONResponse({"detail": "Transcription authentication required."}, 401)
            length = request.headers.get("Content-Length", "0")
            if not length.isdecimal() or int(length) > settings.max_bytes + 65536:
                return JSONResponse({"detail": "Audio upload is too large."}, 413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "model": MODEL, "backend": "mlx"}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "mlx"}]}

    @app.post("/v1/audio/transcriptions")
    def transcribe(file: UploadFile = File(...), model: str = Form(...)):
        if model != MODEL:
            raise HTTPException(400, "Select the configured MLX Whisper model.")
        # Reject overlap instead of building a queue beyond the assistant's read timeout.
        if not lock.acquire(blocking=False):
            raise HTTPException(503, "Transcription is busy. Try again later.")
        try:
            with tempfile.TemporaryDirectory(prefix="theos-transcription-") as directory:
                path = Path(directory) / "audio"
                audio = file.file.read(settings.max_bytes + 1)
                if not audio:
                    raise HTTPException(400, "Supply a nonempty audio file.")
                if len(audio) > settings.max_bytes:
                    raise HTTPException(413, "Audio upload is too large.")
                path.write_bytes(audio)
                # A disconnected caller cannot release the model or delete its active file.
                return {"text": worker.submit(engine, path).result()}
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
            raise HTTPException(422, "Audio transcription failed.") from None
        finally:
            lock.release()

    return app


def main():
    import uvicorn

    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)
