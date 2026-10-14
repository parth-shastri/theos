"""Scoped context activity, tool status, and readable unchanged approval snapshots."""

import json
import time
from types import SimpleNamespace

import pytest

from harness.events import ContextCompaction
from theos.runtime.events import publish_event
from theos.runtime.reviews import approval_review
from theos.transports.telegram.formatting import format_approval, utf16_length
from theos.transports.telegram.polling import Telegram


def cart_arguments():
    return {
        "arguments": {
            "deviceId": "telegram",
            "cartItems": [
                {
                    "productVariantId": "variant-one",
                    "storeProductId": "store-one",
                    "quantity": 0,
                    "name": "Fresh Milk Pouch",
                    "label": "Fresh Milk Pouch",
                    "price": 3900,
                    "mrp": 3900,
                    "packSize": "1 pack (500 ml)",
                    "availableQuantity": 10,
                    "isAd": False,
                    "variantId": "variant-one",
                    "cartProductId": "variant-one",
                },
                {"productVariantId": "variant-two", "name": "Bread", "quantity": 2},
            ],
        }
    }


def test_cart_review_explains_items_and_preserves_every_value_without_mutating_arguments():
    original = cart_arguments()
    before = json.dumps(original)
    fields = approval_review("zepto_update_cart", original)
    assert fields[0]["group"] == "Cart item 1" and fields[0]["text"] == "Fresh Milk Pouch"
    assert "Product" in fields[0]["label"] and "Label" in fields[0]["label"]
    assert any(f["label"] == "Requested quantity" and f["text"] == "0" for f in fields)
    assert any(f["group"] == "Cart item 2" and f["text"] == "Bread" for f in fields)
    variants = [f for f in fields if f["text"] == "variant-one"]
    assert len(variants) == 1 and variants[0]["technical"]
    assert (
        "Product variant ID" in variants[0]["label"] and "Cart product ID" in variants[0]["label"]
    )
    assert all("Arguments /" not in f["label"] for f in fields)
    assert json.dumps(original) == before
    parts = format_approval("zepto_update_cart", fields)
    text = "".join(p["text"] for p in parts)
    assert text.index("Fresh Milk Pouch") < text.index("variant-one")
    assert "₹39.00" in text and "3900" in text and "(paise)" in text
    assert any(e["type"] == "expandable_blockquote" for p in parts for e in p["entities"])
    for part in parts:
        assert all(
            e["offset"] + e["length"] <= utf16_length(part["text"]) for e in part["entities"]
        )


@pytest.mark.parametrize("parent", [None, "delegate-call"])
def test_compaction_events_reach_clients_without_private_summary_content(runtime, parent):
    row = runtime.db.create_session("alice", "test", "none")
    output = []
    turn = SimpleNamespace(
        owner="alice", session_id=row["id"], raw_events=False, emit=output.append
    )
    status = publish_event(
        runtime,
        turn,
        ContextCompaction("started", 90000, parent_call_id=parent, compaction_id="compression-one"),
        "running",
    )
    assert status == "running" and output[0]["type"] == "compaction"
    assert output[0]["parent_call_id"] == parent
    assert output[0]["compaction_id"] == "compression-one"
    assert "summary" not in output[0] and "content" not in output[0]


async def test_telegram_updates_each_tool_and_compaction_in_place(runtime):
    bot, sent, edited, deleted = Telegram(runtime), [], [], []

    async def api(method, payload=None, files=None):
        if method == "sendMessage":
            sent.append(payload)
            return {"message_id": len(sent)}
        if method == "editMessageText":
            edited.append(payload)
        if method == "deleteMessage":
            deleted.append(payload["message_id"])
        return {}

    bot.api = api

    async def events():
        yield {"type": "compaction", "status": "started", "compaction_id": "one"}
        yield {"type": "compaction", "status": "progress", "compaction_id": "one"}
        yield {"type": "compaction", "status": "completed", "compaction_id": "one"}
        yield {"type": "tool", "name": "web_search", "call_id": "search", "status": "running"}
        yield {"type": "tool", "name": "web_search", "call_id": "search", "status": "completed"}
        yield {"type": "done", "status": "completed"}

    await bot.render(SimpleNamespace(events=events, owner="alice"), 123, 42)
    assert len(sent) == 4
    assert "🗂" in sent[1]["text"] and "Organizing" in sent[1]["text"]
    assert "🔎" in sent[2]["text"] and "Search the web" in sent[2]["text"]
    assert deleted == [2, 3]
    assert "1 tool call · Complete" in sent[-1]["text"]
    assert sent[1]["disable_notification"] and sent[2]["disable_notification"]
    assert all(p["message_thread_id"] == 42 for p in sent)


async def test_interrupted_compaction_does_not_leave_a_running_telegram_indicator(runtime):
    bot, deleted = Telegram(runtime), []

    async def api(method, payload=None, files=None):
        if method == "deleteMessage":
            deleted.append(payload["message_id"])
        return {"message_id": 1}

    bot.api = api

    async def events():
        yield {"type": "compaction", "status": "started", "compaction_id": "one"}
        yield {"type": "done", "status": "interrupted"}

    await bot.render(SimpleNamespace(events=events, owner="alice"), 123, 42)
    assert deleted == [1]


@pytest.mark.parametrize(
    "price,display", [(3900, "₹39.00"), (3901, "₹39.01"), (0, "₹0.00"), ("3900", "₹39.00")]
)
def test_cart_prices_are_rupees_only_in_the_display(price, display):
    arguments = cart_arguments()
    arguments["arguments"]["cartItems"][0].update(price=price, mrp=price)
    fields = approval_review("zepto_update_cart", arguments)
    prices = [f for f in fields if "Price" in f["label"]]
    assert any(f["text"] == display and not f["technical"] for f in prices)
    assert any(f["text"] == str(price) and f["technical"] for f in prices)
    assert arguments["arguments"]["cartItems"][0]["price"] == price
    other_tool = approval_review("other_cart", arguments)
    assert not any("₹" in f["text"] for f in other_tool)


async def test_pending_cart_snapshot_keeps_paise_and_ids(runtime):
    row = runtime.db.create_session("alice", "test", "default")
    arguments = json.dumps(cart_arguments())
    runtime.db.execute(
        "INSERT INTO approvals(id,session,call_id,tool,arguments,preview,created,expires) VALUES (?,?,?,?,?,?,?,?)",
        (
            "cart-review",
            row["id"],
            "call",
            "zepto_update_cart",
            arguments,
            arguments,
            time.time(),
            time.time() + 900,
        ),
    )
    assert not runtime.pending("alice", row["id"])
    item = runtime.db.one("SELECT * FROM approvals WHERE id='cart-review'")
    item["review"] = approval_review(item["tool"], json.loads(item["preview"]))
    assert item["arguments"] == item["preview"] == arguments
    assert any(f["text"] == "₹39.00" for f in item["review"])
    assert json.loads(item["arguments"])["arguments"]["cartItems"][0]["price"] == 3900
