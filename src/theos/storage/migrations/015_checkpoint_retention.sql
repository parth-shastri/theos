CREATE TABLE context_deletions (
 id TEXT PRIMARY KEY,
 owner TEXT NOT NULL REFERENCES users(id),
 session TEXT NOT NULL REFERENCES sessions(id),
 object_key TEXT NOT NULL,
 remote_required INTEGER NOT NULL,
 created REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 due REAL NOT NULL
);
CREATE INDEX context_deletions_due ON context_deletions(due);
