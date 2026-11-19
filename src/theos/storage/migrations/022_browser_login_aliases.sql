CREATE TABLE browser_login_aliases (
 alias TEXT PRIMARY KEY COLLATE NOCASE,
 owner TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
 CHECK (length(alias) BETWEEN 3 AND 64),
 CHECK (alias NOT GLOB '*[^A-Za-z0-9_]*')
);
