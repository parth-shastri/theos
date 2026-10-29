"""Select bounded attention events without executing webhook content."""

import re

EVENTS = frozenset(
    {
        "issues",
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "workflow_run",
    }
)


def obj(value):
    return value if isinstance(value, dict) else {}


def positive_id(value):
    return value if type(value) is int and 0 < value < 2**63 else None


def clean(value, limit=160):
    return " ".join(str(value or "").split())[:limit]


def mention(body, login):
    return bool(
        isinstance(body, str)
        and re.search(r"(?<![\w@/])@" + re.escape(login) + r"(?![\w-])", body, re.I)
    )


def attention(event, payload, github_id, login):
    """Return one literal alert and a canonical GitHub link for this identity."""
    repo = obj(payload.get("repository"))
    name = repo.get("full_name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        return None
    action = payload.get("action")
    if event == "workflow_run":
        run = obj(payload.get("workflow_run"))
        actors = [obj(run.get("actor")), obj(run.get("triggering_actor"))]
        if (
            action != "completed"
            or run.get("conclusion")
            not in {"failure", "timed_out", "action_required", "startup_failure"}
            or not any(actor.get("id") == github_id for actor in actors)
            or not positive_id(run.get("id"))
        ):
            return None
        return (
            f"Workflow failed in {name}: {clean(run.get('name'))}",
            f"https://github.com/{name}/actions/runs/{run['id']}",
        )
    if (obj(payload.get("sender"))).get("id") == github_id:
        return None
    item = payload.get("pull_request") or payload.get("issue") or {}
    number = positive_id(item.get("number"))
    if not number:
        return None
    is_pr = bool(payload.get("pull_request") or item.get("pull_request"))
    reason = None
    if event in {"issues", "pull_request"}:
        if action == "assigned" and (obj(payload.get("assignee"))).get("id") == github_id:
            reason = "Assigned to you"
        elif (
            event == "pull_request"
            and action == "review_requested"
            and (obj(payload.get("requested_reviewer"))).get("id") == github_id
        ):
            reason = "Review requested"
        elif action in {"opened", "edited"} and mention(item.get("body"), login):
            reason = "You were mentioned"
    elif event in {"issue_comment", "pull_request_review_comment", "pull_request_review"}:
        content = (
            payload.get("review") if event == "pull_request_review" else payload.get("comment")
        )
        if action in {"created", "edited", "submitted"} and mention(
            obj(content).get("body"), login
        ):
            reason = "You were mentioned"
    previous = obj(obj(payload.get("changes")).get("body")).get("from")
    if reason == "You were mentioned" and action == "edited":
        if "body" not in obj(payload.get("changes")) or mention(previous, login):
            return None
    if not reason:
        return None
    kind = "pull" if is_pr else "issues"
    return (
        f"{reason} in {name} #{number}: {clean(item.get('title'))}",
        f"https://github.com/{name}/{kind}/{number}",
    )
