ALTER TABLE telegram_updates ADD COLUMN received REAL NOT NULL DEFAULT 0;
CREATE INDEX telegram_pending ON telegram_updates(status,id);
