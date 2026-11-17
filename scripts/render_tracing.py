"""Render the current Theos logs and trace destinations."""

import json

from redraw_framework import BLUE, EDGE, GREEN, OUT, PURPLE, TEAL, YELLOW, Scene


def main():
    scene = Scene("theos-tracing", 1600, 1000)
    scene.title(
        "Theos / observability paths",
        "Logs and GenAI traces use separate private services on the Mac mini",
    )

    scene.node(
        "theos-runtime",
        "rectangle",
        70,
        330,
        290,
        135,
        "Theos runtime\nPi + local process",
        PURPLE,
        25,
    )

    scene.node(
        "application-log",
        "rectangle",
        455,
        180,
        310,
        135,
        "Rotating JSON log\nfirst_model_call\nturn_profile",
        BLUE,
        22,
    )
    scene.node(
        "filelog-collectors",
        "rectangle",
        840,
        180,
        310,
        135,
        "Filelog collectors\nPi + local LaunchAgent",
        GREEN,
        23,
    )
    scene.node(
        "openobserve",
        "rectangle",
        1230,
        180,
        320,
        135,
        "OpenObserve 1.1.2\nSearchable service logs\nSeven-day retention",
        TEAL,
        22,
    )

    scene.edge("runtime-log", [(360, 365), (405, 365), (405, 248), (455, 248)])
    scene.text("log-label", 378, 285, "JSON events", 18, EDGE)
    scene.edge("log-collector", [(765, 248), (840, 248)])
    scene.edge("collector-openobserve", [(1150, 248), (1230, 248)])

    scene.node(
        "otel-exporter",
        "rectangle",
        455,
        550,
        310,
        135,
        "OTel SDK exporter\nOne trace per turn\nOTLP/HTTP",
        BLUE,
        22,
    )
    scene.node(
        "langfuse",
        "rectangle",
        1000,
        550,
        400,
        135,
        "Langfuse 4.80.0\nChat-style model + tool traces\nConversation sessions",
        TEAL,
        22,
    )
    scene.edge(
        "runtime-traces",
        [(360, 425), (405, 425), (405, 617), (455, 617)],
    )
    scene.text("trace-label", 382, 515, "OTel spans", 18, EDGE)
    scene.edge("export-langfuse", [(765, 617), (1000, 617)])

    scene.node(
        "privacy",
        "rectangle",
        455,
        755,
        945,
        95,
        "Local files stay intact. Trace content capture remains opt-in.",
        YELLOW,
        23,
    )
    scene.text(
        "collector-note",
        455,
        880,
        "Collectors keep offsets and retry queues on their source host.",
        20,
        EDGE,
    )
    scene.save()
    path = OUT / "theos-tracing.elements.json"
    elements = json.loads(path.read_text())
    for element in elements:
        if element["type"] == "cameraUpdate":
            element.update(x=0, y=0, width=1600, height=1200)
    path.write_text(json.dumps(elements, indent=2) + "\n")


if __name__ == "__main__":
    main()
