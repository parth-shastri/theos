CREATE TABLE telegram_access (
 owner TEXT PRIMARY KEY REFERENCES users(id),
 code_fingerprint TEXT NOT NULL,
 granted REAL NOT NULL
);
