"""Replay saved evidence with a live model and local, read-only history tools.

The session export and instructions can contain private data. Outputs use mode 0600.
No connector, transport, or production database participates in this replay.
"""

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from harness import (
    Agent,
    AssistantMessage,
    CompactionConfig,
    ContextMemory,
    Hooks,
    ToolResultMessage,
)
from harness.context_size import ContextOverflowError, request_size
from harness.events import GenerationComplete
from harness.output import requested_output_tokens
from harness.types import message_from_dict, message_to_dict
from theos.runtime.budgets import TurnBudget
from theos.runtime.context import SUMMARY_PROMPT
from theos.runtime.errors import CheckedModel
from theos.runtime.history_tools import history_tools
from theos.runtime.models import model_client, session_options
from theos.settings import Settings


def credentials(host):
    """Read provider credentials into memory without printing or saving them."""
    if not host:
        return Settings()
    code = (
        "from theos.settings import Settings; import json; s=Settings(); "
        "print(json.dumps(dict(provider=s.provider,api_key=s.api_key.get_secret_value(),"
        "model_base_url=s.model_base_url)))"
    )
    command = shlex.join(["docker", "exec", "theos-theos-1", "/app/.venv/bin/python", "-c", code])
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        capture_output=True,
        text=True,
        check=True,
    )
    return Settings(_env_file=None, **json.loads(result.stdout))


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)


def visible_history_reads(request):
    """Record source indices, without recording private result content."""
    indices = []
    for message in request.messages:
        if not isinstance(message, ToolResultMessage) or message.name != "history_read":
            continue
        try:
            result = json.loads(message.content)
        except ValueError:
            continue  # Request previews can contain an explicit truncation marker.
        if isinstance(result, dict) and isinstance(result.get("message_index"), int):
            indices.append(result["message_index"])
    return indices


async def replay(args):
    saved = json.loads(args.session.read_text())
    messages = json.loads(saved["history"])
    # Remove only the failed final reply. Preserve the complete evidence before it.
    if messages and messages[-1].get("type") == "assistant" and not messages[-1].get("tool_calls"):
        messages.pop()
    history = [message_from_dict(message) for message in messages]
    original = [message_to_dict(message) for message in history]
    memory = ContextMemory.from_dict(json.loads(saved["memory"]))
    settings = Settings(_env_file=args.config) if args.config else credentials(args.ssh)
    # These values deliberately cannot fund the replay in bounded mode.
    settings.max_model_calls = 1
    settings.max_compaction_calls = 0
    budgets = TurnBudget(settings, enforce=False)
    requests, reads, injections = [], [], []
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)

    async def options(request, ctx):
        request.options.update(session_options(settings, saved))
        key = "max_tokens" if settings.provider == "openrouter" else "max_output_tokens"
        request.options.setdefault(key, args.output_tokens)
        return request

    async def after_tool(result, ctx):
        call = next(
            c
            for m in reversed(ctx.history)
            if isinstance(m, AssistantMessage)
            for c in m.tool_calls
            if c.id == result.call_id
        )
        reads.append({"name": call.name, "arguments": call.arguments, "status": result.status})
        write_private(args.output / "reads.json", json.dumps(reads, indent=2))
        return result

    class ReplayModel:
        def __init__(self, model):
            self.model = model

        def __getattr__(self, name):
            return getattr(self.model, name)

        async def stream(self, request):
            summary = (
                not request.tools
                and "You are a summarization agent creating a context checkpoint"
                in request.messages[0].content
            )
            record = {
                "summary": summary,
                "input_estimate": request_size(request),
                "output_reserved": requested_output_tokens(request),
                "usage": {},
                "visible_history_reads": visible_history_reads(request),
            }
            requests.append(record)
            if args.mode == "summary-failure" and summary:
                injections.append("unusable_summary")
                yield GenerationComplete(AssistantMessage("Unusable summary", stop_reason="length"))
                return
            if args.mode == "overflow" and not summary and injections.count("overflow") < 2:
                injections.append("overflow")
                raise ContextOverflowError()
            async for event in self.model.stream(request):
                if isinstance(event, GenerationComplete):
                    record["usage"] = event.message.usage
                yield event

    async with model_client(settings, saved["model"], saved["reasoning"]) as connected:
        agent = Agent(
            ReplayModel(CheckedModel(connected, settings.provider)),
            tools=history_tools(),
            instructions=args.instructions.read_text(),
            hooks=Hooks(before_model=options, after_tool=after_tool),
            context_window=args.window,
            compaction=CompactionConfig(
                SUMMARY_PROMPT,
                {
                    "max_tokens"
                    if settings.provider == "openrouter"
                    else "max_output_tokens": args.output_tokens
                },
                max_summary_tokens=None,
                resilient=True,
                retrieval_tools=("history_read", "history_search"),
                trigger_ratio=0.5,
                target_ratio=0.20,
            ),
        )
        # This deadline belongs to the manual test, not the Theos harness.
        async with asyncio.timeout(args.timeout):
            result = await agent.run(
                history,
                memory=memory,
                budget=budgets.research,
                compaction_budget=budgets.compaction,
            )
    answer = result.message.text if result.message else ""
    expected = json.loads(args.expectations.read_text()) if args.expectations else {}
    checks = {
        "completed": result.status == "completed",
        "not_fixed_fallback": bool(answer) and result.message.stop_reason != "context_fallback",
        "original_unchanged": original == [message_to_dict(m) for m in history[: len(original)]],
        "requests_fit": all(
            r["input_estimate"] + r["output_reserved"] <= args.window for r in requests
        ),
    }
    for pattern in expected.get("required_patterns", []):
        checks[f"answer_matches:{pattern}"] = bool(re.search(pattern, answer, re.IGNORECASE))
    for index in expected.get("required_reads", []):
        checks[f"read:{index}"] = any(
            r["name"] == "history_read"
            and r["arguments"].get("message_index") == index
            and r["status"] == "completed"
            for r in reads
        )
    report = {
        "mode": args.mode,
        "stop_reason": result.message.stop_reason if result.message else None,
        "provider": settings.provider,
        "model": saved["model"],
        "checks": checks,
        "requests": requests,
        "injections": injections,
        "history_tool_calls": len(reads),
        "budget_enforced": False,
        "logical_calls": budgets.total.used,
        "summary_calls": budgets.compaction.used,
    }
    write_private(args.output / "answer.md", answer)
    write_private(args.output / "result.json", json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "passed": all(checks.values()),
                "requests": len(requests),
                "history_tool_calls": len(reads),
                "failed_checks": [k for k, v in checks.items() if not v],
            }
        )
    )
    if not all(checks.values()):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--instructions", type=Path, required=True)
    parser.add_argument("--expectations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        help="Read a local provider configuration without printing credentials",
    )
    parser.add_argument("--ssh", help="Read existing provider credentials from this Pi host")
    parser.add_argument(
        "--mode", choices=("normal", "summary-failure", "overflow"), default="normal"
    )
    parser.add_argument("--window", type=int, default=100000)
    parser.add_argument("--output-tokens", type=int, default=8192)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    os.umask(0o077)
    asyncio.run(replay(args))


if __name__ == "__main__":
    main()
