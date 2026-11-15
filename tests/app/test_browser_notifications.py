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
