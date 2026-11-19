"""Keep one bounded spoken response in memory after the outgoing prompt ends."""

import asyncio
import io
import math
import sys
import wave
from array import array

SAMPLE_RATE = 48000
MAX_SECONDS = 30
MAX_PCM = SAMPLE_RATE * 2 * MAX_SECONDS


class AudioInput:
    def __init__(self):
        self.done = asyncio.Event()
        self.heard = asyncio.Event()
        self.buffer = bytearray()
        self.voice_bytes = 0
        self.quiet_bytes = 0
        self.source = None
        self.truncated = False

    def feed(self, source, pcm):
        if self.done.is_set() or not pcm or len(pcm) % 2:
            return
        if self.source is not None and source != self.source:
            return
        self.source = source
        if len(self.buffer) + len(pcm) > MAX_PCM:
            self.truncated = True
            self.done.set()
            return
        samples = array("h", pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        voiced = rms >= 350
        if voiced:
            self.heard.set()
            self.voice_bytes += len(pcm)
            self.quiet_bytes = 0
        elif self.voice_bytes:
            self.quiet_bytes += len(pcm)
        # Retain at most a short pre-roll while waiting for speech.
        if not self.voice_bytes:
            self.buffer.extend(pcm)
            del self.buffer[: -SAMPLE_RATE // 2]
        else:
            self.buffer.extend(pcm)
        if self.voice_bytes >= SAMPLE_RATE // 2 and self.quiet_bytes >= SAMPLE_RATE * 2:
            self.done.set()

    async def finish(self, disconnected):
        speech = asyncio.create_task(self.done.wait())
        ended = asyncio.create_task(disconnected.wait())
        heard = asyncio.create_task(self.heard.wait())
        try:
            await asyncio.wait(
                (heard, ended, speech), timeout=30, return_when=asyncio.FIRST_COMPLETED
            )
            if not self.heard.is_set() or disconnected.is_set():
                return None
            await asyncio.wait(
                (speech, ended), timeout=MAX_SECONDS, return_when=asyncio.FIRST_COMPLETED
            )
            if (
                disconnected.is_set()
                or self.truncated
                or not self.done.is_set()
                or self.voice_bytes < SAMPLE_RATE // 2
            ):
                return None
            result = io.BytesIO()
            with wave.open(result, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(SAMPLE_RATE)
                output.writeframes(self.buffer)
            return result.getvalue()
        finally:
            speech.cancel()
            ended.cancel()
            heard.cancel()
            await asyncio.gather(speech, ended, heard, return_exceptions=True)
            self.buffer.clear()
