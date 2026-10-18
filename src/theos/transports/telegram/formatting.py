"""Convert Markdown to Telegram text/entities and split it within Telegram's limits."""

import json
import shlex
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from theos.runtime.reviews import tool_icon, tool_label
from theos.runtime.text import reply_text

_markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
_styles = {"strong": "bold", "em": "italic", "s": "strikethrough"}


def utf16_length(text):
    """Telegram measures entity offsets in UTF-16 code units."""
    # Python counts Unicode code points, but Telegram counts UTF-16 units. Emoji can take
    # two units, so ordinary len(text) would place bold/link offsets incorrectly.
    return len(text.encode("utf-16-le")) // 2


def safe_url(url):
    """Keep executable and malformed URLs out of generated link entities."""
    # Markdown is model-generated. Allow only link types Telegram users can safely open.
    if not url or any(ord(char) < 32 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme in {"https", "http"}:
            return bool(parsed.hostname)
        return scheme in {"mailto", "tg"} and bool(parsed.netloc or parsed.path)
    except ValueError:
        return False


class _Text:
    # Collect visible text and formatting spans together so entity offsets always match
    # the exact text sent to Telegram.
    def __init__(self):
        self.text = ""
        self.entities = []
        self.offset = 0

    def append(self, value):
        value = reply_text(value)
        self.text += value
        self.offset += utf16_length(value)

    def newline(self, count=1):
        if self.text:
            missing = count - (len(self.text) - len(self.text.rstrip("\n")))
            self.append("\n" * max(0, missing))

    def entity(self, kind, start, **attributes):
        if self.offset > start:
            self.entities.append(
                {"type": kind, "offset": start, "length": self.offset - start, **attributes}
            )

    def inline(self, tokens):
        # Markdown-It gives nested open/close tokens. Remember their starting offsets,
        # then create Telegram entities when the matching close token arrives.
        opened = []
        for token in tokens:
            kind = token.type
            if kind in {"text", "html_inline"}:
                self.append(token.content)
            elif kind in {"softbreak", "hardbreak"}:
                self.append("\n")
            elif kind == "code_inline":
                start = self.offset
                self.append(token.content)
                self.entity("code", start)
            elif kind.endswith("_open"):
                style = _styles.get(kind.removesuffix("_open"))
                attributes = {}
                if kind == "link_open" and safe_url(token.attrGet("href")):
                    style = "text_link"
                    attributes["url"] = token.attrGet("href")
                opened.append((style, self.offset, attributes))
            elif kind.endswith("_close") and opened:
                style, start, attributes = opened.pop()
                if style:
                    self.entity(style, start, **attributes)
            elif kind == "image":
                start = self.offset
                self.append(token.content or "Image")
                url = token.attrGet("src")
                if safe_url(url):
                    self.entity("text_link", start, url=url)


def _entities_without_code_overlap(entities):
    # Telegram does not allow code/pre entities inside links or text styles.
    # Split a conflicting style span around code rather than dropping the whole style.
    code = [e for e in entities if e["type"] in {"code", "pre"}]
    result = []
    for entity in entities:
        spans = [(entity["offset"], entity["offset"] + entity["length"])]
        if entity["type"] not in {"code", "pre"}:
            for literal in code:
                left = literal["offset"]
                right = left + literal["length"]
                spans = [
                    piece
                    for start, end in spans
                    for piece in [(start, min(end, left)), (max(start, right), end)]
                    if piece[1] > piece[0]
                ]
        result.extend({**entity, "offset": start, "length": end - start} for start, end in spans)
    return sorted(result, key=lambda e: (e["offset"], -e["length"]))


def _chunks(text, entities, limit):
    # Chunk by Telegram's UTF-16 limit and clip/rebase any entity that crosses a message
    # boundary. Reusing character indexes here would break non-BMP characters like emoji.
    start, units, absolute = 0, 0, 0
    boundaries = []
    for index, char in enumerate(text):
        size = utf16_length(char)
        if units + size > limit:
            boundaries.append((start, index, absolute - units, absolute))
            start, units = index, 0
        units += size
        absolute += size
    boundaries.append((start, len(text), absolute - units, absolute))
    messages = []
    for start, end, left, right in boundaries:
        clipped = []
        for entity in entities:
            offset = max(left, entity["offset"])
            stop = min(right, entity["offset"] + entity["length"])
            if stop > offset:
                clipped.append({**entity, "offset": offset - left, "length": stop - offset})
        messages.append({"text": text[start:end] or "…", "entities": clipped})
    return messages


def format_reply(source, limit=3900):
    """Render complete or partial Markdown and split without cutting emoji or entities."""
    # Reparse the whole current reply on every stream edit. This handles incomplete Markdown
    # while tokens are still arriving and yields consistent final formatting.
    if limit < 2:
        raise ValueError("The message limit must fit a UTF-16 surrogate pair.")
    output = _Text()
    lists = []
    heading = None
    cell = 0
    for token in _markdown.parse(reply_text(source)):
        kind = token.type
        if kind == "inline":
            output.inline(token.children or [])
        elif kind in {"fence", "code_block"}:
            # Telegram's pre entity represents fenced code; preserve a language hint when set.
            output.newline(2)
            start = output.offset
            output.append(token.content.rstrip("\n"))
            language = token.info.strip().split()[0] if token.info.strip() else ""
            output.entity("pre", start, **({"language": language} if language else {}))
            output.newline(2)
        elif kind == "heading_open":
            output.newline(2)
            heading = output.offset
        elif kind == "heading_close":
            output.entity("bold", heading)
            output.newline(2)
        elif kind == "paragraph_close":
            output.newline(1 if lists else 2)
        elif kind in {"bullet_list_open", "ordered_list_open"}:
            # Telegram does not render Markdown lists itself, so add visible list markers.
            output.newline()
            lists.append([kind, int(token.attrGet("start") or 1)])
        elif kind == "list_item_open":
            output.newline()
            style, number = lists[-1]
            output.append("  " * (len(lists) - 1))
            output.append(f"{number}. " if style == "ordered_list_open" else "• ")
            lists[-1][1] += 1
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
            output.newline(1 if lists else 2)
        elif kind == "tr_open":
            # Telegram has no table entity. Render each row as text with pipe separators.
            output.newline()
            cell = 0
        elif kind in {"th_open", "td_open"}:
            if cell:
                output.append(" | ")
            cell += 1
        elif kind in {"tr_close", "blockquote_close"}:
            output.newline()
        elif kind in {"table_close", "hr"}:
            output.newline(2)
    text = output.text.rstrip("\n")
    entities = _entities_without_code_overlap(output.entities)
    return _chunks(text, entities, limit)


def plain_messages(text):
    """Split literal command and review text using the same Unicode limit."""
    # Commands and approval copy are literal; do not parse user-controlled text as Markdown.
    return _chunks(reply_text(text), [], 3900)


def format_tool_activity(name, arguments, status, action="Calling"):
    """Render sandbox commands clearly and other exact arguments as temporary progress."""
    try:
        payload = json.loads(arguments)
    except (TypeError, ValueError):
        payload = {}
    language, literal = None, None
    if name == "run_command" and isinstance(payload.get("command"), str):
        language, literal = "bash", payload["command"]
    elif name == "execute_code" and isinstance(payload.get("code"), str):
        language, literal = "python", payload["code"]
    elif name == "browser" and isinstance(payload.get("arguments"), list):
        args = payload["arguments"]
        if all(isinstance(argument, str) for argument in args):
            language, literal = "bash", shlex.join(["agent-browser", *args])

    if literal is not None:
        heading = f"{tool_icon(name)} {action} {tool_label(name)}:"
        prefix = heading + "\n\n"
        text = prefix + literal + "\n\n" + status
        entities = [{"type": "bold", "offset": 0, "length": utf16_length(heading)}]
        if literal:
            entities.append(
                {
                    "type": "pre",
                    "offset": utf16_length(prefix),
                    "length": utf16_length(literal),
                    "language": language,
                }
            )
        return _chunks(text, entities, 3900)

    # Keep arguments in a code entity so punctuation and values remain exact and readable.
    heading = f"{tool_icon(name)} {action} {tool_label(name)} with args:"
    prefix = heading + "\n\n"
    text = prefix + arguments + "\n\n" + status
    entities = [
        {"type": "bold", "offset": 0, "length": utf16_length(heading)},
        {
            "type": "pre",
            "offset": utf16_length(prefix),
            "length": utf16_length(arguments),
            "language": "json",
        },
    ]
    return _chunks(text, entities, 3900)


def format_approval(tool, fields):
    """Render labels and prose while preserving commands as literal code."""
    # Put user-facing review fields first and technical details after them; the full original
    # arguments remain available for checking the approval against the action that will run.
    title = tool_icon(tool) + " Approval needed"
    text = title + "\n" + tool_label(tool) + "\n\n"
    entities = [{"type": "bold", "offset": 0, "length": utf16_length(title)}]
    primary = [field for field in fields if not field.get("technical")]
    technical = [field for field in fields if field.get("technical")]
    group, technical_start = None, None
    for field in [*primary, *technical]:
        if field.get("technical") and technical_start is None:
            text += "Exact request details (expand to inspect)\n"
            technical_start = utf16_length(text)
            group = None
        if field.get("group") and field["group"] != group:
            group = field["group"]
            entities.append(
                {"type": "bold", "offset": utf16_length(text), "length": utf16_length(group)}
            )
            text += group + "\n"
        if (
            not field.get("technical")
            and field.get("group", "").startswith("Cart item ")
            and field["label"] in {"Product", "Product / Label", "Label / Product"}
        ):
            entities.append(
                {
                    "type": "bold",
                    "offset": utf16_length(text),
                    "length": utf16_length(field["text"]),
                }
            )
            text += field["text"] + "\n"
            continue
        entities.append(
            {"type": "bold", "offset": utf16_length(text), "length": utf16_length(field["label"])}
        )
        inline = field["kind"] == "text" and "\n" not in field["text"] and len(field["text"]) <= 160
        text += field["label"] + (": " if inline else "\n")
        offset = utf16_length(text)
        if field["kind"] == "markdown":
            for part in format_reply(field["text"]):
                entities.extend({**e, "offset": e["offset"] + offset} for e in part["entities"])
                text += part["text"]
                offset += utf16_length(part["text"])
        else:
            text += field["text"]
            if field["kind"] == "code":
                entities.append(
                    {"type": "pre", "offset": offset, "length": utf16_length(field["text"])}
                )
        text += "\n" if inline else "\n\n"
        if field.get("hint"):
            entities.append(
                {
                    "type": "italic",
                    "offset": utf16_length(text),
                    "length": utf16_length(field["hint"]),
                }
            )
            text += field["hint"] + "\n"
    if technical_start is not None:
        entities.append(
            {
                "type": "expandable_blockquote",
                "offset": technical_start,
                "length": utf16_length(text.rstrip("\n")) - technical_start,
            }
        )
    return _chunks(text.rstrip("\n"), entities, 3900)
