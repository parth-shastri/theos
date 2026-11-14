"""Read and dismiss notifications in the signed-in browser."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, Request
from pydantic import BaseModel, Field


class Notice(BaseModel):
    source: Literal["github", "reminder"]
    id: str = Field(min_length=1, max_length=200)


class Dismissal(BaseModel):
    notice: Notice | None = None


def browser_inbox(db, owner):
    rows = db.rows(
        """
        WITH inbox AS (
            SELECT id, 'reminder' AS source, text, NULL AS url, created
            FROM notifications WHERE owner=? AND browser_dismissal IS NULL
            UNION ALL
            SELECT id, 'github', text, url, created
            FROM github_notifications WHERE owner=? AND read=0 AND browser_dismissal IS NULL
        )
        SELECT *, COUNT(*) OVER () AS unread
        FROM inbox ORDER BY created DESC, source, id LIMIT 50
        """,
        (owner, owner),
    )
    unread = rows[0]["unread"] if rows else 0
    for row in rows:
        del row["unread"]
    return {"items": rows, "unread": unread}


def register_notifications(app, current, identity):
    @app.get("/api/notifications/browser")
    async def inbox(request: Request, owner: Annotated[str, Depends(identity)]):
        return browser_inbox(current(request).db, owner)

    @app.post("/api/notifications/browser/dismiss")
    async def dismiss(body: Dismissal, request: Request, owner: Annotated[str, Depends(identity)]):
        db = current(request).db
        batch = uuid4().hex
        notice = body.notice
        notice_id = notice.id if notice else None
        changed = 0
        # Both sources enter the same undo batch. Delivery status is independent.
        with db.transaction():
            if notice is None or notice.source == "reminder":
                changed += db.execute(
                    "UPDATE notifications SET browser_dismissal=? "
                    "WHERE owner=? AND browser_dismissal IS NULL AND (? IS NULL OR id=?)",
                    (batch, owner, notice_id, notice_id),
                ).rowcount
            if notice is None or notice.source == "github":
                changed += db.execute(
                    "UPDATE github_notifications SET browser_dismissal=? "
                    "WHERE owner=? AND browser_dismissal IS NULL AND read=0 AND (? IS NULL OR id=?)",
                    (batch, owner, notice_id, notice_id),
                ).rowcount
        return {"batch": batch if changed else None, **browser_inbox(db, owner)}

    @app.delete("/api/notifications/browser/dismiss/{batch}")
    async def restore(batch: UUID, request: Request, owner: Annotated[str, Depends(identity)]):
        db = current(request).db
        with db.transaction():
            db.execute(
                "UPDATE notifications SET browser_dismissal=NULL WHERE owner=? AND browser_dismissal=?",
                (owner, batch.hex),
            )
            db.execute(
                "UPDATE github_notifications SET browser_dismissal=NULL WHERE owner=? AND browser_dismissal=?",
                (owner, batch.hex),
            )
        return browser_inbox(db, owner)
