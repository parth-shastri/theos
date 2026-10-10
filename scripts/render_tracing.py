"""Save the tracing diagram with consistent native and MCP text positions."""

import json

from redraw_framework import BLUE, EDGE, GREEN, INK, OUT, PURPLE, TEAL, YELLOW, Scene


class TracingScene(Scene):
    """Position each text line explicitly to avoid MCP bound-text offsets."""

    def node(self, ident, kind, x, y, w, h, label, fill=BLUE, size=24):
        self.shape(ident, kind, x, y, w, h, fill)
        self.elements[-1]["groupIds"] = [ident + "-group"]
        lines = label.split("\n")
        for index, line in enumerate(lines):
            width, _ = self.measure(line, size)
            assert width < w - 24, (ident, line)
            self.text(
                f"{ident}-line-{index}",
                x + (w - width) / 2,
                y + (h - len(lines) * size * 1.25) / 2 + index * size * 1.25,
                line,
                size,
            )
            self.elements[-1]["groupIds"] = [ident + "-group"]


def main():
    scene = TracingScene("theos-tracing", 1200, 1000)
    scene.title(
        "Theos / conversations and traces", "One conversation ID groups separate turn waterfalls"
    )
    scene.shape("conversation", "rectangle", 40, 145, 540, 230, "transparent", EDGE, True)
    scene.text("conversation-label", 70, 168, "Conversation / existing session ID", 25, INK)
    scene.node("turn-one", "rectangle", 65, 245, 220, 95, "Turn 1\nTrace A", PURPLE, 25)
    scene.node("turn-two", "rectangle", 335, 245, 220, 95, "Turn 2\nTrace B", PURPLE, 25)
    scene.text("grouping", 73, 207, "Grouping only / each turn has its own root", 20)
    scene.edge("models", [(115, 340), (115, 420)])
    scene.node("model", "rectangle", 40, 420, 220, 95, "Model calls\nMessages + timing", BLUE, 21)
    scene.edge("tools", [(245, 340), (385, 390), (385, 420)])
    scene.node("tool", "rectangle", 285, 420, 270, 95, "Tool calls\nArguments + results", GREEN, 23)
    scene.edge("delegate-tool", [(420, 515), (420, 570)])
    scene.node(
        "delegate", "rectangle", 285, 570, 270, 100, "delegate_tasks\nNamed assignments", GREEN, 23
    )
    scene.edge("child-one", [(320, 670), (150, 700), (150, 745)])
    scene.node(
        "research-one", "rectangle", 40, 745, 220, 105, "Named agent A\nModel + tools", PURPLE, 23
    )
    scene.edge("child-two", [(470, 670), (470, 745)])
    scene.node(
        "research-two", "rectangle", 285, 745, 270, 105, "Named agent B\nModel + tools", PURPLE, 23
    )
    scene.text("parallel", 65, 880, "Each turn owns its parallel delegate branches.", 21)
    scene.edge("export", [(555, 290), (740, 290)])
    scene.text("export-label", 586, 255, "Both traces", 20)
    scene.node(
        "batch",
        "rectangle",
        740,
        245,
        410,
        95,
        "OTel SDK / background export\nQueue limit: 2,048 spans",
        BLUE,
        23,
    )
    scene.edge("otlp", [(945, 340), (945, 420)])
    scene.text("protocol", 975, 360, "OTLP/HTTP", 21)
    scene.node(
        "jaeger",
        "rectangle",
        740,
        420,
        410,
        95,
        "Jaeger v2 / turn waterfall\nFilter by conversation ID",
        TEAL,
        23,
    )
    scene.edge("store", [(945, 515), (945, 570)])
    scene.node(
        "badger",
        "rectangle",
        740,
        570,
        410,
        100,
        "Badger / seven-day expiry\nRetains traces across restarts",
        TEAL,
        23,
    )
    scene.node(
        "limits",
        "rectangle",
        650,
        745,
        500,
        105,
        "Jaeger: 512 MB container limit\nMemory guard + bounded batches\nFile and container logs rotate",
        YELLOW,
        22,
    )
    scene.node(
        "privacy",
        "rectangle",
        650,
        880,
        500,
        80,
        "Opt-in content: 8 KB/field, 32 KB/span\nExport failures do not fail turns",
        YELLOW,
        22,
    )
    scene.save()
    path = OUT / "theos-tracing.elements.json"
    elements = json.loads(path.read_text())
    for element in elements:
        if element["type"] == "cameraUpdate":
            element.update(x=0, y=0, width=1200, height=1000)
    path.write_text(json.dumps(elements, indent=2) + "\n")


if __name__ == "__main__":
    main()
