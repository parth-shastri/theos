"""Speech and transcription clients backed by the private file catalog."""

import httpx

from theos.services.errors import ServiceError


class Voice:
    """Own voice configuration and an HTTP client supplied by the runtime."""

    def __init__(self, settings, http, files, prepare=None):
        self.settings = settings
        self.http = http
        self.files = files
        self.prepare = prepare

    async def transcribe(self, owner, file_id):
        """Send an owned audio file to the configured transcription service."""
        # Check ownership before sending private audio to the transcription service.
        row = self.files.get(owner, file_id)
        if not self.settings.transcription_url:
            raise ServiceError("Set the transcription service URL before you send voice messages.")
        return await self.transcribe_audio(
            await self.files.read(owner, file_id), row["name"], row["media_type"]
        )

    async def transcribe_audio(self, audio, name, media_type, *, timeout=30):
        """Transcribe an already-authorized ephemeral clip without adding it to the catalog."""
        if not self.settings.transcription_url:
            raise ServiceError("Set the transcription service URL before you send voice messages.")
        try:
            response = await self.http.post(
                self.settings.transcription_url.rstrip("/") + "/audio/transcriptions",
                headers={
                    "Authorization": "Bearer " + self.settings.transcription_key.get_secret_value()
                },
                data={"model": self.settings.transcription_model},
                files={"file": (name, audio, media_type)},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()["text"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise ServiceError(
                "Voice transcription failed. Check the transcription service."
            ) from error

    async def speech(self, owner, text, *, session_id=None):
        """Generate bounded speech text and save the returned audio."""
        if not text.strip() or len(text) > 12000:
            raise ValueError("Supply speech text from 1 to 12000 characters.")
        if not self.settings.kokoro_url:
            raise ServiceError("Set the Kokoro service URL before you request speech.")
        if self.prepare is None:
            raise ServiceError("Expressive speech preparation is unavailable.")
        text = await self.prepare(owner, text, session_id=session_id)
        audio = await self.synthesize(text)
        return self.files.save(owner, "speech.mp3", "audio/mpeg", audio)

    async def synthesize(self, text, *, max_bytes=None):
        """Render literal text with the configured Kokoro voice and speech gateway."""
        if not self.settings.kokoro_url:
            raise ServiceError("Set the Kokoro service URL before you request speech.")
        try:
            async with self.http.stream(
                "POST",
                self.settings.kokoro_url.rstrip("/") + "/audio/speech",
                timeout=httpx.Timeout(120, connect=10),
                headers=(
                    {"Authorization": "Bearer " + self.settings.kokoro_key.get_secret_value()}
                    if self.settings.kokoro_key.get_secret_value()
                    else {}
                ),
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": self.settings.kokoro_voice,
                    "speed": self.settings.kokoro_speed,
                    "response_format": "mp3",
                },
            ) as response:
                response.raise_for_status()
                if max_bytes is None:
                    return await response.aread()
                if response.headers.get("content-type", "").split(";", 1)[0] != "audio/mpeg":
                    raise ServiceError("The speech service did not return MP3 audio.")
                audio = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(audio) + len(chunk) > max_bytes:
                        raise ServiceError("Generated speech exceeds the phone audio limit.")
                    audio.extend(chunk)
                if not audio:
                    raise ServiceError("The speech service returned empty audio.")
                return bytes(audio)
        except httpx.HTTPError as error:
            raise ServiceError("Speech generation failed. Check the Kokoro service.") from error
