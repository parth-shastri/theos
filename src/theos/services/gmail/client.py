"""Gmail access and draft sending with content-bound approval."""

import base64
import hashlib
import re
from email import policy
from email.parser import BytesParser
from urllib.parse import quote

import httpx

from harness.tools import OutcomeUnknown
from theos.services.errors import ServiceError


def resource_id(value):
    """Validate and encode a Gmail resource identifier."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,300}", value):
        raise ValueError("The Gmail resource ID is invalid.")
    return quote(value, safe="")


def decode_raw(value):
    """Decode the unpadded base64 format returned by Gmail."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class Gmail:
    """Use the owner's OAuth grant. No tool accepts a Gmail account identifier."""

    def __init__(self, oauth, http, files):
        self.oauth = oauth
        self.http = http
        self.files = files

    async def request(self, owner, method, path, **kwargs):
        """Use the owner grant and preserve uncertainty after write failures."""
        token = await self.oauth.access_token(owner, "gmail")
        try:
            response = await self.http.request(
                method,
                "https://gmail.googleapis.com/gmail/v1/users/me/" + path,
                headers={"Authorization": "Bearer " + token},
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except httpx.TransportError as error:
            if method != "GET":
                raise OutcomeUnknown(
                    "The Gmail write outcome is unknown. Check Gmail before you repeat it."
                ) from error
            raise ServiceError("Gmail is unavailable. Try the read again later.") from error
        except (httpx.HTTPStatusError, ValueError) as error:
            raise ServiceError(
                "Gmail rejected the request. Check the account connection and resource ID."
            ) from error

    async def draft(self, owner, draft_id):
        """Read the raw draft for content checks."""
        return await self.request(
            owner, "GET", "drafts/" + resource_id(draft_id), params={"format": "raw"}
        )

    async def preview(self, owner, draft_id):
        """Build a review snapshot with recipients, contents, and a hash."""
        draft = await self.draft(owner, draft_id)
        message = draft["message"]
        if set(message.get("labelIds", [])) & {"SPAM", "TRASH"}:
            raise PermissionError("Do not send a draft in Spam or Trash.")
        raw = decode_raw(message["raw"])
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        body = parsed.get_body(preferencelist=("plain", "html"))
        return {
            "draft_id": draft_id,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "to": str(parsed.get("To", "")),
            "cc": str(parsed.get("Cc", "")),
            "bcc": str(parsed.get("Bcc", "")),
            "subject": str(parsed.get("Subject", "")),
            "body": body.get_content() if body else "",
            "attachments": [p.get_filename() for p in parsed.iter_attachments()],
        }

    def tools(self, owner):
        """Build the service tools for the authenticated owner."""
        from .tools import gmail_tools

        return gmail_tools(self, owner)
