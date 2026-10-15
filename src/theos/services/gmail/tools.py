"""Gmail tools bound to one owner and current draft approval."""

import base64
import json
from email.message import EmailMessage

from harness import tool
from harness.events import _tool_scope

from .client import decode_raw, resource_id


def gmail_tools(client, owner):
    """Build account tools bound to one authenticated private owner."""

    @tool
    async def gmail_connect():
        """Create a Google authorization link for your Gmail account."""
        return {"url": client.oauth.start(owner, "gmail")}

    @tool
    async def gmail_disconnect():
        """Disconnect your Gmail account and revoke its grant."""
        return await client.oauth.disconnect(owner, "gmail")

    @tool(parallel_safe=True)
    async def gmail_search_messages(query: str, page_token: str | None = None):
        """Search Gmail messages outside Spam and Trash."""
        params = {"q": f"({query}) -in:spam -in:trash", "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        return await client.request(owner, "GET", "messages", params=params)

    async def get_message(message_id):
        message = await client.request(
            owner, "GET", "messages/" + resource_id(message_id), params={"format": "full"}
        )
        if set(message.get("labelIds", [])) & {"SPAM", "TRASH"}:
            raise PermissionError("Messages in Spam or Trash are unavailable.")
        return message

    @tool(parallel_safe=True)
    async def gmail_get_message(message_id: str):
        """Read a Gmail message, including its MIME body and attachment IDs."""
        return await get_message(message_id)

    @tool(parallel_safe=True)
    async def gmail_get_thread(thread_id: str):
        """Read a Gmail thread outside Spam and Trash."""
        thread = await client.request(
            owner, "GET", "threads/" + resource_id(thread_id), params={"format": "full"}
        )
        thread["messages"] = [
            m
            for m in thread.get("messages", [])
            if not set(m.get("labelIds", [])) & {"SPAM", "TRASH"}
        ]
        return thread

    @tool
    async def gmail_download_attachment(message_id: str, attachment_id: str):
        """Download an attachment from one of your accessible messages."""
        message = await get_message(message_id)

        def find_part(part):
            if part.get("body", {}).get("attachmentId") == attachment_id:
                return part
            for child in part.get("parts", []):
                found = find_part(child)
                if found:
                    return found
            return None

        part = find_part(message.get("payload", {}))
        if not part:
            raise LookupError("Attachment not found in this message.")
        payload = await client.request(
            owner,
            "GET",
            f"messages/{resource_id(message_id)}/attachments/{resource_id(attachment_id)}",
        )
        row = client.files.save(
            owner,
            part.get("filename", "attachment"),
            part.get("mimeType", "application/octet-stream"),
            decode_raw(payload["data"]),
        )
        return {"file_id": row["id"], "name": row["name"]}

    @tool(parallel_safe=True)
    async def gmail_list_drafts(page_token: str | None = None):
        """List your Gmail drafts."""
        return await client.request(
            owner,
            "GET",
            "drafts",
            params={"maxResults": 50, **({"pageToken": page_token} if page_token else {})},
        )

    @tool(parallel_safe=True)
    async def gmail_get_draft(draft_id: str):
        """Read a draft with its recipients, subject, body, and content hash."""
        return await client.preview(owner, draft_id)

    @tool
    async def gmail_create_draft(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        attachment_ids: list[str] | None = None,
    ):
        """Create a draft. Sending requires a separate user approval."""
        message = EmailMessage()
        for name, value in (("To", to), ("Subject", subject), ("Cc", cc), ("Bcc", bcc)):
            if "\n" in value or "\r" in value:
                raise ValueError("Mail headers cannot contain line breaks.")
            if value:
                message[name] = value
        message.set_content(body)
        for file_id in attachment_ids or []:
            row = client.files.get(owner, file_id)
            from pathlib import Path

            major, minor = row["media_type"].split("/", 1)
            message.add_attachment(
                Path(row["path"]).read_bytes(),
                maintype=major,
                subtype=minor,
                filename=row["name"],
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return await client.request(owner, "POST", "drafts", json={"message": {"raw": raw}})

    @tool
    async def gmail_send_draft(draft_id: str):
        """Send a reviewed draft only after explicit approval of its current contents."""
        row = client.oauth.db.one(
            "SELECT a.preview FROM approvals a JOIN sessions s ON s.id=a.session WHERE s.owner=? AND a.call_id=? AND a.tool='gmail_send_draft' AND a.status='approved'",
            (owner, _tool_scope.get()),
        )
        # Another client can edit the draft after the runtime approval check.
        if not row or json.loads(row["preview"]) != await client.preview(owner, draft_id):
            raise PermissionError("The draft is not approved or its contents changed.")
        # A connection failure remains unknown. The runtime must not repeat the send.
        return await client.request(owner, "POST", "drafts/send", json={"id": draft_id})

    @tool(parallel_safe=True)
    async def gmail_list_labels():
        """List Gmail labels."""
        return await client.request(owner, "GET", "labels")

    @tool
    async def gmail_create_label(name: str):
        """Create a Gmail label."""
        return await client.request(owner, "POST", "labels", json={"name": name})

    @tool
    async def gmail_modify_labels(
        resource: str, resource_type: str, add: list[str], remove: list[str]
    ):
        """Add or remove labels on a message or thread."""
        if resource_type not in {"messages", "threads"}:
            raise ValueError("Use messages or threads as the resource type.")
        if set(add + remove) & {"SPAM", "TRASH"}:
            raise PermissionError("Spam and Trash label changes are unavailable.")
        # Label writes must obey the same Spam and Trash boundary as reads.
        if resource_type == "messages":
            await get_message(resource)
        else:
            thread = await client.request(owner, "GET", "threads/" + resource_id(resource))
            if any(
                set(message.get("labelIds", [])) & {"SPAM", "TRASH"}
                for message in thread.get("messages", [])
            ):
                raise PermissionError(
                    "Threads containing Spam or Trash messages are unavailable for label changes."
                )
        return await client.request(
            owner,
            "POST",
            f"{resource_type}/{resource_id(resource)}/modify",
            json={"addLabelIds": add, "removeLabelIds": remove},
        )

    return [
        gmail_connect,
        gmail_disconnect,
        gmail_search_messages,
        gmail_get_message,
        gmail_get_thread,
        gmail_download_attachment,
        gmail_list_drafts,
        gmail_get_draft,
        gmail_create_draft,
        gmail_send_draft,
        gmail_list_labels,
        gmail_create_label,
        gmail_modify_labels,
    ]
