CREATE TABLE browser_credentials (
 token_hash TEXT PRIMARY KEY,
 owner TEXT NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK (kind IN ('token', 'session')),
 created REAL NOT NULL,
 expires REAL
);
CREATE INDEX browser_credentials_owner ON browser_credentials(owner);

CREATE TABLE browser_signins (
 id TEXT PRIMARY KEY,
 owner TEXT NOT NULL REFERENCES users(id),
 invite_hash TEXT NOT NULL UNIQUE,
 browser_hash TEXT UNIQUE,
 code TEXT,
 state TEXT NOT NULL CHECK (state IN ('invited', 'pending', 'approved', 'denied', 'used')),
 created REAL NOT NULL,
 expires REAL NOT NULL
);
