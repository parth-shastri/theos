ALTER TABLE reminders ADD COLUMN delivery TEXT NOT NULL DEFAULT 'message'
    CHECK (delivery IN ('message', 'phone'));

CREATE TABLE phone_calls (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(id),
    session TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('reminder', 'approval')),
    source_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('telegram', 'twilio')),
    due REAL NOT NULL,
    expires REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'accepted', 'failed', 'uncertain', 'skipped', 'rate_limited')),
    attempted REAL,
    call_sid TEXT,
    audio_digest TEXT UNIQUE,
    audio_expires REAL,
    audio BLOB
);
CREATE INDEX phone_calls_due ON phone_calls(status, due);
CREATE INDEX phone_calls_attempted ON phone_calls(attempted) WHERE attempted IS NOT NULL;
CREATE INDEX phone_calls_reminders ON phone_calls(owner, source_id, due) WHERE kind='reminder';
