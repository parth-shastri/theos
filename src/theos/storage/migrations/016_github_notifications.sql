CREATE TABLE github_subscriptions (
 owner TEXT PRIMARY KEY REFERENCES users(id),
 github_id INTEGER NOT NULL,
 login TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0,
 telegram INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1,
 updated REAL NOT NULL
);
CREATE TABLE github_deliveries (
 id TEXT PRIMARY KEY,
 event TEXT NOT NULL,
 digest TEXT NOT NULL,
 encrypted TEXT,
 created REAL NOT NULL,
 due REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 cursor TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX github_deliveries_due ON github_deliveries(status,due);
CREATE TABLE github_notifications (
 id TEXT PRIMARY KEY,
 delivery TEXT NOT NULL REFERENCES github_deliveries(id) ON DELETE CASCADE,
 owner TEXT NOT NULL REFERENCES users(id),
 github_id INTEGER NOT NULL,
 revision INTEGER NOT NULL,
 repo_id INTEGER NOT NULL,
 text TEXT NOT NULL,
 url TEXT NOT NULL,
 created REAL NOT NULL,
 read INTEGER NOT NULL DEFAULT 0,
 telegram TEXT NOT NULL DEFAULT 'not_requested',
 due REAL NOT NULL,
 UNIQUE(delivery,owner)
);
CREATE INDEX github_notifications_owner ON github_notifications(owner,created);
CREATE INDEX github_notifications_delivery ON github_notifications(telegram,due);
