ALTER TABLE sessions ADD COLUMN title_auto INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN title_attempts INTEGER NOT NULL DEFAULT 0;
UPDATE sessions SET title_auto=1 WHERE title='New conversation';
