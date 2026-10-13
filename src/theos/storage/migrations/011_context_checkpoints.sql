CREATE TABLE context_objects (
 id TEXT PRIMARY KEY,
 owner TEXT NOT NULL REFERENCES users(id),
 session TEXT NOT NULL REFERENCES sessions(id),
 kind TEXT NOT NULL,
 digest TEXT NOT NULL,
 path TEXT NOT NULL,
 object_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 created REAL NOT NULL
);
CREATE INDEX context_objects_session ON context_objects(owner, session, kind, created);
