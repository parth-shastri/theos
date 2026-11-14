CREATE TABLE browser_passwords (
 owner TEXT PRIMARY KEY REFERENCES users(id),
 salt BLOB NOT NULL,
 digest BLOB NOT NULL,
 configured_token_hash TEXT
);

ALTER TABLE browser_session_metadata ADD COLUMN password_login INTEGER NOT NULL DEFAULT 0;
ALTER TABLE browser_signins ADD COLUMN password_setup INTEGER NOT NULL DEFAULT 0;
