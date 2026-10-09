"""SQLite storage, migrations, and restart recovery for one application process."""

import fcntl
import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from .messages import restore_message, serialize_message


class Database:
    """Own one connection. Transactions contain no awaits or network requests."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "theos.sqlite3"
        self.lock_file = (directory / "process.lock").open("a")
        try:
            # SQLite protects writes, but only one process may deliver scheduled work.
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise RuntimeError(
                "This database already has an application process. Use one worker."
            ) from None
        self.connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.path.chmod(0o600)
        try:
            self.migrate()
            self.recover()
        except Exception:
            self.close()
            raise

    def migrate(self):
        """Apply each numbered migration in its own transaction."""
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            number = int(path.name.split("_", 1)[0])
            if number > version:
                self.connection.executescript(
                    f"BEGIN IMMEDIATE;\n{path.read_text()}\nPRAGMA user_version={number};\nCOMMIT;"
                )

    @contextmanager
    def transaction(self):
        """Commit related writes together, or roll all of them back."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def execute(self, sql, parameters=()):
        """Run a parameterized statement on the application connection."""
        return self.connection.execute(sql, parameters)

    def rows(self, sql, parameters=()):
        """Read result rows as dictionaries."""
        return [dict(row) for row in self.execute(sql, parameters).fetchall()]

    def one(self, sql, parameters=()):
        """Read one result row or return None."""
        row = self.execute(sql, parameters).fetchone()
        return dict(row) if row else None

    def recover(self):
        """Preserve uncertain writes instead of repeating them after a crash."""
        with self.transaction():
            # 1. Preserve uncertainty. An interrupted process cannot prove an external write failed.
            self.execute("UPDATE tool_runs SET status='unknown' WHERE status='running'")
            self.execute("UPDATE sessions SET status='interrupted' WHERE status='running'")
            # 2. Ask durable jobs to inspect remote state before another write.
            self.execute("UPDATE jobs SET status='reconcile' WHERE status='running'")
            # 3. Keep interrupted replies and updates out of the automatic delivery queue.
            self.execute("UPDATE telegram_updates SET status='uncertain' WHERE status='running'")
            self.execute("UPDATE notifications SET delivered=-1 WHERE delivered=2")
            # Background work also preserves uncertain external effects across restarts.
            self.execute(
                "UPDATE scheduled_tasks SET status='paused' WHERE id IN "
                "(SELECT task_id FROM scheduled_runs WHERE status='running')"
            )
            self.execute("UPDATE scheduled_runs SET status='interrupted' WHERE status='running'")
            self.execute("UPDATE scheduled_runs SET delivery='uncertain' WHERE delivery='sending'")
            self.execute(
                "UPDATE memory_batches SET status='unknown', content='', error='Interrupted write' "
                "WHERE status='running'"
            )
            # 4. Expire old decisions before any conversation resumes.
            self.execute(
                "UPDATE approvals SET status='expired' WHERE status='pending' AND expires<?",
                (time.time(),),
            )

    def ensure_user(self, owner):
        """Create an owner record before saving dependent records."""
        self.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (owner, time.time()))

    def create_session(
        self,
        owner,
        model,
        reasoning,
        channel="browser",
        address="",
        title="New conversation",
        *,
        session_id=None,
    ):
        """Create a persistent conversation bound to an owner and transport."""
        self.ensure_user(owner)
        session_id = session_id or uuid4().hex
        now = time.time()
        self.execute(
            "INSERT INTO sessions(id,owner,channel,address,title,model,reasoning,created,updated,title_auto) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                owner,
                channel,
                address,
                title,
                model,
                reasoning,
                now,
                now,
                int(title == "New conversation"),
            ),
        )
        return self.session(owner, session_id)

    def session(self, owner, session_id):
        """Read an owned conversation or report that it does not exist."""
        # An opaque session ID is not permission. Every lookup also needs the owner.
        row = self.one("SELECT * FROM sessions WHERE owner=? AND id=?", (owner, session_id))
        if row is None:
            raise LookupError("Conversation not found.")
        return row

    def load_history(self, owner, session_id):
        """Restore typed harness messages from the saved conversation."""
        return [
            restore_message(value)
            for value in json.loads(self.session(owner, session_id)["history"])
        ]

    def save_history(self, owner, session_id, history, memory=None, status=None):
        """Save owned conversation messages and optional runtime state."""
        self.session(owner, session_id)
        self.execute(
            "UPDATE sessions SET history=?, memory=COALESCE(?,memory), status=COALESCE(?,status), updated=? WHERE id=? AND owner=?",
            (
                json.dumps([serialize_message(m) for m in history]),
                json.dumps(memory) if memory is not None else None,
                status,
                time.time(),
                session_id,
                owner,
            ),
        )

    def put_record(self, owner, kind, record_id, value):
        """Insert or replace one record within the owner and kind."""
        self.ensure_user(owner)
        self.execute(
            "INSERT INTO records VALUES (?,?,?,?,?) ON CONFLICT(owner,kind,id) DO UPDATE SET value=excluded.value,updated=excluded.updated",
            (owner, kind, record_id, json.dumps(value), time.time()),
        )
        return {"id": record_id, **value}

    def record(self, owner, kind, record_id):
        """Read a record only within the requested owner and kind."""
        row = self.one(
            "SELECT value FROM records WHERE owner=? AND kind=? AND id=?", (owner, kind, record_id)
        )
        if row is None:
            raise LookupError("Record not found.")
        return {"id": record_id, **json.loads(row["value"])}

    def records(self, owner, kind):
        """List the owner records for one kind, newest first."""
        return [
            {"id": r["id"], **json.loads(r["value"])}
            for r in self.rows(
                "SELECT id,value FROM records WHERE owner=? AND kind=? ORDER BY updated DESC",
                (owner, kind),
            )
        ]

    def delete_record(self, owner, kind, record_id):
        """Delete a record after checking its owner and kind."""
        self.record(owner, kind, record_id)
        self.execute(
            "DELETE FROM records WHERE owner=? AND kind=? AND id=?", (owner, kind, record_id)
        )
        return {"deleted": record_id}

    def backup(self, destination: Path):
        """Copy a consistent snapshot, including committed WAL data."""
        with closing(sqlite3.connect(destination)) as target:
            self.connection.backup(target)
        destination.chmod(0o600)

    def close(self):
        """Release the SQLite connection and single-process lock."""
        self.connection.close()
        self.lock_file.close()
