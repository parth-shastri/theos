"""Return compact Gmail metadata and selected message text."""

from html.parser import HTMLParser

from .client import decode_raw

HEADERS = ("from", "to", "cc", "date", "subject")
MESSAGE_LABELS = {"INBOX", "UNREAD", "STARRED", "IMPORTANT"}


class _HTMLText(HTMLParser):
    """Collect visible HTML text and skip script and style contents."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "tr", "td", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "tr", "td", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def message_summary(message, *, message_id=None):
    """Keep the fields that help select a message; discard provider internals."""
    headers = {
        header.get("name", "").lower(): header.get("value", "")
        for header in (message.get("payload") or {}).get("headers", [])
    }
    result = {
        "id": message.get("id") or message_id,
        "thread_id": message.get("threadId"),
        "snippet": (message.get("snippet") or "")[:400],
        "labels": sorted(MESSAGE_LABELS.intersection(message.get("labelIds", []))),
    }
    result.update({name: headers[name][:500] for name in HEADERS if headers.get(name)})
    return {key: value for key, value in result.items() if value not in (None, "", [])}


def message_detail(
    message, *, body_offset=0, body_limit=4000, include_body=True, include_quoted=False
):
    """Return a bounded body and attachment descriptions, never MIME payloads."""
    plain, html, attachments = [], [], []

    def visit(part):
        mime_type = part.get("mimeType", "")
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        disposition = next(
            (
                header.get("value", "").lower()
                for header in part.get("headers", [])
                if header.get("name", "").lower() == "content-disposition"
            ),
            "",
        )
        is_attachment = bool(filename or "attachment" in disposition) or (
            bool(attachment_id) and mime_type.startswith("application/")
        )
        if is_attachment:
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "filename": filename or "attachment",
                    "mime_type": mime_type,
                    "size": body.get("size"),
                }
            )
            return

        if mime_type.startswith("multipart/"):
            for child in part.get("parts", []):
                visit(child)
            return

        encoded = body.get("data")
        if encoded and mime_type in {"text/plain", "text/html"}:
            value = decode_raw(encoded).decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                plain.append(value)
            else:
                parser = _HTMLText()
                parser.feed(value)
                html.append(
                    "\n".join(
                        line
                        for row in "".join(parser.parts).splitlines()
                        if (line := " ".join(row.split()))
                    )
                )

    visit(message.get("payload") or {})
    body = "\n\n".join(plain or html)
    if not include_quoted:
        body = _without_quoted_replies(body)
    end = body_offset + body_limit
    result = {
        **message_summary(message),
        "body": body[body_offset:end] if include_body else "",
        "body_chars": len(body),
        "body_offset": body_offset,
        "next_body_offset": end if include_body and end < len(body) else None,
        "attachments": attachments,
    }
    return result


def _without_quoted_replies(body):
    """Drop common quoted-reply blocks from the default email preview."""
    lines = []
    for line in body.splitlines():
        normalized = line.strip().lower()
        if normalized == "-----original message-----" or (
            normalized.startswith("on ") and normalized.endswith(" wrote:")
        ):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines).strip()
