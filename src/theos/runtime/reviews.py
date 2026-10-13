"""Readable approval fields, separate from the unchanged approval snapshot."""

import re
from decimal import Decimal, InvalidOperation, localcontext


def readable_name(name):
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name)).replace("_", " ")
    words = re.sub(r"\bid\b", "ID", words, flags=re.I)
    return words[:1].upper() + words[1:]


def tool_label(name):
    labels = {
        "gmail_send_draft": "Send Gmail draft",
        "sandbox_execute_code": "Run code in sandbox",
        "sandbox_run_command": "Run sandbox command",
        "web_search": "Search the web",
        "history_read": "Read saved evidence",
        "history_search": "Find saved evidence",
        "zepto_update_cart": "Update Zepto cart",
        "delete_custom_table": "Delete saved table",
    }
    return labels.get(name, readable_name(name))


def tool_icon(name):
    if name.startswith("zepto_"):
        return "🛒"
    if name.startswith("gmail_"):
        return "✉️"
    if "search" in name or "research" in name:
        return "🔎"
    if name.startswith("sandbox_"):
        return "🧰"
    if "file" in name or name.startswith("source_"):
        return "📄"
    if name.startswith("history_"):
        return "📚"
    return "⚙️"


def approval_review(tool, value):
    """Group readable action fields, retaining exact identifiers in technical details."""
    fields = []
    labels = {
        "name": "Product" if tool.startswith("zepto_") else "Name",
        "quantity": "Requested quantity",
        "packSize": "Pack size",
        "availableQuantity": "Available quantity",
        "isAd": "Promoted item",
        "mrp": "Maximum retail price",
        "price": "Price",
    }

    def walk(item, path=(), key="", price_unit=None):
        if isinstance(item, dict) and item:
            price_unit = (
                item.get("priceUnit")
                or item.get("price_unit")
                or item.get("currency")
                or price_unit
            )
            for name, child in item.items():
                walk(child, path if name == "arguments" else (*path, name), name, price_unit)
        elif isinstance(item, list) and item:
            for index, child in enumerate(item, 1):
                walk(child, (*path, str(index)), key, price_unit)
        else:
            field = approval_fields(item, (), key)[0]
            group_parts = list(path[:-1])
            field_name = path[-1] if path else key
            group = " / ".join(readable_name(part) for part in group_parts)
            if group_parts and group_parts[0] == "cartItems" and len(group_parts) > 1:
                group = "Cart item " + group_parts[1]
            technical = bool(re.search(r"(?:_id|Id|Ids|ID)$", field_name)) or field_name in {
                "deviceId",
                "id",
            }
            normalized = field_name.replace("_", "").lower()
            identifier_labels = {
                "deviceid": "Device ID",
                "productvariantid": "Product variant ID",
                "storeproductid": "Store product ID",
                "variantid": "Variant ID",
                "cartproductid": "Cart product ID",
            }
            technical = technical or normalized in identifier_labels
            label = labels.get(field_name, readable_name(field_name) or "Details")
            label = identifier_labels.get(normalized, label)
            field.update(label=label, group=group, technical=technical)
            if (
                tool == "zepto_update_cart"
                and group.startswith("Cart item ")
                and field_name in {"price", "mrp"}
                and not isinstance(item, bool)
            ):
                try:
                    amount = Decimal(str(item))
                    if amount.is_finite():
                        with localcontext() as decimal_context:
                            decimal_context.prec = max(28, len(amount.as_tuple().digits) + 4)
                            amount = amount.scaleb(-2)
                            display = "₹" + format(
                                amount, ".2f" if amount.as_tuple().exponent >= -2 else "f"
                            )
                        fields.append({**field, "label": label + " (paise)", "technical": True})
                        field["text"] = display
                except (InvalidOperation, ValueError):
                    pass
            elif tool.startswith("zepto_") and field_name in {"price", "mrp"}:
                field["hint"] = (
                    f"Declared currency/unit: {price_unit}. Values are unchanged."
                    if isinstance(price_unit, str)
                    else "Currency and price units were not supplied. Values are unchanged."
                )
            fields.append(field)

    walk(value)
    priority = {"Product": 0, "Name": 0, "Pack size": 1, "Requested quantity": 2}
    fields.sort(key=lambda f: (f["technical"], f["group"], priority.get(f["label"], 3)))
    merged = []
    for field in fields:
        match = next(
            (
                f
                for f in merged
                if f["group"] == field["group"]
                and f["technical"] == field["technical"]
                and f["kind"] == field["kind"]
                and f["text"] == field["text"]
            ),
            None,
        )
        if match:
            match["label"] += " / " + field["label"]
        else:
            merged.append(field)
    return merged


def approval_fields(value, path=(), key=""):
    """Keep every value, including empty containers and multiline strings."""
    fields = []
    if isinstance(value, dict) and value:
        for name, child in value.items():
            fields.extend(
                approval_fields(child, (*path, name.replace("_", " ").capitalize()), name)
            )
    elif isinstance(value, list) and value:
        for index, child in enumerate(value, 1):
            fields.extend(approval_fields(child, (*path, str(index)), key))
    else:
        text = (
            value
            if isinstance(value, str)
            else (
                "Yes"
                if value is True
                else "No"
                if value is False
                else "Not set"
                if value is None
                else "None"
                if value in ([], {})
                else str(value)
            )
        )
        kind = (
            "code"
            if key in {"code", "command", "script"}
            else ("markdown" if key in {"body", "content", "message", "description"} else "text")
        )
        fields.append(
            {"label": " / ".join(path) or "Details", "text": text or "(empty)", "kind": kind}
        )
    return fields
