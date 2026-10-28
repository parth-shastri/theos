"""Research-only tools for saved notes, source reading, and evidence retrieval."""

import json
import time
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from harness import tool
from theos.prompts import render
from theos.services.errors import ServiceError
from theos.services.http import request_json

RESEARCH_INSTRUCTIONS = render("capabilities/research.md", allow_delegation=True)


def research_tools(runtime, session, run_id):
    """Bind all reads and writes to the authorized account and conversation."""
    owner, session_id = session["owner"], session["id"]
    store = runtime.research

    @tool
    async def save_research_note(
        kind: Literal["finding", "question", "plan"],
        text: str,
        source_ids: list[str] | None = None,
        status: Literal["unverified", "supported", "disputed", "open", "resolved"] = "unverified",
        replaces: str | None = None,
    ):
        """Save a finding, plan, or question. Cite saved source IDs. Replace a previous note by reference while retaining its original record."""
        if not text.strip():
            raise ValueError("Enter a research note.")
        source_ids = source_ids or []
        root = store.family(owner, session_id, run_id)
        for reference in source_ids:
            item = store.scratchpad_item(owner, session_id, reference)
            if item["kind"] != "source" or store.family(owner, session_id, item["run"]) != root:
                raise ValueError("Use source references from this research run.")
        if kind == "finding" and status in {"supported", "disputed"} and not source_ids:
            raise ValueError("Attach saved sources or mark the finding unverified.")
        if replaces:
            old = store.scratchpad_item(owner, session_id, replaces)
            if old["kind"] != kind or old["run"] != run_id:
                raise ValueError("Replace only your own note of the same kind.")
        item_id = store.save_scratchpad(
            owner,
            session_id,
            run_id,
            kind,
            {
                "text": text,
                "source_ids": source_ids,
                "status": status,
                "replaces": replaces,
            },
        )
        return {"id": item_id, "saved": True}

    @tool
    async def read_research(run: str | None = None, item_id: str | None = None):
        """Reopen a saved research run or item in this conversation. Source items contain complete retrieved text. Answers are returned in full."""
        if item_id:
            return store.scratchpad_item(owner, session_id, item_id)
        selected = run or run_id
        row = store.get(owner, session_id, selected)
        return {
            "id": row["id"],
            "task": row["task"],
            "status": row["status"],
            "answer": row["answer"],
            "scratchpad": store.scratchpad(owner, session_id, selected, family=True),
        }

    @tool
    async def list_research():
        """List saved research runs in this conversation. Use read_research to reopen one."""
        return store.runs(owner, session_id)

    @tool
    async def read_source(url: str):
        """Read the full extracted text of a public source through Exa and save it. No excerpt length is requested. Requires the Exa integration."""
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        try:
            private = not ip_address(host).is_global
        except ValueError:
            private = (
                host == "localhost"
                or host.endswith((".localhost", ".local", ".internal"))
                or "." not in host
            )
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or private
        ):
            raise ValueError("Use a public HTTP or HTTPS source URL.")
        key = runtime.settings.exa_key.get_secret_value()
        if not key:
            raise ServiceError("Configure an Exa API key to read full source pages.")
        # A fixed extraction endpoint keeps source URLs away from the server's private network.
        data = await request_json(
            runtime.http,
            "POST",
            "https://api.exa.ai/contents",
            headers={"x-api-key": key},
            json={"urls": [url], "text": True},
        )
        results = data.get("results", [])
        if not results or not results[0].get("text"):
            raise ServiceError("The source could not be read. Keep it marked unverified.")
        source = {**results[0], "retrieved_at": time.time()}
        reference = store.save_scratchpad(owner, session_id, run_id, "source", source)
        return {"source_id": reference, **source}

    return [save_research_note, read_research, list_research, read_source]


def capture_search(runtime, session, run_id, result):
    """Keep the exact search payload and attach stable references to its sources."""
    from harness import ToolResultMessage

    if result.name != "web_search" or result.status != "completed":
        return result
    try:
        payload = json.loads(result.content)
        rows = payload.get("results") or payload.get("web", {}).get("results", [])
        references = [
            runtime.research.save_scratchpad(session["owner"], session["id"], run_id, "source", row)
            for row in rows
        ]
        # Retain the complete search payload. Added IDs help notes refer to saved evidence.
        return ToolResultMessage(
            result.call_id,
            result.name,
            json.dumps(
                {
                    "search_result": payload,
                    "source_ids": references,
                },
                ensure_ascii=False,
            ),
            result.status,
        )
    except (ValueError, AttributeError, TypeError):
        return result
