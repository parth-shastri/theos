"""Keep sequenced responses and replies private to one active voice conversation."""

import asyncio
import hashlib

from fastapi import HTTPException


class Dialogue:
    def __init__(self, id, recipient):
        self.id, self.recipient = id, recipient
        self.turn = 0
        self.response = None
        self.feedback = None
        self.completed = {}

    async def answer(self, audio):
        self.turn += 1
        if self.turn > 20:
            return None
        self.feedback = asyncio.get_running_loop().create_future()
        self.response = audio
        try:
            async with asyncio.timeout(90):
                return await self.feedback
        except TimeoutError:
            return None
        finally:
            self.response = None

    def finish(self, audio, turn, end=False):
        digest = hashlib.sha256(audio + bytes([end])).hexdigest()
        if turn in self.completed:
            if self.completed[turn] != digest:
                raise HTTPException(409, "This voice turn already has a different reply.")
            return
        if turn != self.turn or self.response is None or not self.feedback or self.feedback.done():
            raise HTTPException(409, "This voice turn is not waiting for a reply.")
        self.completed[turn] = digest
        self.feedback.set_result((audio, end))

    def close(self):
        self.response = None
        if self.feedback and not self.feedback.done():
            self.feedback.cancel()
