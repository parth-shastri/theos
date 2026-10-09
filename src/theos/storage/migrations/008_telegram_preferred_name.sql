-- Add the preferred-name step without restarting existing users' setup.
CREATE TABLE telegram_enrollments_new (
 user_id INTEGER PRIMARY KEY,
 owner TEXT NOT NULL UNIQUE REFERENCES users(id),
 state TEXT NOT NULL CHECK (state IN ('name', 'timezone', 'ready')),
 created REAL NOT NULL
);

INSERT INTO telegram_enrollments_new SELECT * FROM telegram_enrollments;
DROP TABLE telegram_enrollments;
ALTER TABLE telegram_enrollments_new RENAME TO telegram_enrollments;
