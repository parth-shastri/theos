"""Speech and transcription clients backed by the private file catalog."""

from pathlib import Path

import httpx

from theos.services.errors import ServiceError


class Voice:
    """Own voice configuration and an HTTP client supplied by the runtime."""

    def __init__(self, settings, http, files):
        self.settings = settings
        self.http = http
        self.files = files

    async def transcribe(self, owner, file_id):
        """Send an owned audio file to the configured transcription service."""
        # Check ownership before sending private audio to the transcription service.
        row = self.files.get(owner, file_id)
        if not self.settings.transcription_url:
            raise ServiceError("Set the transcription service URL before you send voice messages.")
        try:
            response = await self.http.post(
                self.settings.transcription_url.rstrip("/") + "/audio/transcriptions",
                headers={
                    "Authorization": "Bearer " + self.settings.transcription_key.get_secret_value()
                },
                data={"model": self.settings.transcription_model},
                files={"file": (row["name"], Path(row["path"]).read_bytes(), row["media_type"])},
            )
            response.raise_for_status()
            return response.json()["text"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise ServiceError(
                "Voice transcription failed. Check the transcription service."
            ) from error

    async def speech(self, owner, text):
        """Generate bounded speech text and save the returned audio."""
        if not text.strip() or len(text) > 12000:
            raise ValueError("Supply speech text from 1 to 12000 characters.")
        if not self.settings.kokoro_url:
            raise ServiceError("Set the Kokoro service URL before you request speech.")
        try:
            response = await self.http.post(
                self.settings.kokoro_url.rstrip("/") + "/audio/speech",
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": self.settings.kokoro_voice,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ServiceError("Speech generation failed. Check the Kokoro service.") from error
        return self.files.save(owner, "speech.mp3", "audio/mpeg", response.content)
