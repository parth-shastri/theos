CREATE TABLE phone_calls_next (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(id),
    session TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('reminder', 'approval', 'request')),
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

INSERT INTO phone_calls_next
    (id,owner,session,kind,source_id,provider,due,expires,status,attempted,call_sid,audio_digest,audio_expires,audio)
SELECT id,owner,session,kind,source_id,provider,due,expires,status,attempted,call_sid,audio_digest,audio_expires,audio
FROM phone_calls;

DROP TABLE phone_calls;
ALTER TABLE phone_calls_next RENAME TO phone_calls;
CREATE INDEX phone_calls_due ON phone_calls(status, due);
CREATE INDEX phone_calls_attempted ON phone_calls(attempted) WHERE attempted IS NOT NULL;
CREATE INDEX phone_calls_reminders ON phone_calls(owner, source_id, due) WHERE kind='reminder';
