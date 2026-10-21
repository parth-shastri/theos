"""Render the current service map with the shared Excalidraw preview renderer."""

import json

from redraw_framework import BLUE, GREEN, OUT, PURPLE, TEAL, YELLOW, Scene


def service_map():
    """Show the implemented boundaries without changing the original framework."""
    scene = Scene("theos-services", 1200, 900)
    scene.title(
        "Theos / code and service boundaries",
        "Current implementation | Read each service in its own directory",
    )
    scene.node("web", "rectangle", 40, 145, 305, 110, "Next.js frontend\nweb/", BLUE, 27)
    scene.edge("frontend-api", [(345, 200), (435, 200)])
    scene.text("frontend-auth", 65, 268, "Private API + sessions", 20)
    scene.node(
        "interfaces",
        "rectangle",
        435,
        145,
        330,
        110,
        "FastAPI + transports\nsrc/theos/transports/",
        BLUE,
        24,
    )
    scene.edge("input", [(600, 255), (600, 325)])
    scene.node(
        "runtime",
        "rectangle",
        435,
        325,
        330,
        115,
        "Runtime\nTurns + approvals\nDurable checkpoints",
        PURPLE,
        25,
    )
    scene.edge("model", [(765, 382), (850, 382)])
    scene.node(
        "harness", "rectangle", 850, 325, 305, 115, "Owned harness\nModel + tool loop", BLUE, 27
    )
    scene.edge("durable", [(435, 382), (345, 382)])
    scene.node("storage", "rectangle", 40, 325, 305, 115, "SQLite + migrations\nstorage/", TEAL, 27)
    scene.edge("tools", [(1002, 440), (1002, 612), (765, 612)])
    scene.text("tools-caption", 1040, 482, "Call tools", 25)
    scene.node(
        "services",
        "rectangle",
        435,
        530,
        330,
        165,
        "Service tools + clients\nPersonal records, memory\nFiles, voice, accounts\nSearch, weather, sandbox",
        GREEN,
        24,
    )
    scene.edge("schedule-store", [(192, 530), (192, 440)])
    scene.node(
        "scheduler",
        "rectangle",
        40,
        530,
        305,
        165,
        "One scheduler\nReminder delivery\nHealth imports + exports\nruntime/scheduler.py",
        YELLOW,
        23,
    )
    scene.edge("schedule-jobs", [(345, 612), (435, 612)])
    scene.edge("remote", [(600, 695), (600, 757)])
    scene.node(
        "external",
        "rectangle",
        435,
        757,
        330,
        100,
        "External services\nConfigured endpoints",
        TEAL,
        26,
    )
    scene.text(
        "ownership-note",
        43,
        775,
        "Use the authenticated owner.\nReview uncertain writes\nbefore another attempt.",
        22,
    )
    return scene


def main():
    """Save matching editable source, MCP input, PNG, and SVG files."""
    scene = service_map()
    scene.save()
    # Use an exact 4:3 viewport for the MCP rendering.
    path = OUT / "theos-services.elements.json"
    elements = json.loads(path.read_text())
    for element in elements:
        if element["type"] == "cameraUpdate":
            element.update(x=0, y=0, width=1200, height=900)
    path.write_text(json.dumps(elements, indent=2) + "\n")


if __name__ == "__main__":
    main()
