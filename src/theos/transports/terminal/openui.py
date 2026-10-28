"""Replace browser-only OpenUI source with readable terminal history text."""

from harness import AssistantMessage, UserMessage
from theos.storage.messages import display_metadata


def terminal_history(messages):
    """Show the saved summary or a browser notice without exposing OpenUI source."""
    visible = []
    for message in messages:
        if isinstance(message, UserMessage):
            user_text = display_metadata(message).get("user_text")
            if isinstance(user_text, str):
                message.content = user_text
            visible.append(message)
            continue
        if not isinstance(message, AssistantMessage):
            visible.append(message)
            continue
        display = display_metadata(message)
        if display.get("openui_hidden"):
            continue
        if display.get("format") != "openui-lang":
            visible.append(message)
            continue
        summary = display.get("openui_summary")
        message.text = (
            summary.strip()
            if isinstance(summary, str) and summary.strip()
            else "This answer uses an interactive interface. Open this conversation in the browser to view it."
        )
        visible.append(message)
    return visible
