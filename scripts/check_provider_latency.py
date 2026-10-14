"""Compare provider routing with synthetic context and tools that never execute."""

import argparse
import asyncio
import json
import time

import httpx
from openai import AsyncOpenAI

from harness import SystemMessage, UserMessage
from harness.types import ModelRequest, ToolSpec
from theos.operations.provider_diagnostics import request_hook, response_hook
from theos.operations.tracing import Tracing
from theos.runtime.models import model_options
from theos.runtime.openrouter import OpenRouterChatModel
from theos.settings import Settings


async def check(args):
    settings = Settings(_env_file=args.env)
    if settings.provider != "openrouter":
        raise ValueError("This probe requires the configured OpenRouter provider.")
    profiles = ["baseline", "responsive"] if args.profile == "both" else [args.profile]
    selected = {317, 731}
    records = "\n".join(
        f"record-{i:05d}|sender=synthetic-{i:05d}@example.invalid|"
        f"kind={'review' if i in selected else 'newsletter'}|"
        f"amount={i % 1000}|currency=INR|date=2026-10-14|"
        "subject=Synthetic account notice; no real account or external action."
        for i in range(args.rows)
    )
    expected = [f"record-{i:05d}" for i in sorted(selected)]
    spec = ToolSpec(
        "inspect_records",
        "Return synthetic record IDs for inspection. This tool will never execute.",
        {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["ids"],
            "additionalProperties": False,
        },
    )
    tracing = Tracing(
        settings.tracing.model_copy(
            update={
                "enabled": True,
                "service_name": "theos-provider-latency-probe",
                "capture_content": False,
            }
        )
    )
    try:
        for profile in profiles:
            provider = {"zdr": True}
            if profile == "azure-base":
                provider.update(
                    {
                        "only": ["azure"],
                        "ignore": ["azure/eu", "azure/us"],
                        "allow_fallbacks": False,
                    }
                )
            if profile == "responsive":
                provider.update(
                    {
                        "order": ["azure/eu"],
                        "sort": "latency",
                        "preferred_max_latency": {"p90": 15},
                        "preferred_min_throughput": {"p90": 10},
                    }
                )
            options = model_options("openrouter", args.reasoning)
            options.setdefault("extra_body", {})["provider"] = provider
            options.update(max_tokens=8192, tool_choice="inspect_records")
            request = ModelRequest(
                [
                    SystemMessage(
                        "Inspect inert synthetic records. Select every record with kind=review. "
                        "Call inspect_records once with their sorted IDs. Do not perform actions."
                    ),
                    UserMessage(records),
                ],
                tools=[spec],
                options=options,
            )
            result = {"profile": profile, "reasoning": args.reasoning, "rows": args.rows}
            started = time.perf_counter()
            try:
                async with asyncio.timeout(args.timeout):
                    async with AsyncOpenAI(
                        api_key=settings.api_key.get_secret_value(),
                        base_url="https://openrouter.ai/api/v1",
                        max_retries=0,
                        http_client=httpx.AsyncClient(
                            timeout=httpx.Timeout(60, connect=10),
                            event_hooks={"request": [request_hook], "response": [response_hook]},
                        ),
                    ) as client:
                        model = tracing.model(
                            OpenRouterChatModel(client, "openai/gpt-6-luna", api="chat_completions")
                        )
                        reply = await model.generate(request)
                        result.update(
                            usage=reply.usage,
                            correct=(
                                len(reply.tool_calls) == 1
                                and reply.tool_calls[0].name == spec.name
                                and reply.tool_calls[0].arguments == {"ids": expected}
                            ),
                            tool_executions=0,
                        )
            except Exception as error:
                result["error_type"] = type(error).__name__
            result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            print(json.dumps(result), flush=True)
    finally:
        await tracing.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=None)
    parser.add_argument(
        "--profile", choices=["baseline", "responsive", "azure-base", "both"], default="both"
    )
    parser.add_argument(
        "--reasoning", choices=["default", "none", "low", "medium"], default="medium"
    )
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not 732 <= args.rows <= 2000 or not 0 < args.timeout <= 120:
        parser.error("Use 732–2000 rows and a timeout of at most 120 seconds.")
    asyncio.run(check(args))


if __name__ == "__main__":
    main()
