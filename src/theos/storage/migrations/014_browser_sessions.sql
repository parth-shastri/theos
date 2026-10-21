CREATE TABLE browser_session_metadata (
 token_hash TEXT PRIMARY KEY REFERENCES browser_credentials(token_hash) ON DELETE CASCADE,
 last_used REAL NOT NULL,
 credential_hash TEXT
);
INSERT INTO browser_session_metadata(token_hash, last_used)
 SELECT token_hash, created FROM browser_credentials WHERE kind='session';

CREATE TABLE browser_login_attempts (
 bucket TEXT NOT NULL,
 attempted REAL NOT NULL
);
CREATE INDEX browser_login_attempts_time ON browser_login_attempts(bucket, attempted);
