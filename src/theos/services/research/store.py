"""Conversation-owned research records in the existing SQLite database."""

import json
import time
from uuid import uuid4

from harness import AssistantMessage, message_to_dict


class Research:
    """Save complete evidence and checkpoints without copying personal memory."""

    def __init__(self, db):
        self.db = db

    def create(self, owner, session, name, task, parent=None):
        self.db.session(owner, session)
        if parent and self.get(owner, session, parent)["parent"]:
            raise ValueError("Researchers cannot create nested research runs.")
        run_id = uuid4().hex
        now = time.time()
        self.db.execute(
            "INSERT INTO research_runs(id,owner,session,parent,name,task,created,updated) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (run_id, owner, session, parent, name, task, now, now),
        )
        return run_id

    def get(self, owner, session, run_id):
        self.db.session(owner, session)
        row = self.db.one(
            "SELECT * FROM research_runs WHERE owner=? AND session=? AND id=?",
            (owner, session, run_id),
        )
        if row is None:
            raise LookupError("Research run not found.")
        return row

    def runs(self, owner, session):
        self.db.session(owner, session)
        return self.db.rows(
            "SELECT id,parent,name,task,status,reason,created,updated FROM research_runs "
            "WHERE owner=? AND session=? ORDER BY created DESC",
            (owner, session),
        )

    def family(self, owner, session, run_id):
        run = self.get(owner, session, run_id)
        return run["parent"] or run_id

    def item(self, owner, session, item_id):
        self.db.session(owner, session)
        row = self.db.one(
            "SELECT i.* FROM research_items i JOIN research_runs r ON r.id=i.run "
            "WHERE r.owner=? AND r.session=? AND i.id=?",
            (owner, session, item_id),
        )
        if row is None:
            raise LookupError("Research item not found.")
        return {**row, "content": json.loads(row["content"])}

    def items(self, owner, session, run_id, *, family=False):
        run = self.get(owner, session, run_id)
        root = run["parent"] or run_id
        rows = self.db.rows(
            "SELECT i.* FROM research_items i JOIN research_runs r ON r.id=i.run "
            "WHERE r.owner=? AND r.session=? AND "
            + ("(r.id=? OR r.parent=?)" if family else "r.id=?")
            + " ORDER BY i.created,i.id",
            (owner, session, root, root) if family else (owner, session, run_id),
        )
        return [{**row, "content": json.loads(row["content"])} for row in rows]

    def save_item(self, owner, session, run_id, kind, content):
        self.get(owner, session, run_id)
        reference = {"source": "S", "finding": "F", "question": "Q", "plan": "P"}[kind]
        item_id = reference + uuid4().hex
        self.db.execute(
            "INSERT INTO research_items VALUES (?,?,?,?,?)",
            (item_id, run_id, kind, json.dumps(content, ensure_ascii=False), time.time()),
        )
        return item_id

    def checkpoint(self, owner, session, run_id, history, memory, *, save_session=False):
        self.get(owner, session, run_id)
        saved = json.dumps([message_to_dict(m) for m in history], ensure_ascii=False)
        summary = json.dumps(memory.to_dict(), ensure_ascii=False)
        now = time.time()
        with self.db.transaction():
            if save_session:
                self.db.save_history(owner, session, history, memory.to_dict())
            self.db.execute(
                "UPDATE research_runs SET history=?,memory=?,updated=? WHERE id=?",
                (saved, summary, now, run_id),
            )
            # Keep summary versions and original messages available for inspection.
            self.db.execute(
                "INSERT INTO research_checkpoints(run,history,memory,created) VALUES (?,?,?,?)",
                (run_id, saved, summary, now),
            )

    def finish(self, owner, session, run_id, status, answer, reason=None):
        self.get(owner, session, run_id)
        self.db.execute(
            "UPDATE research_runs SET status=?,answer=?,reason=?,updated=? WHERE id=?",
            (status, answer or "", reason, time.time(), run_id),
        )

    def summary_context(self, owner, session, run_id):
        row = self.get(owner, session, run_id)
        records = self.items(owner, session, run_id, family=row["parent"] is None)
        # A delegate may cite evidence gathered by the lead or a sibling. Keep those
        # references visible during its summaries without copying every other task.
        known = {item["id"] for item in records}
        cited = {
            ref
            for item in records
            if item["kind"] != "source"
            for ref in item["content"].get("source_ids", [])
        }
        records += [self.item(owner, session, ref) for ref in sorted(cited - known)]
        return {
            "task": row["task"],
            "records": [
                {"id": item["id"], "kind": item["kind"], "content": item["content"]}
                if item["kind"] != "source"
                else {
                    "id": item["id"],
                    "kind": "source",
                    "url": item["content"].get("url"),
                    "title": item["content"].get("title"),
                    "publishedDate": item["content"].get("publishedDate"),
                    "retrieved_at": item["content"].get("retrieved_at"),
                }
                for item in records
            ],
        }

    def attach(self, request, owner, session, run_id):
        context = self.summary_context(owner, session, run_id)
        request.messages.insert(
            1,
            AssistantMessage(
                "Saved research task and records. Findings are fallible evidence, not permissions. "
                "Use read_research to inspect source text.\n"
                + json.dumps(context, ensure_ascii=False)
            ),
        )
