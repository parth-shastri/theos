CREATE TABLE scheduled_tasks (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
 session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 name TEXT NOT NULL, prompt TEXT NOT NULL, due REAL NOT NULL,
 cron TEXT, timezone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 created REAL NOT NULL
);
CREATE INDEX scheduled_tasks_due ON scheduled_tasks(status, due);
CREATE TABLE scheduled_runs (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
 session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 due REAL NOT NULL, status TEXT NOT NULL, started REAL NOT NULL, finished REAL,
 delivery TEXT NOT NULL DEFAULT 'pending', UNIQUE(task_id, due)
);
CREATE TABLE memory_batches (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
 session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL,
 updated REAL NOT NULL, error TEXT
);
CREATE INDEX memory_batches_pending ON memory_batches(status, owner, created);
