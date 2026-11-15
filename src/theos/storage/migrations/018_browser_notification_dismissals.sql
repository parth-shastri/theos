ALTER TABLE notifications ADD COLUMN browser_dismissal TEXT;
ALTER TABLE github_notifications ADD COLUMN browser_dismissal TEXT;

CREATE INDEX notifications_owner_created ON notifications(owner, created DESC);
