"""Content-free token accounting and configured cost estimates."""

import time

from .model_catalog import wire_model


def usage_summary(db, *, owner=None, session=None):
    """Count unpriced requests separately so incomplete estimates stay visible."""
    clauses, values = [], []
    for column, value in (("owner", owner), ("session", session)):
        if value is not None:
            clauses.append(f"{column}=?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return db.one(
        "SELECT COUNT(*) AS requests, COUNT(cost) AS priced_requests, "
        "COUNT(*)-COUNT(cost) AS unpriced_requests, SUM(cost) AS cost, "
        "COALESCE(SUM(input_tokens),0) AS input_tokens, "
        "COALESCE(SUM(output_tokens),0) AS output_tokens FROM usage" + where,
        tuple(values),
    )


def record_usage(runtime, session, usage):
    """Store token counters and configured cost estimates without prompt content."""
    incoming, outgoing = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    cost = None
    rates = runtime.settings.model_costs.get(session["model"]) or runtime.settings.model_costs.get(
        wire_model(runtime.settings.provider, session["model"])
    )
    input_rate = rates.input if rates else runtime.settings.input_cost_per_million
    output_rate = rates.output if rates else runtime.settings.output_cost_per_million
    if input_rate is not None and output_rate is not None:
        cost = (incoming * input_rate + outgoing * output_rate) / 1_000_000
    reported = usage.get("cost_nanousd")
    if isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0:
        cost = reported / 1_000_000_000
    runtime.db.execute(
        "INSERT INTO usage(owner,session,model,input_tokens,output_tokens,cache_tokens,cost,created) VALUES (?,?,?,?,?,?,?,?)",
        (
            session["owner"],
            session["id"],
            session["model"],
            incoming,
            outgoing,
            usage.get("cache_read_tokens", 0),
            cost,
            time.time(),
        ),
    )
