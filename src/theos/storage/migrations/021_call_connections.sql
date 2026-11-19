CREATE TABLE call_connections (
    owner TEXT PRIMARY KEY,
    connection_id TEXT UNIQUE,
    recipient INTEGER CHECK (recipient > 0),
    state TEXT NOT NULL CHECK (state IN ('waiting', 'linked', 'ready', 'disabled')),
    reminders INTEGER NOT NULL DEFAULT 0 CHECK (reminders IN (0, 1)),
    approvals INTEGER NOT NULL DEFAULT 0 CHECK (approvals IN (0, 1)),
    test_call_id TEXT,
    updated REAL NOT NULL
);
