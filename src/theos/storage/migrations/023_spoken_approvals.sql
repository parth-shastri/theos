ALTER TABLE phone_calls ADD COLUMN voice_review_digest TEXT;
ALTER TABLE phone_calls ADD COLUMN voice_recipient INTEGER;
ALTER TABLE phone_calls ADD COLUMN voice_response_digest TEXT;
ALTER TABLE phone_calls ADD COLUMN voice_status TEXT CHECK (voice_status IN (
    'listening', 'processing', 'approved', 'denied', 'unrecognized', 'stale',
    'expired', 'unanswered', 'uncertain', 'unavailable'
));
ALTER TABLE phone_calls ADD COLUMN voice_decided REAL;
CREATE INDEX phone_calls_voice ON phone_calls(voice_status) WHERE voice_status='listening';
ALTER TABLE phone_calls ADD COLUMN conversation_expires REAL;
ALTER TABLE phone_calls ADD COLUMN conversation_status TEXT CHECK (conversation_status IN ('active','closed','uncertain'));
ALTER TABLE phone_calls ADD COLUMN conversation_approval TEXT;
ALTER TABLE phone_calls ADD COLUMN conversation_review_digest TEXT;
CREATE TABLE call_utterances (
    call_id TEXT NOT NULL REFERENCES phone_calls(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 20),
    status TEXT NOT NULL CHECK(status IN ('processing','replied','approved','denied','ended','uncertain')),
    response_digest TEXT NOT NULL,
    input_text TEXT NOT NULL DEFAULT '',
    reply_text TEXT NOT NULL DEFAULT '',
    intent TEXT,
    approval_id TEXT,
    review_digest TEXT,
    created REAL NOT NULL,
    PRIMARY KEY(call_id,ordinal)
);
