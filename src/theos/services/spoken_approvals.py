"""Bind natural spoken decisions to a complete, unchanged approval review."""

import io
import json
import re
import time
import wave

from theos.runtime.approvals import review_digest
from theos.runtime.reviews import approval_review, tool_label

MAX_RESPONSE = 48000 * 2 * 30 + 44
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
        "After I finish, tell me whether to approve or decline, or ask a question. Silence leaves it pending."
    )
    # Never omit fields or truncate a review to make a risky action fit a call.
    return prompt if len(prompt) <= 600 else None


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
                and 0 < source.getnframes() <= 1440000
                and len(source.readframes(source.getnframes())) == source.getnframes() * 2
            )
    except (wave.Error, EOFError):
        return False


class SpokenApprovals:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = runtime.phone_calls
        self.db = runtime.db

    @property
    def available(self):
        return bool(
            self.calls.provider == "telegram"
            and self.calls.available
            and (self.calls.config.spoken_approvals or self.calls.config.two_way)
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
            or (job.get("conversation_expires") or 0) <= time.time()
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
            and (job.get("conversation_expires") or 0) > time.time()
        )

    def finish(self, id, status):
        self.db.execute(
            "UPDATE phone_calls SET voice_status=?,voice_decided=? WHERE id=? AND (voice_status IS NULL OR voice_status NOT IN ('approved','denied'))",
            (status, time.time(), id),
        )
