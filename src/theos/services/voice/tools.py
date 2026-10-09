"""Speech output and audio transcription."""

from harness import tool


def voice_tools(voice, owner):
    """Build speech and transcription tools bound to the authenticated owner."""

    @tool
    async def send_text_to_speech(text: str):
        """Generate speech with Kokoro and deliver it as a file."""
        row = await voice.speech(owner, text)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @tool
    async def transcribe_file(file_id: str):
        """Transcribe an uploaded audio file."""
        return {"text": await voice.transcribe(owner, file_id)}

    return [send_text_to_speech, transcribe_file]
