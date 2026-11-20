"""Run bounded freeform conversations on an owner's existing private call."""

import asyncio
import hashlib
import json
import logging
import time

import httpx

from harness import AssistantMessage
from theos.runtime.approvals import review_digest

from .call_intent import classify
from .errors import ServiceError
from .spoken_approvals import MAX_AUDIO, MAX_RESPONSE, spoken_prompt, valid_response

logger = logging.getLogger("theos")


class CallConversations:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = runtime.phone_calls
        self.db = runtime.db

    @property
    def available(self):
        return bool(
            self.calls.provider == "telegram"
            and self.calls.available
            and (self.calls.config.two_way or self.calls.config.spoken_approvals)
            and self.runtime.settings.transcription_url.strip()
        )

    def authorized(self, job):
        try:
            session = self.runtime.session(job["owner"], job["session"])
        except LookupError:
            return False
        connection = self.calls.connections.row(job["owner"])
        testing = bool(connection and connection["test_call_id"] == job["id"])
        return bool(
            self.available
            and self.calls.recipient(job["owner"], session["channel"], testing=testing)
            == job["voice_recipient"]
            and job["conversation_expires"] > time.time()
        )

    def binding(self, job):
        pending = [
            {**row, "session": job["session"]}
            for row in self.runtime.pending(job["owner"], job["session"])
        ]
        row = next((row for row in pending if row["id"] == job.get("conversation_approval")), None)
        if row and review_digest(row) == job.get("conversation_review_digest"):
            return row, True
        return (pending[0], False) if pending else (None, False)

    def readback(self, job):
        row, _ = self.binding(job)
        if not row:
            return "", None, None
        prompt = spoken_prompt(row, self.runtime.settings.name)
        if not prompt:
            return (
                "This request needs a detailed review in Theos. You can ask about it here, but please approve it in the app.",
                None,
                None,
            )
        return prompt, row["id"], review_digest(row)

    async def dispatch(self, job, recipient, text):
        dialogue_expires = (
            min(job["expires"], time.time() + 300)
            if job["kind"] == "approval"
            else time.time() + 300
        )
        state = {
            **job,
            "voice_recipient": recipient,
            "conversation_expires": dialogue_expires,
            "conversation_approval": None,
            "conversation_review_digest": None,
        }
        review, approval, digest = self.readback(state)
        prompt = (
            review
            if review and job["kind"] == "approval"
            else f"This is {self.runtime.settings.name}. {text}" + (" " + review if review else "")
        )
        prompt += " You can reply naturally, ask a question, or say goodbye to end this call."
        try:
            async with asyncio.timeout(35):
                audio = await self.calls.voice.synthesize(prompt, max_bytes=MAX_AUDIO)
        except (ServiceError, TimeoutError):
            return self.calls._finish(job["id"], "failed")
        if (
            not self.available
            or self.calls._available(job) != recipient
            or not self.calls._source(job)
        ):
            return self.calls._finish(job["id"], "skipped")
        if approval:
            current = self.db.one("SELECT * FROM approvals WHERE id=?", (approval,))
            if not current or current["status"] != "pending" or review_digest(current) != digest:
                return self.calls._finish(job["id"], "skipped")
        self.db.execute(
            "UPDATE phone_calls SET conversation_status='active',conversation_expires=?,conversation_approval=?,conversation_review_digest=?,voice_recipient=?,voice_review_digest=?,voice_status=? WHERE id=? AND status='pending'",
            (
                dialogue_expires,
                approval,
                digest,
                recipient,
                digest,
                "listening" if approval else None,
                job["id"],
            ),
        )
        await self.calls._telegram(
            job, recipient, audio, interactive=True, dialogue_expires=dialogue_expires
        )
        status = self.db.one("SELECT status FROM phone_calls WHERE id=?", (job["id"],))["status"]
        if status != "accepted":
            self.db.execute(
                "UPDATE phone_calls SET conversation_status='uncertain' WHERE id=?", (job["id"],)
            )

    def headers(self):
        return {"Authorization": "Bearer " + self.calls.config.key.get_secret_value()}

    def url(self, job, suffix):
        return self.calls.config.url.rstrip("/") + "/v1/calls/" + job["id"] + "/" + suffix

    async def close_call(self, job):
        self.db.execute(
            "UPDATE call_utterances SET status='uncertain' WHERE call_id=? AND status='processing'",
            (job["id"],),
        )
        self.db.execute(
            "UPDATE phone_calls SET conversation_status='closed' WHERE id=?", (job["id"],)
        )
        try:
            await self.runtime.http.delete(
                self.url(job, "dialogue"), headers=self.headers(), timeout=5
            )
        except httpx.HTTPError:
            pass

    async def live(self, job, ordinal):
        if not self.authorized(job):
            return False
        response = await self.runtime.http.get(
            self.url(job, "dialogue"), headers=self.headers(), timeout=5
        )
        if response.status_code in {404, 410}:
            return False
        response.raise_for_status()
        body = response.json()
        return self.authorized(job) and body.get("turn") == ordinal and body.get("waiting") is True

    async def response(self, job):
        async with self.runtime.http.stream(
            "GET", self.url(job, "response"), headers=self.headers(), timeout=5
        ) as response:
            if response.status_code == 204:
                return None
            if response.status_code in {404, 410}:
                self.db.execute(
                    "UPDATE phone_calls SET conversation_status='closed' WHERE id=?", (job["id"],)
                )
                return None
            response.raise_for_status()
            ordinal = int(response.headers.get("X-Theos-Voice-Turn", "0"))
            if (
                not 1 <= ordinal <= 20
                or response.headers.get("content-type", "").split(";", 1)[0] != "audio/wav"
            ):
                raise ServiceError("The voice response has an invalid format.")
            audio = bytearray()
            async for chunk in response.aiter_bytes():
                if len(audio) + len(chunk) > MAX_RESPONSE:
                    raise ServiceError("The voice response exceeds its size limit.")
                audio.extend(chunk)
            if not valid_response(audio):
                raise ServiceError("The voice response has an invalid format.")
            return ordinal, bytes(audio)

    async def tick(self, telegram=None):
        self.db.execute(
            "UPDATE phone_calls SET conversation_status='closed' WHERE conversation_status='active' AND conversation_expires<=?",
            (time.time(),),
        )
        for job in self.db.rows(
            "SELECT * FROM phone_calls WHERE conversation_status='active' AND status='accepted' ORDER BY due LIMIT 5"
        ):
            if not self.authorized(job):
                await self.close_call(job)
                continue
            try:
                result = await self.response(job)
                if result is None:
                    continue
                ordinal, audio = result
                claimed = self.db.execute(
                    "INSERT OR IGNORE INTO call_utterances(call_id,ordinal,status,response_digest,created) VALUES (?,?,'processing',?,?)",
                    (job["id"], ordinal, hashlib.sha256(audio).hexdigest(), time.time()),
                )
                if not claimed.rowcount:
                    continue
                async with asyncio.timeout(80):
                    await self.process(job, ordinal, audio, telegram)
            except asyncio.CancelledError:
                self.db.execute(
                    "UPDATE call_utterances SET status='uncertain' WHERE call_id=? AND status='processing'",
                    (job["id"],),
                )
                self.db.execute(
                    "UPDATE phone_calls SET conversation_status='uncertain' WHERE id=?",
                    (job["id"],),
                )
                raise
            except Exception as error:
                # A failed turn is never re-transcribed or replayed as another instruction.
                self.db.execute(
                    "UPDATE call_utterances SET status='uncertain' WHERE call_id=? AND status='processing'",
                    (job["id"],),
                )
                await self.close_call(job)
                logger.warning(
                    "spoken_approval_worker_failed", extra={"error_type": type(error).__name__}
                )

    async def drain(self, job, turn, telegram):
        session = self.runtime.session(job["owner"], job["session"])
        if session["channel"] == "telegram-private" and telegram:
            chat, topic = session["address"].split(":")
            await telegram.render(turn, int(chat), int(topic) or None)
        else:
            async for _ in turn.events():
                pass

    async def normal_turn(self, job, ordinal, text, history, telegram):
        session = self.runtime.session(job["owner"], job["session"])
        active = self.runtime.active.get(session["id"])
        if active and active.task:
            done, _ = await asyncio.wait((active.task,), timeout=10)
            if not done:
                return "Theos is still working on the previous request. You can wait, or say goodbye to end this call."
        if not await self.live(job, ordinal):
            return ""
        if self.runtime.pending(job["owner"], job["session"]):
            return "A decision is waiting in this conversation. Please resolve that request first."
        turn = self.runtime.start(
            job["owner"], job["session"], text, voice_call=True, voice_context=history
        )
        await self.drain(job, turn, telegram)
        history = self.db.load_history(job["owner"], job["session"])
        reply = next(
            (
                message.text
                for message in reversed(history)
                if isinstance(message, AssistantMessage) and message.text
            ),
            "",
        )
        if not reply or len(reply) > 1600:
            return "I saved the result in Theos. Open the conversation for the full details. What else would you like to do?"
        return reply

    async def process(self, job, ordinal, audio, telegram):
        if not await self.live(job, ordinal):
            return await self.close_call(job)
        text = await self.calls.voice.transcribe_audio(
            audio, "call-response.wav", "audio/wav", timeout=15
        )
        if not await self.live(job, ordinal):
            return await self.close_call(job)
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            return await self.reply(
                job, ordinal, "I did not catch that. Could you say it another way?"
            )
        self.db.execute(
            "UPDATE call_utterances SET input_text=? WHERE call_id=? AND ordinal=?",
            (text, job["id"], ordinal),
        )
        row, read = self.binding(job)
        if job.get("conversation_approval") and not read:
            review, approval, digest = self.readback(job)
            return await self.reply(
                job,
                ordinal,
                "The previous action changed or is no longer pending. I did not apply a decision. "
                + review,
                approval=approval,
                digest=digest,
            )
        history = self.db.rows(
            "SELECT input_text,reply_text FROM call_utterances WHERE call_id=? AND ordinal<? ORDER BY ordinal",
            (job["id"], ordinal),
        )
        history.insert(
            0,
            {
                "input_text": "",
                "reply_text": self.calls._source(job) or "The call began with an approval review.",
            },
        )
        context = {
            "approval": None
            if not row
            else {"tool": row["tool"], "review": json.loads(row["preview"])},
            "review_read": read,
        }
        session = self.runtime.session(job["owner"], job["session"])
        try:
            intent = await classify(self.runtime, session, text, context, history)
        except ServiceError as error:
            return await self.reply(job, ordinal, str(error))
        self.db.execute(
            "UPDATE call_utterances SET intent=? WHERE call_id=? AND ordinal=?",
            (intent.intent, job["id"], ordinal),
        )
        if intent.intent == "end":
            return await self.reply(
                job, ordinal, intent.reply or "Goodbye.", end=True, status="ended"
            )
        if intent.intent in {"approve", "decline"} and row and read:
            digest = review_digest(row)
            bound = {
                **job,
                "kind": "request",
                "source_id": row["id"],
                "expires": min(row["expires"], job["conversation_expires"]),
            }
            if not await self.runtime.spoken_approvals.current(
                bound, digest, job["voice_recipient"]
            ) or not await self.live(job, ordinal):
                return await self.reply(
                    job,
                    ordinal,
                    "That action changed or is no longer available. I did not apply a decision. What would you like to do?",
                )
            approved = intent.intent == "approve"
            with self.db.transaction():
                turn = self.runtime.start(
                    job["owner"],
                    job["session"],
                    approval=(row["id"], approved),
                    expected_approval_digest=digest,
                    voice_call=True,
                    voice_context=history,
                )
                self.db.execute(
                    "UPDATE call_utterances SET status=?,approval_id=?,review_digest=? WHERE call_id=? AND ordinal=?",
                    ("approved" if approved else "denied", row["id"], digest, job["id"], ordinal),
                )
                self.runtime.spoken_approvals.finish(
                    job["id"], "approved" if approved else "denied"
                )
                self.db.execute(
                    "INSERT OR IGNORE INTO notifications(id,owner,session,text,created,delivered) VALUES (?,?,?,?,?,0)",
                    (
                        "voice-decision:" + job["id"] + ":" + str(ordinal),
                        job["owner"],
                        job["session"],
                        "Your spoken decision was recorded. Open the conversation to see the result.",
                        time.time(),
                    ),
                )
            await self.drain(job, turn, telegram)
            answer = (
                "Your approval was recorded."
                if approved
                else "Your decline was recorded. I will not run that action."
            )
        elif row:
            answer = intent.reply or "What would you like to know about this request?"
        else:
            if not await self.live(job, ordinal):
                return await self.close_call(job)
            answer = await self.normal_turn(job, ordinal, text, history, telegram)
        fresh = self.db.one("SELECT * FROM phone_calls WHERE id=?", (job["id"],))
        pending, heard = self.binding(fresh)
        approval, digest = None, None
        if pending:
            if heard:
                approval, digest = pending["id"], review_digest(pending)
            else:
                review, approval, digest = self.readback(fresh)
                answer += " " + review
        await self.reply(
            job, ordinal, answer, approval=approval, digest=digest, end=intent.end_call
        )

    async def reply(
        self, job, ordinal, text, *, end=False, status="replied", approval=None, digest=None
    ):
        if not await self.live(job, ordinal):
            return await self.close_call(job)
        end = end or ordinal >= 20
        async with asyncio.timeout(25):
            audio = await self.calls.voice.synthesize(text, max_bytes=MAX_AUDIO)
        if not await self.live(job, ordinal):
            return await self.close_call(job)
        # Bind the next listening turn before handing its exact spoken review to the gateway.
        self.db.execute(
            "UPDATE phone_calls SET conversation_approval=?,conversation_review_digest=? WHERE id=?",
            (approval, digest, job["id"]),
        )
        self.db.execute(
            "UPDATE call_utterances SET reply_text=?,status=CASE WHEN status IN ('approved','denied') THEN status ELSE ? END WHERE call_id=? AND ordinal=?",
            (text, status, job["id"], ordinal),
        )
        response = await self.runtime.http.post(
            self.url(job, "finish"),
            params={"turn": ordinal, "end": str(end).lower()},
            headers={**self.headers(), "Content-Type": "audio/mpeg"},
            content=audio,
            timeout=5,
        )
        response.raise_for_status()
        if end:
            self.db.execute(
                "UPDATE phone_calls SET conversation_status='closed' WHERE id=?", (job["id"],)
            )
