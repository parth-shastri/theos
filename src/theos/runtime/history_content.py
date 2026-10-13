"""Render saved MIME evidence as text without changing connector responses."""

import base64
import binascii
import json
from html.parser import HTMLParser


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
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


def evidence_text(content):
    """Decode text MIME parts. Keep references and identify unread attachments."""
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return content
    if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
        return content
    payload = data["payload"]
    parts = [f"Message ID: {data.get('id', '')}"]
    if data.get("threadId"):
        parts.append(f"Thread ID: {data['threadId']}")
    for header in payload.get("headers", []):
        if header.get("name", "").lower() in {"subject", "from", "to", "date"}:
            parts.append(f"{header['name']}: {header.get('value', '')}")

    def visit(part, path):
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        encoded = body.get("data")
        if encoded and mime in {"text/plain", "text/html"}:
            try:
                text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode(
                    "utf-8", errors="replace"
                )
                if mime == "text/html":
                    parser = _HTMLText()
                    parser.feed(text)
                    text = "\n".join(
                        line
                        for row in "".join(parser.parts).splitlines()
                        if (line := " ".join(row.split()))
                    )
                parts.append(f"Text part {path} ({mime}):\n{text}")
            except (ValueError, binascii.Error):
                parts.append(f"Text part {path} could not be decoded. Read the raw view.")
        elif body.get("attachmentId") or encoded:
            parts.append(
                f"Unread attachment at {path}: {part.get('filename', '')} ({mime}), attachment_id={body.get('attachmentId', '')}. Attachment contents are not included."
            )
        children = list(enumerate(part.get("parts", [])))
        if mime == "multipart/alternative":
            # MIME alternatives represent the same body. Prefer readable plain text to duplicate HTML.
            plain = [
                (i, child)
                for i, child in children
                if child.get("mimeType") == "text/plain" and child.get("body", {}).get("data")
            ]
            if plain:
                children = plain
        for index, child in children:
            visit(child, f"{path}/parts/{index}")

    visit(payload, "/payload")
    return "\n\n".join(parts)
