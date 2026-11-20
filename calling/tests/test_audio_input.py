"""Bound response capture, silence rejection, and temporary audio cleanup."""

import asyncio
import io
import wave

from theos_calling.audio_input import MAX_PCM, SAMPLE_RATE, AudioInput


async def test_short_speech_and_trailing_silence_produce_a_bounded_wav():
    capture = AudioInput()
    capture.feed(123, b"\x00\x04" * (SAMPLE_RATE // 3))
    capture.feed(123, b"\x00\x00" * SAMPLE_RATE)
    result = await capture.finish(asyncio.Event())
    with wave.open(io.BytesIO(result), "rb") as clip:
        assert (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) == (
            1,
            2,
            SAMPLE_RATE,
        )
        assert clip.getnframes() <= 480000
    assert not capture.buffer


async def test_silence_disconnect_and_oversized_frames_never_become_a_decision():
    for case in ("silence", "disconnect", "oversized"):
        capture = AudioInput()
        ended = asyncio.Event()
        if case == "oversized":
            capture.feed(123, b"\x00\x04" * (MAX_PCM // 2 + 1))
        else:
            capture.feed(123, b"\x00\x00" * SAMPLE_RATE)
            if case == "disconnect":
                ended.set()
            else:
                capture.done.set()
        assert await capture.finish(ended) is None
        assert not capture.buffer


async def test_truncated_speech_cannot_authorize_its_positive_opening():
    capture = AudioInput()
    capture.feed(123, b"\x00\x04" * (SAMPLE_RATE // 3))
    assert capture.heard.is_set()
    capture.feed(123, b"\x00\x04" * (MAX_PCM // 2))
    assert capture.truncated and capture.done.is_set()
    assert await capture.finish(asyncio.Event()) is None
    assert not capture.buffer
