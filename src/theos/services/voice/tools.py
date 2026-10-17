"""Speech output and audio transcription."""

from harness import tool


def voice_tools(voice, owner, session_id=None):
    """Build speech and transcription tools bound to the authenticated owner."""

    @tool
    async def send_text_to_speech(text: str):
        """Write an expressive spoken rendition, generate speech, and deliver the audio file."""
        row = await voice.speech(owner, text, session_id=session_id)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @tool
    async def transcribe_file(file_id: str):
        """Transcribe an uploaded audio file."""
        return {"text": await voice.transcribe(owner, file_id)}

    return [send_text_to_speech, transcribe_file]
