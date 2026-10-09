CREATE TABLE users (id TEXT PRIMARY KEY, created REAL NOT NULL);
CREATE TABLE sessions (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), channel TEXT NOT NULL,
 address TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, model TEXT NOT NULL, reasoning TEXT NOT NULL,
 history TEXT NOT NULL DEFAULT '[]', memory TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'idle', created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX sessions_owner ON sessions(owner, updated);
CREATE UNIQUE INDEX session_address ON sessions(owner, channel, address) WHERE address != '';
CREATE TABLE approvals (
 id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 call_id TEXT NOT NULL, tool TEXT NOT NULL, arguments TEXT NOT NULL, preview TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL, expires REAL NOT NULL,
 UNIQUE(session, call_id)
);
CREATE TABLE tool_runs (
 session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, call_id TEXT NOT NULL,
 tool TEXT NOT NULL, status TEXT NOT NULL, result TEXT, PRIMARY KEY(session, call_id)
);
CREATE TABLE records (
 owner TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, id TEXT NOT NULL,
 value TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(owner, kind, id)
);
CREATE TABLE reminders (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), session TEXT NOT NULL REFERENCES sessions(id),
 text TEXT NOT NULL, due REAL NOT NULL, cron TEXT, timezone TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX reminders_due ON reminders(status, due);
CREATE TABLE notifications (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, session TEXT NOT NULL, text TEXT NOT NULL,
 created REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 due REAL NOT NULL, result TEXT, updated REAL NOT NULL
);
CREATE TABLE oauth_states (
 digest TEXT PRIMARY KEY, owner TEXT NOT NULL, service TEXT NOT NULL, verifier TEXT NOT NULL,
 expires REAL NOT NULL
);
CREATE TABLE credentials (
 owner TEXT NOT NULL, service TEXT NOT NULL, encrypted TEXT NOT NULL, updated REAL NOT NULL,
 PRIMARY KEY(owner, service)
);
CREATE TABLE usage (
 id INTEGER PRIMARY KEY, owner TEXT NOT NULL, session TEXT NOT NULL, model TEXT NOT NULL,
 input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cache_tokens INTEGER NOT NULL,
 cost REAL, created REAL NOT NULL
);
CREATE TABLE traces (
 id INTEGER PRIMARY KEY, owner TEXT NOT NULL, session TEXT NOT NULL, event TEXT NOT NULL,
 tool TEXT, status TEXT, created REAL NOT NULL
);
CREATE TABLE telegram_updates (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
CREATE TABLE application_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, media_type TEXT NOT NULL,
 size INTEGER NOT NULL, path TEXT NOT NULL, object_key TEXT, created REAL NOT NULL
);
