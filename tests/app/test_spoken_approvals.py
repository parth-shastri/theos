"""Preserve complete approval details in spoken reviews."""

import json

from theos.services.spoken_approvals import spoken_prompt


def test_large_or_opaque_reviews_are_not_truncated_into_voice_grants():
    row = {
        "tool": "gmail_send_draft",
        "preview": json.dumps(
            {"to": "a@example.test", "body": "x" * 700, "sha256": "digest", "draft_id": "draft"}
        ),
    }
    assert spoken_prompt(row, "Theos") is None
    row = {"tool": "zepto_confirm_cart", "preview": json.dumps({"cart_id": "opaque"})}
    assert spoken_prompt(row, "Theos") is None


def test_short_plain_email_reads_full_contents_and_formatted_recipients():
    row = {
        "tool": "gmail_send_draft",
        "preview": json.dumps(
            {
                "to": "Ada <ada@example.test>",
                "subject": "Meeting",
                "body": "See you tomorrow.",
                "attachments": [],
                "draft_id": "private-draft",
                "sha256": "private-digest",
            }
        ),
    }
    prompt = spoken_prompt(row, "Theos")
    assert "Ada <ada@example.test>" in prompt and "See you tomorrow." in prompt
    assert "private-draft" not in prompt and "private-digest" not in prompt
    row["preview"] = json.dumps({"to": "ada@example.test", "body": "<p>HTML only</p>"})
    assert spoken_prompt(row, "Theos") is None
