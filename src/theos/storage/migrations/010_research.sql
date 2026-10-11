CREATE TABLE research_runs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(id),
    session TEXT NOT NULL REFERENCES sessions(id),
    parent TEXT REFERENCES research_runs(id),
    name TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    reason TEXT,
    answer TEXT NOT NULL DEFAULT '',
    history TEXT NOT NULL DEFAULT '[]',
    memory TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX research_session ON research_runs(owner, session, created);
CREATE TABLE research_items (
    id TEXT PRIMARY KEY,
    run TEXT NOT NULL REFERENCES research_runs(id),
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE INDEX research_item_run ON research_items(run, created);
CREATE TABLE research_checkpoints (
    id INTEGER PRIMARY KEY,
    run TEXT NOT NULL REFERENCES research_runs(id),
    history TEXT NOT NULL,
    memory TEXT NOT NULL,
    created REAL NOT NULL
);
