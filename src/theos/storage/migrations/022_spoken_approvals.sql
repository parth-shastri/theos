ALTER TABLE phone_calls ADD COLUMN voice_review_digest TEXT;
ALTER TABLE phone_calls ADD COLUMN voice_recipient INTEGER;
ALTER TABLE phone_calls ADD COLUMN voice_response_digest TEXT;
ALTER TABLE phone_calls ADD COLUMN voice_status TEXT CHECK (voice_status IN (
    'listening', 'processing', 'approved', 'denied', 'unrecognized', 'stale',
    'expired', 'unanswered', 'uncertain', 'unavailable'
));
ALTER TABLE phone_calls ADD COLUMN voice_decided REAL;
CREATE INDEX phone_calls_voice ON phone_calls(voice_status) WHERE voice_status='listening';
