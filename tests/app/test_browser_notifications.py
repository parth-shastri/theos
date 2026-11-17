"""Browser dismissal is owner scoped and independent of notification delivery."""

import httpx


async def test_browser_dismissal_and_undo_preserve_notification_delivery(runtime):
    from theos.server import create_app

    db = runtime.db
    for name in ("alice", "bob"):
        session = db.create_session(name, runtime.settings.model, "default")
        db.execute(
            "INSERT INTO notifications(id,owner,session,text,created,delivered) "
            "VALUES (?,?,?,?,?,0)",
            (name, name, session["id"], "Reminder", 1),
        )
    db.execute(
        "INSERT INTO github_deliveries(id,event,digest,created,due) VALUES ('d','e','d',0,0)"
    )
    db.execute(
        "INSERT INTO github_notifications"
        "(id,delivery,owner,github_id,revision,repo_id,text,url,created,telegram,due) "
        "VALUES ('alice','d','alice',1,1,1,'Workflow failed','https://github.com/a/b/actions/runs/9',2,'pending',0)"
    )
    transport = httpx.ASGITransport(app=create_app(runtime.settings, runtime))
    path = "/api/notifications/browser"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        alice = {"Authorization": "Bearer " + "a" * 32}
        bob = {"Authorization": "Bearer " + "b" * 32}

        async def inbox(headers):
            response = await client.get(path, headers=headers)
            assert response.status_code == 200
            return response.json()

        assert (await client.get(path)).status_code == 401
        assert (await inbox(alice))["unread"] == 2
        history = (await client.get(path + "/history", headers=alice)).json()
        assert [(item["source"], item["unread"]) for item in history["items"]] == [
            ("github", 1),
            ("reminder", 1),
        ]
        response = await client.post(
            path + "/dismiss", headers=alice, json={"notice": {"id": "alice", "source": "github"}}
        )
        single = response.json()["batch"]
        assert (await inbox(alice))["unread"] == 1
        assert (await inbox(bob))["unread"] == 1
        await client.delete(f"{path}/dismiss/{single}", headers=bob)
        assert (await inbox(alice))["unread"] == 1

        result = await client.post(path + "/dismiss", headers=alice, json={})
        bulk = result.json()["batch"]
        assert await inbox(alice) == {"items": [], "unread": 0}
        history = (await client.get(path + "/history", headers=alice)).json()
        assert [item["unread"] for item in history["items"]] == [0, 0]
        # A notice created after dismissal must stay visible.
        db.execute(
            "INSERT INTO notifications(id,owner,session,text,created) "
            "SELECT 'new',owner,session,'New reminder',3 FROM notifications WHERE id='alice'"
        )
        assert [row["id"] for row in (await inbox(alice))["items"]] == ["new"]
        await client.delete(f"{path}/dismiss/{bulk}", headers=alice)
        assert (await inbox(alice))["unread"] == 2
        await client.delete(f"{path}/dismiss/{single}", headers=alice)
        assert (await inbox(alice))["unread"] == 3
        assert (await inbox(bob))["unread"] == 1

        await client.post(path + "/dismiss", headers=alice, json={})
        legacy = (await client.get("/api/notifications", headers=alice)).json()
        assert len(legacy) == 3
        assert db.one("SELECT delivered FROM notifications WHERE id='alice'")["delivered"] == 0
        assert db.one("SELECT telegram FROM github_notifications")["telegram"] == "pending"


async def test_notification_history_paginates_and_keeps_owners_separate(runtime):
    from theos.server import create_app

    db = runtime.db
    for owner in ("alice", "bob"):
        db.create_session(owner, runtime.settings.model, "default")
    session = db.one("SELECT id FROM sessions WHERE owner='alice'")["id"]
    for index in range(52):
        db.execute(
            "INSERT INTO notifications(id,owner,session,text,created) VALUES (?,?,?,?,?)",
            (f"notice-{index}", "alice", session, f"Reminder {index}", index),
        )
    bob_session = db.one("SELECT id FROM sessions WHERE owner='bob'")["id"]
    db.execute(
        "INSERT INTO notifications(id,owner,session,text,created) VALUES ('bob','bob',?,'Private',100)",
        (bob_session,),
    )
    transport = httpx.ASGITransport(app=create_app(runtime.settings, runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        alice = {"Authorization": "Bearer " + "a" * 32}
        bob = {"Authorization": "Bearer " + "b" * 32}
        path = "/api/notifications/browser/history"
        assert (await client.get(path)).status_code == 401
        first = (await client.get(path, headers=alice)).json()
        assert len(first["items"]) == 50
        assert first["items"][0]["id"] == "notice-51"
        assert first["next_offset"] == 50
        second = (await client.get(path + "?offset=50", headers=alice)).json()
        assert [item["id"] for item in second["items"]] == ["notice-1", "notice-0"]
        assert second["next_offset"] is None
        assert [item["id"] for item in (await client.get(path, headers=bob)).json()["items"]] == [
            "bob"
        ]
