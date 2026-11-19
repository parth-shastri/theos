"""Apply a short spoken decision only to the unchanged approval read in that call."""

import asyncio
import hashlib
import io
import json
import logging
import re
import time
import wave

import httpx

from theos.runtime.approvals import review_digest
from theos.runtime.reviews import approval_review, tool_label

from .errors import ServiceError

logger = logging.getLogger("theos")
MAX_RESPONSE = 48000 * 2 * 10 + 44
MAX_AUDIO = 2 * 1024 * 1024


def spoken_prompt(row, name):
    preview = json.loads(row["preview"])
    if not isinstance(preview, dict) or not preview:
        return None
    # The hash and draft ID bind the review but are not useful spoken contents.
    if row["tool"] == "gmail_send_draft":
        if re.search(r"</?[A-Za-z][^>]*>", str(preview.get("body", ""))):
            return None
        preview = {
            key: value for key, value in preview.items() if key not in {"draft_id", "sha256"}
        }
    fields = approval_review(row["tool"], preview)
    if not any(
        not field["technical"] and field["text"] not in {"Not set", "None", "(empty)"}
        for field in fields
    ):
        return None
    contents = ". ".join(
        f"{field['group'] + '. ' if field['group'] else ''}{field['label']}: {field['text']}"
        + (". " + field["hint"] if field.get("hint") else "")
        for field in fields
    )
    prompt = (
        f"This is {name}. One action needs your decision. {tool_label(row['tool'])}. "
        f"Action details begin. {contents}. Action details end. "
        "After I finish, say yes to approve this action or no to decline. Silence leaves it pending."
    )
    # Never omit fields or truncate a review to make a risky action fit a call.
    return prompt if len(prompt) <= 600 else None


def decision(text):
    if not isinstance(text, str) or len(text) > 80 or "?" in text:
        return None
    normalized = re.sub(r"[\s.,!]+", " ", text.casefold().replace("’", "'")).strip()
    yes = {
        "yes",
        "approve",
        "approve it",
        "yes approve",
        "yes approve it",
        "yes please",
        "yes please approve",
        "yes do it",
        "yes go ahead",
        "go ahead",
    }
    no = {
        "no",
        "decline",
        "decline it",
        "reject",
        "reject it",
        "cancel",
        "cancel it",
        "no decline",
        "no please",
        "no thank you",
        "no cancel",
        "do not approve",
        "don't approve",
        "no do not approve",
        "no don't approve",
        "no don't",
        "no do not",
        "don't do it",
        "don't do that",
        "no don't do that",
        "no don't do it",
        "no do not do it",
        "do not do it",
    }
    if normalized in yes:
        return True
    if normalized in no:
        return False
    return None


def valid_response(audio):
    if not 44 < len(audio) <= MAX_RESPONSE:
        return False
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            return (
                (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                )
                == (1, 2, 48000, "NONE")
                and 0 < source.getnframes() <= 480000
                and len(source.readframes(source.getnframes())) == source.getnframes() * 2
            )
    except (wave.Error, EOFError):
        return False


class SpokenApprovals:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = runtime.phone_calls
        self.db = runtime.db
        self.workers = set()

    @property
    def available(self):
        return bool(
            self.calls.provider == "telegram"
            and self.calls.available
            and self.calls.config.spoken_approvals
            and self.runtime.settings.transcription_url.strip()
        )

    def approval(self, job):
        return self.db.one(
            "SELECT * FROM approvals WHERE id=? AND session=?", (job["source_id"], job["session"])
        )

    async def current(self, job, digest, recipient):
        if (
            not self.available
            or self.calls._available(job) != recipient
            or (job.get("attempted") and job["attempted"] + 150 <= time.time())
        ):
            return False
        row = self.approval(job)
        if (
            not row
            or row["status"] != "pending"
            or row["expires"] <= time.time()
            or review_digest(row) != digest
        ):
            return False
        session = self.runtime.session(job["owner"], job["session"])
        current = await self.runtime.approval_preview(
            session, row["tool"], json.loads(row["arguments"])
        )
        if current != json.loads(row["preview"]):
            return False
        # Access or the saved review can change while the provider read is in progress.
        row = self.approval(job)
        return bool(
            self.available
            and self.calls._available(job) == recipient
            and row
            and row["status"] == "pending"
            and row["expires"] > time.time()
            and review_digest(row) == digest
            and (not job.get("attempted") or job["attempted"] + 150 > time.time())
        )

    async def dispatch(self, job, recipient):
        if not self.available or job["kind"] != "approval":
            return False
        row = self.approval(job)
        prompt = spoken_prompt(row, self.runtime.settings.name) if row else None
        if not prompt or job["expires"] - time.time() < 160:
            return False
        digest = review_digest(row)
        try:
            if not await self.current(job, digest, recipient):
                return False
            async with asyncio.timeout(35):
                audio = await self.calls.voice.synthesize(prompt, max_bytes=MAX_AUDIO)
            if not await self.current(job, digest, recipient):
                return False
        except (ServiceError, TimeoutError, httpx.HTTPError, PermissionError):
            return False
        self.db.execute(
            "UPDATE phone_calls SET voice_review_digest=?,voice_recipient=?,voice_status='listening' WHERE id=? AND status='pending'",
            (digest, recipient, job["id"]),
        )
        await self.calls._telegram(job, recipient, audio, interactive=True)
        if (
            self.db.one("SELECT status FROM phone_calls WHERE id=?", (job["id"],))["status"]
            != "accepted"
        ):
            self.finish(job["id"], "uncertain")
        return True

    def finish(self, id, status):
        self.db.execute(
            "UPDATE phone_calls SET voice_status=?,voice_decided=? WHERE id=? AND (voice_status IS NULL OR voice_status NOT IN ('approved','denied'))",
            (status, time.time(), id),
        )

    async def response(self, job):
        async with self.runtime.http.stream(
            "GET",
            self.calls.config.url.rstrip("/") + "/v1/calls/" + job["id"] + "/response",
            headers={"Authorization": "Bearer " + self.calls.config.key.get_secret_value()},
            timeout=5,
        ) as response:
            if response.status_code == 204:
                return None
            if response.status_code in {404, 410}:
                self.finish(job["id"], "unanswered")
                return None
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";", 1)[0] != "audio/wav":
                raise ServiceError("The spoken response has an invalid audio format.")
            audio = bytearray()
            async for chunk in response.aiter_bytes():
                if len(audio) + len(chunk) > MAX_RESPONSE:
                    raise ServiceError("The spoken response exceeds the audio limit.")
                audio.extend(chunk)
            if not valid_response(audio):
                raise ServiceError("The spoken response has an invalid audio format.")
            return bytes(audio)

    async def tick(self, telegram=None):
        self.db.execute(
            "UPDATE phone_calls SET voice_status='expired' WHERE voice_status='listening' AND (expires<=? OR attempted+150<=?)",
            (time.time(), time.time()),
        )
        if not self.available:
            self.db.execute(
                "UPDATE phone_calls SET voice_status='unavailable' WHERE voice_status='listening'"
            )
            return
        for job in self.db.rows(
            "SELECT * FROM phone_calls WHERE voice_status='listening' AND status='accepted' AND expires>? ORDER BY due LIMIT 5",
            (time.time(),),
        ):
            try:
                audio = await self.response(job)
                if audio is None:
                    continue
                claimed = self.db.execute(
                    "UPDATE phone_calls SET voice_status='processing',voice_response_digest=? WHERE id=? AND voice_status='listening'",
                    (hashlib.sha256(audio).hexdigest(), job["id"]),
                )
                if claimed.rowcount:
                    await self.process(job, audio, telegram)
            except asyncio.CancelledError:
                self.finish(job["id"], "uncertain")
                raise
            except ServiceError:
                self.finish(job["id"], "unrecognized")
                await self.feedback(
                    job,
                    "I could not understand your response. The approval is still pending. Review it in Theos.",
                )
            except httpx.HTTPError:
                # A read can be retried while the bounded gateway response remains available.
                state = self.db.one("SELECT voice_status FROM phone_calls WHERE id=?", (job["id"],))
                if state and state["voice_status"] == "processing":
                    self.finish(job["id"], "uncertain")
                continue
            except Exception as error:
                self.finish(job["id"], "uncertain")
                logger.warning(
                    "spoken_approval_uncertain", extra={"error_type": type(error).__name__}
                )

    async def interpret(self, job, audio):
        recipient, digest = job["voice_recipient"], job["voice_review_digest"]
        if not await self.current(job, digest, recipient):
            return "stale"
        text = await self.calls.voice.transcribe_audio(
            audio, "spoken-response.wav", "audio/wav", timeout=15
        )
        approved = decision(text)
        if approved is None:
            return "unrecognized"
        if not await self.current(job, digest, recipient):
            return "stale"
        return approved

    async def process(self, job, audio, telegram):
        try:
            async with asyncio.timeout(25):
                approved = await self.interpret(job, audio)
        except TimeoutError:
            approved = "uncertain"
        if type(approved) is not bool:
            self.finish(job["id"], approved)
            text = {
                "stale": "The action changed or is no longer available. I did not apply a decision. Review it in Theos.",
                "unrecognized": "I did not hear a clear yes or no. The approval is still pending. Review it in Theos.",
                "uncertain": "I could not process your response in time. I did not apply a decision. Review it in Theos.",
            }[approved]
            await self.feedback(job, text)
            return
        digest = job["voice_review_digest"]
        status = "approved" if approved else "denied"
        # Save the voice outcome and the exact approval decision in one transaction.
        # No await occurs before the runtime has reserved its one resumed turn.
        with self.db.transaction():
            turn = self.runtime.start(
                job["owner"],
                job["session"],
                approval=(job["source_id"], approved),
                expected_approval_digest=digest,
                browser_ui=self.runtime.session(job["owner"], job["session"])["channel"]
                == "browser",
            )
            self.finish(job["id"], status)
            self.db.execute(
                "INSERT OR IGNORE INTO notifications(id,owner,session,text,created,delivered) VALUES (?,?,?,?,?,0)",
                (
                    "voice-decision:" + job["id"],
                    job["owner"],
                    job["session"],
                    "Your spoken approval was recorded. Open the conversation to see the result."
                    if approved
                    else "Your spoken decline was recorded. The requested action was declined.",
                    time.time(),
                ),
            )
        worker = asyncio.create_task(self.deliver(turn, telegram))
        self.workers.add(worker)
        worker.add_done_callback(self.completed)
        await self.feedback(
            job,
            "Your approval was recorded."
            if approved
            else "Your decline was recorded. I will not run that action.",
        )

    async def feedback(self, job, text):
        try:
            async with asyncio.timeout(12):
                audio = await self.calls.voice.synthesize(text, max_bytes=MAX_AUDIO)
                response = await self.runtime.http.post(
                    self.calls.config.url.rstrip("/") + "/v1/calls/" + job["id"] + "/finish",
                    headers={
                        "Authorization": "Bearer " + self.calls.config.key.get_secret_value(),
                        "Content-Type": "audio/mpeg",
                    },
                    content=audio,
                    timeout=5,
                )
                response.raise_for_status()
        except (ServiceError, httpx.HTTPError, TimeoutError):
            # Feedback delivery never repeats a recorded decision or external action.
            logger.warning("spoken_approval_feedback_unavailable")

    async def deliver(self, turn, telegram):
        try:
            session = self.runtime.session(turn.owner, turn.session_id)
            if session["channel"] == "telegram-private" and telegram:
                chat, topic = session["address"].split(":")
                await telegram.render(turn, int(chat), int(topic) or None)
            else:
                async for _ in turn.events():
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "spoken_approval_delivery_uncertain", extra={"error_type": type(error).__name__}
            )
        finally:
            if turn.task and not turn.task.done():
                await asyncio.shield(turn.task)

    async def close(self):
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    def completed(self, worker):
        self.workers.discard(worker)
        if not worker.cancelled():
            error = worker.exception()
            if error:
                logger.warning(
                    "spoken_approval_delivery_uncertain", extra={"error_type": type(error).__name__}
                )
