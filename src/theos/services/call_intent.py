"""Understand natural call replies without letting generated text execute an action."""

import asyncio
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harness import ModelRequest, SystemMessage, UserMessage
from theos.prompts import render
from theos.runtime.model_catalog import generation_options, reasoning_choices
from theos.runtime.models import model_options
from theos.runtime.usage import message_model

from .errors import ServiceError


class CallIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["message", "approve", "decline", "end"]
    reply: str = Field(max_length=1600)
    authorization_quote: str = Field(max_length=4000)
    end_call: bool


async def classify(runtime, session, text, context, history):
    choices = reasoning_choices(runtime.settings.provider, session["model"])
    effort = "none" if "none" in choices else "low" if "low" in choices else "default"
    options = model_options(runtime.settings.provider, effort)
    options.update(
        generation_options(runtime.settings.provider, session["model"], {"max_output_tokens": 1024})
    )
    options["json_schema"] = CallIntent.model_json_schema()
    request = ModelRequest(
        messages=[
            SystemMessage(render("calls/intent.md")),
            UserMessage(
                json.dumps(
                    {"context": context, "conversation": history[-8:], "utterance": text},
                    ensure_ascii=False,
                )
            ),
        ],
        options=options,
    )
    try:
        async with asyncio.timeout(20):
            async with runtime.models(runtime.settings, session["model"], effort) as model:
                response = await model.generate(request)
        if response.usage:
            runtime.record_usage(session, response.usage, model_id=message_model(response))
        if response.tool_calls or response.stop_reason in {
            "length",
            "max_tokens",
            "max_output_tokens",
            "incomplete",
        }:
            raise ValueError("Incomplete call intent.")
        result = CallIntent.model_validate_json(response.text or "")
        if result.intent in {"approve", "decline"}:
            quote = result.authorization_quote.strip()
            if (
                not context.get("approval")
                or not context.get("review_read")
                or not quote
                or quote != text.strip()
            ):
                return CallIntent(
                    intent="message",
                    reply="Please tell me clearly whether you want this exact action approved or declined.",
                    authorization_quote="",
                    end_call=False,
                )
        return result
    except Exception as error:
        raise ServiceError(
            "I could not understand that reply. Could you say it another way?"
        ) from error
