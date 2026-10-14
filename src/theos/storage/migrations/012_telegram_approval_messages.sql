-- Store only transport message references. Approval contents stay in approvals.
CREATE TABLE telegram_approval_messages (
    approval_id TEXT NOT NULL REFERENCES approvals(id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (approval_id, chat_id, message_id)
);
