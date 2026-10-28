"""Dashboard charts cover complete UTC periods and retain unknown costs."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from theos.server import create_app
from theos.transports.browser.activity import activity_summary


def usage(db, session, created, cost, incoming=10, outgoing=5):
    db.execute(
        "INSERT INTO usage(owner,session,model,input_tokens,output_tokens,cache_tokens,cost,created) "
        "VALUES (?,?,?,?,?,0,?,?)",
        (
            session["owner"],
            session["id"],
            session["model"],
            incoming,
            outgoing,
            cost,
            created.timestamp(),
        ),
    )


def test_chart_aggregates_cover_all_rows_transports_and_utc_boundaries(db):
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    start = datetime(2026, 9, 30, tzinfo=UTC)
    browser = db.create_session("alice", "model-a", "default")
    telegram = db.create_session("bob", "model-b", "default", channel="telegram")
    usage(db, browser, start - timedelta(seconds=1), 9)
    usage(db, browser, now + timedelta(seconds=1), 9)
    for _ in range(120):
        usage(db, browser, start, 0.01)
    usage(db, telegram, now, None, incoming=20, outgoing=10)
    for event, tool, created in [
        ("ToolStarted", "get_preferences", now),
        ("ToolFinished", "get_preferences", now),
        ("ToolStarted", "old_tool", start - timedelta(seconds=1)),
    ]:
        db.execute(
            "INSERT INTO traces(owner,session,event,tool,created) VALUES (?,?,?,?,?)",
            ("bob", telegram["id"], event, tool, created.timestamp()),
        )
    data = activity_summary(db, 7, now=now)
    assert len(data["daily"]) == 7 and data["timezone"] == "UTC"
    assert data["daily"][0]["date"] == "2026-09-30"
    assert data["daily"][0]["requests"] == 120
    assert data["daily"][0]["cost"] == pytest.approx(1.2)
    assert data["daily"][1]["cost"] == 0 and data["daily"][1]["requests"] == 0
    assert data["daily"][-1]["cost"] is None
    assert data["totals"] == {
        "requests": 121,
        "unpriced_requests": 1,
        "cost": pytest.approx(1.2),
        "input_tokens": 1220,
        "output_tokens": 610,
    }
    assert [row["requests"] for row in data["models"]] == [120, 1]
    assert data["tools"] == [{"tool": "get_preferences", "calls": 1}]


def test_unknown_costs_are_not_zero_and_empty_periods_are_explicit(db):
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    session = db.create_session("alice", "model-a", "default")
    empty = activity_summary(db, 30, now=now)
    assert len(empty["daily"]) == 30
    assert empty["totals"]["requests"] == 0 and empty["totals"]["cost"] == 0
    assert empty["models"] == empty["tools"] == []
    usage(db, session, now, None)
    unknown = activity_summary(db, 30, now=now)
    assert unknown["totals"]["cost"] is None
    assert unknown["daily"][-1]["cost"] is None
    usage(db, session, now, 0)
    partial = activity_summary(db, 30, now=now)
    assert partial["totals"]["cost"] == 0 and partial["totals"]["unpriced_requests"] == 1
    assert partial["daily"][-1]["cost"] == 0
    with pytest.raises(ValueError):
        activity_summary(db, 1000, now=now)


async def test_dashboard_chart_ranges_and_admin_access(runtime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        assert (await browser.get("/api/dashboard?days=7")).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        for days in (7, 30, 90):
            response = await browser.get(f"/api/dashboard?days={days}")
            assert response.status_code == 200
            assert response.json()["activity"]["days"] == days
            assert len(response.json()["activity"]["daily"]) == days
        assert (await browser.get("/api/dashboard?days=1000")).status_code == 422
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.get("/api/dashboard?days=7")).status_code == 403


async def test_personal_activity_is_owner_scoped_and_admin_dashboard_has_no_content(runtime):
    db = runtime.db
    now = datetime.now(UTC)
    alice = db.create_session("alice", "model-alice", "default", title="PRIVATE ALICE TITLE")
    bob = db.create_session("bob", "model-bob", "default", title="PRIVATE BOB TITLE")
    telegram = db.create_session(
        "telegram:123", "model-telegram", "default", channel="telegram-private"
    )
    for session, cost in ((alice, 1), (bob, None), (telegram, 3)):
        usage(db, session, now, cost)
        db.execute(
            "UPDATE sessions SET history=?,memory=? WHERE id=?",
            ('["PRIVATE MESSAGE"]', '{"fact":"PRIVATE MEMORY"}', session["id"]),
        )
        db.execute(
            "INSERT INTO traces(owner,session,event,tool,created) VALUES (?,?,?,?,?)",
            (session["owner"], session["id"], "ToolStarted", session["model"], now.timestamp()),
        )
        db.put_record(session["owner"], "preferences", "settings", {"name": "PRIVATE PROFILE"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        assert (await browser.get("/api/activity")).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        for days in (7, 30, 90):
            response = await browser.get(f"/api/activity?days={days}&owner=alice")
            assert response.status_code == 200
            personal = response.json()
            assert personal["totals"]["requests"] == 1
            assert personal["totals"]["conversations"] == 1
            assert personal["totals"]["cost"] is None
            assert personal["activity"]["totals"]["requests"] == 1
            assert personal["activity"]["tools"] == [{"tool": "model-bob", "calls": 1}]
            assert [row["model"] for row in personal["activity"]["models"]] == ["model-bob"]
            assert {row["owner"] for row in personal["usage"]} == {"bob"}
            assert [row["id"] for row in personal["cost_per_conversation"]] == [bob["id"]]
            assert "alice" not in response.text and "telegram:123" not in response.text
            assert "PRIVATE" not in response.text
        assert (await browser.get("/api/activity?days=1")).status_code == 422
        assert (await browser.get("/api/dashboard")).status_code == 403
        assert (await browser.get("/api/logs")).status_code == 403

        browser.headers["Authorization"] = "Bearer " + "a" * 32
        personal = (await browser.get("/api/activity")).json()
        assert personal["totals"]["requests"] == 1
        assert {row["owner"] for row in personal["usage"]} == {"alice"}
        response = await browser.get("/api/dashboard")
        admin = response.json()
        assert admin["totals"]["requests"] == 3
        assert admin["totals"]["input_tokens"] == 30
        assert admin["totals"]["output_tokens"] == 15
        assert admin["totals"]["cost"] == 4
        assert admin["totals"]["unpriced_requests"] == 1
        assert admin["activity"]["totals"]["requests"] == 3
        assert {row["owner"] for row in admin["cost_per_user"]} == {"alice", "bob", "telegram:123"}
        assert all(row["input_tokens"] == 10 for row in admin["cost_per_user"])
        assert all(row["output_tokens"] == 5 for row in admin["cost_per_user"])
        assert "PRIVATE" not in response.text
        assert all("title" not in row and "history" not in row for row in admin["sessions"])
        assert all("title" not in row for row in admin["cost_per_conversation"])
        assert (await browser.get(f"/api/sessions/{bob['id']}")).status_code == 404


async def test_api_does_not_serve_the_separate_frontend(runtime):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
    ) as browser:
        for path in ("/", "/static/app.js", "/_next/static/app.js"):
            response = await browser.get(path)
            assert response.status_code == 404
            assert "script-src 'self'" in response.headers["Content-Security-Policy"]
