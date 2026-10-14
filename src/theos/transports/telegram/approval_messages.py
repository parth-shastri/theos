"""Keep approval notifications pending, then remove their Telegram messages."""

import time

from theos.services.errors import ServiceError


def remember(bot, approval_id, chat, posted):
    """Save message references so multipart reviews survive a process restart."""
    bot.db.execute(
        "INSERT OR IGNORE INTO telegram_approval_messages VALUES (?,?,?)",
        (approval_id, chat, posted["message_id"]),
    )


async def cleanup(bot):
    """Collect decisions from other clients and expired cards after restart."""
    sessions = bot.db.rows(
        "SELECT DISTINCT s.owner,s.id FROM telegram_approval_messages m "
        "JOIN approvals a ON a.id=m.approval_id JOIN sessions s ON s.id=a.session "
        "WHERE a.status!='pending' OR a.expires<=?",
        (time.time(),),
    )
    for session in sessions:
        await remove_resolved(bot, session["owner"], session["id"])


async def remove_resolved(bot, owner, session_id):
    """Remove only this owner's decided or expired approval cards."""
    rows = bot.db.rows(
        "SELECT m.* FROM telegram_approval_messages m "
        "JOIN approvals a ON a.id=m.approval_id JOIN sessions s ON s.id=a.session "
        "WHERE s.owner=? AND s.id=? AND (a.status!='pending' OR a.expires<=?)",
        (owner, session_id, time.time()),
    )
    removed = set()
    for row in rows:
        reference = (row["chat_id"], row["message_id"])
        if reference in removed:
            continue
        try:
            await bot.api(
                "deleteMessage", {"chat_id": row["chat_id"], "message_id": row["message_id"]}
            )
        except ServiceError:
            # Telegram cleanup cannot undo a decision or restart its external action.
            try:
                await bot.api(
                    "editMessageReplyMarkup",
                    {
                        "chat_id": row["chat_id"],
                        "message_id": row["message_id"],
                        "reply_markup": {"inline_keyboard": []},
                    },
                )
            except ServiceError:
                pass
            continue
        bot.db.execute(
            "DELETE FROM telegram_approval_messages WHERE chat_id=? AND message_id=?",
            (row["chat_id"], row["message_id"]),
        )
        removed.add(reference)
