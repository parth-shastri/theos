"""Save the tracing diagram with traditional Excalidraw handwriting previews."""

import json

from redraw_framework import BLUE, GREEN, OUT, PURPLE, TEAL, YELLOW, Scene


def main():
    scene = Scene("theos-tracing", 1200, 900)
    scene.title("Theos / turn traces", "Implemented spans | Content-free OTLP/HTTP export")
    scene.node(
        "turn", "rectangle", 60, 160, 290, 110, "Turn root\nConversation + turn ID", PURPLE, 25
    )
    scene.edge("models", [(150, 270), (150, 345)])
    scene.node("model", "rectangle", 40, 345, 220, 95, "Model calls\nTokens + timing", BLUE, 23)
    scene.edge("tools", [(280, 270), (380, 320), (380, 345)])
    scene.node("tool", "rectangle", 280, 345, 235, 95, "Tool calls\nStatus + timing", GREEN, 23)
    scene.edge("delegate-tool", [(280, 440), (160, 495), (160, 520)])
    scene.node(
        "delegate", "rectangle", 45, 520, 270, 95, "delegate_tasks\nResearch delegates", GREEN, 24
    )
    scene.edge("child-one", [(115, 615), (115, 680)])
    scene.node(
        "research-one", "rectangle", 40, 680, 220, 125, "Research 1\nModel + tools", PURPLE, 23
    )
    scene.edge("child-two", [(265, 615), (385, 650), (385, 680)])
    scene.node(
        "research-two", "rectangle", 285, 680, 220, 125, "Research 2\nModel + tools", PURPLE, 23
    )
    scene.text("parallel", 70, 830, "Parallel branches share the turn trace.", 22)
    scene.edge("export", [(350, 215), (610, 215)])
    scene.node("batch", "rectangle", 610, 160, 250, 110, "OTel SDK\nBackground batches", BLUE, 25)
    scene.edge("otlp", [(735, 270), (735, 345)])
    scene.text("protocol", 755, 291, "OTLP/HTTP", 22)
    scene.node("jaeger", "rectangle", 610, 345, 250, 95, "Jaeger v2\nTrace waterfall", TEAL, 25)
    scene.edge("store", [(860, 392), (935, 392)])
    scene.node("badger", "rectangle", 935, 345, 230, 95, "Badger volume\n7-day retention", TEAL, 23)
    scene.node(
        "local",
        "rectangle",
        610,
        520,
        555,
        95,
        "SQLite events and usage remain local.\nTracing is optional.",
        YELLOW,
        25,
    )
    scene.node(
        "privacy",
        "rectangle",
        610,
        680,
        555,
        125,
        "No prompts, replies, arguments or results.\nNo owner IDs or exception payloads.\nBackend failures do not fail turns.",
        YELLOW,
        24,
    )
    scene.save()
    path = OUT / "theos-tracing.elements.json"
    elements = json.loads(path.read_text())
    for element in elements:
        if element["type"] == "cameraUpdate":
            element.update(x=0, y=0, width=1200, height=900)
    path.write_text(json.dumps(elements, indent=2) + "\n")


if __name__ == "__main__":
    main()
