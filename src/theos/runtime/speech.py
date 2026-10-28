"""Write expressive spoken text before every synthesis request."""

import asyncio
import json
import re
from collections import Counter

from harness import ModelRequest, SystemMessage, UserMessage
from theos.prompts import render
from theos.services.errors import ServiceError

from .model_catalog import generation_options, reasoning_choices
from .models import model_options
from .text import reply_text
from .usage import message_model

SPEECH_WRITING = render("speech/rewrite.md")
_numbers = re.compile(r"\d+(?:[.,:/-]\d+)*(?:%|\b)")


async def prepare(runtime, owner, text, *, session_id=None):
    """Use one tool-free model request and account for its owner and conversation."""
    session = (
        runtime.session(owner, session_id)
        if session_id
        else {"owner": owner, "id": "speech", "model": runtime.settings.model}
    )
    choices = reasoning_choices(runtime.settings.provider, session["model"])
    effort = "none" if "none" in choices else "low" if "low" in choices else "default"
    options = model_options(runtime.settings.provider, effort)
    options.update(
        generation_options(
            runtime.settings.provider,
            session["model"],
            {"max_output_tokens": min(8192, runtime.settings.max_output_tokens)},
        )
    )
    request = ModelRequest(
        messages=[
            SystemMessage(render("speech/system.md")),
            UserMessage(json.dumps({"source_text": text}, ensure_ascii=False)),
        ],
        options=options,
    )
    try:
        with runtime.tracing.span("prepare expressive speech"):
            async with asyncio.timeout(30):
                async with runtime.models(runtime.settings, session["model"], effort) as model:
                    response = await model.generate(request)
        if response.usage:
            runtime.record_usage(session, response.usage, model_id=message_model(response))
        spoken = reply_text(response.text or "").strip()
        if (
            not spoken
            or len(spoken) > 12000
            or response.tool_calls
            or response.stop_reason in {"length", "max_tokens", "max_output_tokens", "incomplete"}
            or Counter(_numbers.findall(spoken)) != Counter(_numbers.findall(text))
        ):
            raise ValueError("Invalid spoken rendition.")
        return spoken
    except Exception as error:
        # Never silently substitute the plain source after a failed performance-writing step.
        raise ServiceError("Expressive speech preparation failed. Please try again.") from error
