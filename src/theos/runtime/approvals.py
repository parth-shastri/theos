"""Approval policy and content checks before a tool can execute."""

import json
import time
from uuid import uuid4

from harness import ALLOW, ASK, DENY, unanswered_calls


def requires_approval(name):
    """Share the approval rule with the browser tool catalog."""
    if name == "gmail_send_draft":
        return True
    if not name.startswith("zepto_"):
        return False
    words = set(name.removeprefix("zepto_").lower().split("_"))
    if words & {
        "payment",
        "payments",
        "pay",
        "upi",
        "wallet",
        "checkout",
        "purchase",
        "buy",
        "reorder",
    }:
        return True
    return (
        bool(
            (words & {"cart", "order"})
            and (
                words
                & {"confirm", "confirmation", "place", "submit", "finalize", "complete", "execute"}
            )
        )
        or name == "zepto_create_order"
    )


async def approval_preview(runtime, session, name, arguments):
    """Read current action contents for the approval screen."""
    if name == "gmail_send_draft":
        return await runtime.gmail.preview(session["owner"], arguments["draft_id"])
    return arguments


async def check_approval(runtime, session, tool, args, ctx):
    """Match a saved call to an unexpired decision and unchanged preview."""
    owner = session["owner"]
    session_id = session["id"]
    # 1. Match an unanswered call from history, not an ID supplied by the model.
    arguments = args.model_dump(mode="json")
    visited = ctx.state.setdefault("visited_calls", set())
    call = next(
        (
            candidate
            for candidate in unanswered_calls(ctx.history)
            if candidate.name == tool.name and candidate.id not in visited
        ),
        None,
    )
    if call is None:
        return DENY("The tool call has no conversation record.")
    visited.add(call.id)
    if runtime.db.one(
        "SELECT id FROM records WHERE owner=? AND kind='remote_recovery_review' AND id=?",
        (owner, session_id),
    ):
        return DENY(
            "Remote recovery requires operator review of external effects before tools can run."
        )
    if not requires_approval(tool.name):
        return ALLOW
    row = runtime.db.one(
        "SELECT * FROM approvals WHERE session=? AND call_id=?", (session_id, call.id)
    )
    # 2. Accept only the saved arguments and a current decision for this call.
    if row:
        if row["arguments"] != json.dumps(arguments, sort_keys=True):
            return DENY("The tool arguments changed after approval.")
        if row["expires"] <= time.time() or row["status"] in {"denied", "expired"}:
            runtime.db.execute(
                "UPDATE approvals SET status='expired' WHERE id=? AND status='pending'",
                (row["id"],),
            )
            return DENY("The approval expired or was denied.")
        if row["status"] == "approved":
            if tool.name == "gmail_send_draft":
                # Re-read Gmail because another client can edit a draft during approval.
                current = await runtime.approval_preview(session, tool.name, arguments)
                if current != json.loads(row["preview"]):
                    runtime.db.execute(
                        "UPDATE approvals SET status='changed' WHERE id=?", (row["id"],)
                    )
                    return DENY("The Gmail draft changed. Review it and request a new approval.")
            return ALLOW
        return ASK
    # 3. Save the review contents before asking the transport to show approval controls.
    preview = await runtime.approval_preview(session, tool.name, arguments)
    runtime.db.save_history(owner, session_id, ctx.history, ctx.memory.to_dict())
    runtime.db.execute(
        "INSERT INTO approvals(id,session,call_id,tool,arguments,preview,created,expires) VALUES (?,?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            session_id,
            call.id,
            tool.name,
            json.dumps(arguments, sort_keys=True),
            json.dumps(preview),
            time.time(),
            time.time() + 900,
        ),
    )
    return ASK
