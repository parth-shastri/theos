"""Render local durability and background checkpoint replication."""

from redraw_framework import BLUE, GREEN, PURPLE, TEAL, YELLOW
from render_tracing import TracingScene


def main():
    scene = TracingScene("theos-runtime-recovery", 1200, 900)
    scene.title(
        "Theos / latency and safe recovery",
        "Local durability precedes work. Remote replication follows in the background.",
    )
    scene.node(
        "turn", "rectangle", 40, 160, 270, 105, "Turn / queue wait\nSetup phase spans", PURPLE, 24
    )
    scene.edge("prepare", [(310, 210), (390, 210)])
    scene.node(
        "local",
        "rectangle",
        390,
        160,
        350,
        105,
        "SQLite + fsynced files\nDurable calls and results",
        TEAL,
        24,
    )
    scene.edge("request", [(565, 265), (565, 350)])
    scene.node(
        "provider",
        "rectangle",
        390,
        350,
        350,
        115,
        "Provider HTTP headers\nFirst chunk + full stream\nSafe error classifications",
        BLUE,
        22,
    )
    scene.edge("tool-result", [(390, 405), (175, 405)])
    scene.node(
        "tools",
        "rectangle",
        40,
        350,
        270,
        115,
        "Parallel Gmail reads\nOrdered writes\nStable call IDs",
        GREEN,
        22,
    )
    scene.edge("persist-results", [(175, 350), (175, 300), (390, 300), (390, 245)])
    scene.edge("replicate", [(740, 210), (850, 210)], dashed=True)
    scene.node(
        "worker",
        "rectangle",
        850,
        160,
        310,
        105,
        "One storage worker\nSQLite transfer journal",
        BLUE,
        23,
    )
    scene.edge("upload", [(1005, 265), (1005, 350)])
    scene.node(
        "r2",
        "rectangle",
        850,
        350,
        310,
        115,
        "R2 objects + snapshots\nReuse the connection\nRetry storage only",
        TEAL,
        22,
    )
    scene.edge("publish", [(1005, 465), (1005, 555)])
    scene.node(
        "pointer",
        "rectangle",
        850,
        555,
        310,
        110,
        "Publish latest pointer\nOnly after all referenced\nobjects are durable",
        GREEN,
        21,
    )
    scene.node(
        "resume",
        "rectangle",
        40,
        555,
        700,
        110,
        "Resume from saved results. Never repeat uncertain actions.\nRetry transient model streams only before any output.\nPreserve approvals, ownership, transcript and tool identities.",
        YELLOW,
        21,
    )
    scene.text("lag", 850, 705, "Remote recovery may lag.\nLocal recovery stays current.", 21)
    scene.text(
        "timing",
        60,
        760,
        "Measure queueing, setup, checkpoint persistence, HTTP headers and generation separately.",
        22,
    )
    scene.save()


if __name__ == "__main__":
    main()
