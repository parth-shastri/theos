"""Keep a response and its acknowledgement private to one active call."""

import asyncio
import hashlib

from fastapi import HTTPException


class Dialogue:
    def __init__(self, id, recipient):
        self.id, self.recipient = id, recipient
        self.response = None
        self.feedback = asyncio.get_running_loop().create_future()
        self.feedback_digest = None

    async def answer(self, audio):
        self.response = audio
        try:
            async with asyncio.timeout(40):
                return await self.feedback
        except TimeoutError:
            return None
        finally:
            self.response = None

    def finish(self, audio):
        digest = hashlib.sha256(audio).hexdigest()
        if self.feedback.done():
            if self.feedback_digest != digest:
                raise HTTPException(409, "The call response was already completed.")
            return
        if self.response is None:
            raise HTTPException(409, "The call has no spoken response waiting.")
        self.feedback_digest = digest
        self.feedback.set_result(audio)

    def close(self):
        self.response = None
        if not self.feedback.done():
            self.feedback.cancel()
