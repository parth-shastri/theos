CREATE TABLE telegram_enrollments (
 user_id INTEGER PRIMARY KEY,
 owner TEXT NOT NULL UNIQUE REFERENCES users(id),
 state TEXT NOT NULL CHECK (state IN ('timezone', 'ready')),
 created REAL NOT NULL
);

-- Existing private users retain access and count toward the enrollment limit.
INSERT INTO telegram_enrollments(user_id,owner,state,created)
SELECT CAST(SUBSTR(owner,10) AS INTEGER),owner,'ready',MIN(created)
FROM sessions
WHERE channel='telegram-private' AND owner LIKE 'telegram:%'
GROUP BY owner;
