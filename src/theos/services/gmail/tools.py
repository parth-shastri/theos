"""Gmail tools bound to one owner and current draft approval."""

import asyncio
import base64
import json
from email.message import EmailMessage
from typing import Annotated

from pydantic import Field

from harness import tool
from harness.events import _tool_scope
from theos.services.result_files import for_model

from .client import decode_raw, resource_id
from .content import message_detail, message_summary


def gmail_tools(client, owner, *, result_stager=None):
    """Build account tools bound to one authenticated private owner."""

    # Only filtered, normalized dictionaries below reach the shared staging helper.

    @tool
    async def gmail_connect():
        """Create a Google authorization link for your Gmail account."""
        return {"url": client.oauth.start(owner, "gmail")}

    @tool
    async def gmail_disconnect():
        """Disconnect your Gmail account and revoke its grant."""
        return await client.oauth.disconnect(owner, "gmail")

    @tool(parallel_safe=True)
    async def gmail_search_messages(
        query: str,
        page_token: str | None = None,
        max_results: Annotated[int, Field(ge=1, le=25)] = 10,
    ):
        """Return headers and short snippets; pass next_page_token to continue and open a selected ID for its body."""
        params = {"q": f"({query}) -in:spam -in:trash", "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        result = await client.request(owner, "GET", "messages", params=params)
        headers = ["From", "To", "Cc", "Date", "Subject"]

        async def message_metadata(item):
            message = await client.request(
                owner,
                "GET",
                "messages/" + resource_id(item["id"]),
                params={"format": "metadata", "metadataHeaders": headers},
            )
            return message_summary(message, message_id=item["id"])

        messages = await asyncio.gather(
            *(message_metadata(item) for item in result.get("messages", []) if item.get("id"))
        )
        total_results = result.get("resultSizeEstimate", len(messages))
        return await for_model(
            {
                "messages": messages,
                "next_page_token": result.get("nextPageToken"),
                "total_results": total_results,
            },
            tool_name="gmail_search_messages",
            summary=f"Returned {len(messages)} message headers; Gmail estimates {total_results} matches.",
            save_result=result_stager,
        )

    async def get_message(message_id):
        message = await client.request(
            owner, "GET", "messages/" + resource_id(message_id), params={"format": "full"}
        )
        if set(message.get("labelIds", [])) & {"SPAM", "TRASH"}:
            raise PermissionError("Messages in Spam or Trash are unavailable.")
        return message

    @tool(parallel_safe=True)
    async def gmail_get_message(
        message_id: str,
        body_offset: Annotated[int, Field(ge=0)] = 0,
        body_limit: Annotated[int, Field(ge=1, le=12000)] = 4000,
        include_body: bool = True,
        include_quoted: bool = False,
    ):
        """Read a bounded body range; set include_quoted to include replies and use the returned offset to continue."""
        message = await get_message(message_id)
        detail = message_detail(
            message,
            body_offset=body_offset,
            body_limit=body_limit,
            include_body=include_body,
            include_quoted=include_quoted,
        )
        return await for_model(
            detail,
            tool_name="gmail_get_message",
            summary=(
                f"Message {detail.get('id')}: {detail.get('body_chars', 0)} body characters, "
                f"{len(detail.get('attachments', []))} attachments."
            ),
            save_result=result_stager,
        )

    @tool(parallel_safe=True)
    async def gmail_get_thread(
        thread_id: str,
        message_limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ):
        """List recent message headers in a thread; use gmail_get_message for selected content."""
        thread = await client.request(
            owner,
            "GET",
            "threads/" + resource_id(thread_id),
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "To", "Cc", "Date", "Subject"],
            },
        )
        visible = [
            message
            for message in thread.get("messages", [])
            if not set(message.get("labelIds", [])) & {"SPAM", "TRASH"}
        ]
        selected = visible[-message_limit:]
        return await for_model(
            {
                "thread_id": thread_id,
                "message_count": len(visible),
                "omitted_older_messages": len(visible) - len(selected),
                "messages": [message_summary(message) for message in selected],
            },
            tool_name="gmail_get_thread",
            summary=f"Thread {thread_id}: returned {len(selected)} of {len(visible)} message headers.",
            save_result=result_stager,
        )

    @tool
    async def gmail_download_attachment(message_id: str, attachment_id: str):
        """Download one selected attachment by ID; pass its file_id to upload_file for workspace analysis."""
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
        return {
            "file_id": row["id"],
            "name": row["name"],
            "media_type": row["media_type"],
            "size": row["size"],
        }

    @tool(parallel_safe=True)
    async def gmail_list_drafts(
        page_token: str | None = None,
        max_results: Annotated[int, Field(ge=1, le=25)] = 10,
    ):
        """List draft IDs without loading their bodies; inspect a selected draft with gmail_get_draft."""
        result = await client.request(
            owner,
            "GET",
            "drafts",
            params={
                "maxResults": max_results,
                **({"pageToken": page_token} if page_token else {}),
            },
        )
        return {
            "drafts": [
                {"draft_id": item.get("id"), "message_id": item.get("message", {}).get("id")}
                for item in result.get("drafts", [])
            ],
            "next_page_token": result.get("nextPageToken"),
        }

    @tool(parallel_safe=True)
    async def gmail_get_draft(
        draft_id: str,
        body_offset: Annotated[int, Field(ge=0)] = 0,
        body_limit: Annotated[int, Field(ge=1, le=12000)] = 4000,
    ):
        """Read selected draft details and a bounded body range before deciding to send."""
        result = await client.preview(owner, draft_id)
        body = result.pop("body", "")
        body_chars = len(body)
        end = body_offset + body_limit
        return await for_model(
            {
                **result,
                "body": body[body_offset:end],
                "body_chars": body_chars,
                "body_offset": body_offset,
                "next_body_offset": end if end < body_chars else None,
            },
            tool_name="gmail_get_draft",
            summary=f"Draft {draft_id}: {body_chars} body characters; returned range {body_offset}-{min(end, body_chars)}.",
            save_result=result_stager,
        )

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
        """List Gmail label IDs, names, and types."""
        result = await client.request(owner, "GET", "labels")
        return {
            "labels": [
                {key: label[key] for key in ("id", "name", "type") if key in label}
                for label in result.get("labels", [])
            ]
        }

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
