"""Render assistant Markdown as Telegram text and explicit message entities."""

from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from theos.runtime.text import reply_text

_markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
_styles = {"strong": "bold", "em": "italic", "s": "strikethrough"}


def utf16_length(text):
    """Telegram measures entity offsets in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def safe_url(url):
    """Keep executable and malformed URLs out of generated link entities."""
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
    return _chunks(reply_text(text), [], 3900)
