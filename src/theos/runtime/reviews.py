"""Readable approval fields, separate from the unchanged approval snapshot."""


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
