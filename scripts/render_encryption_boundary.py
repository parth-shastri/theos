"""Draw the proposed history decryption boundary without changing runtime diagrams."""

import json

from redraw_framework import BLUE, GREEN, OUT, PURPLE, TEAL, YELLOW, Scene


def encryption_boundary():
    scene = Scene("theos-encryption-proposal", 1200, 900)
    scene.title(
        "How Theos would read encrypted history",
        "Proposal only | Encryption protects stored content, not the running VPS",
    )
    # 1. Separate the device, operator-controlled VPS, and model service.
    scene.shape("device-zone", "rectangle", 25, 135, 310, 445, BLUE)
    scene.text("device-heading", 180, 150, "USER DEVICE", 23, centered=True)
    scene.shape("vps-zone", "rectangle", 465, 135, 430, 445, PURPLE)
    scene.text("vps-heading", 680, 150, "YOUR VPS", 23, centered=True)
    scene.shape("model-zone", "rectangle", 940, 135, 235, 445, YELLOW)
    scene.text("model-heading", 1057, 150, "MODEL PROVIDER", 23, centered=True)
    scene.node(
        "unlock",
        "rectangle",
        45,
        195,
        270,
        135,
        "Password stays here\nUnwrap the data key\nSeparate login token",
        "#ffffff",
        23,
    )
    scene.edge("grant", [(315, 235), (500, 235)], color="#2563eb")
    scene.text("grant-label", 346, 177, "1. Data key\nover HTTPS", 22, color="#2563eb")
    scene.node(
        "runtime",
        "rectangle",
        500,
        195,
        360,
        135,
        "RUNTIME MEMORY\nData key + readable history\nDecrypt for each turn",
        "#ffffff",
        23,
    )
    scene.node(
        "message",
        "rectangle",
        45,
        400,
        270,
        125,
        "New chat message\nTelegram or web\nOne unlock per session",
        "#ffffff",
        23,
    )
    scene.edge("incoming", [(315, 450), (390, 450), (390, 295), (500, 295)])
    scene.text("incoming-label", 340, 365, "2. New\nmessage", 22)
    # 2. Only ciphertext crosses the database boundary.
    scene.node(
        "storage",
        "rectangle",
        500,
        425,
        360,
        120,
        "DATABASE + BACKUPS\nEncrypted history + records\nWrapped key, no plaintext key",
        TEAL,
        23,
    )
    scene.edge("history-read", [(520, 425), (520, 330)], color="#15803d")
    scene.text(
        "history-read-label", 539, 350, "3. Read history\nDecrypt in RAM", 20, color="#15803d"
    )
    scene.edge("history-write", [(842, 330), (842, 425)], color="#15803d")
    scene.text("history-write-label", 720, 350, "5. Encrypt\nSave to DB", 20, color="#15803d")
    scene.edge("model-context", [(860, 255), (1057, 255), (1057, 280)])
    scene.text("context-label", 871, 206, "4. Context", 19)
    scene.node(
        "model",
        "rectangle",
        965,
        280,
        185,
        170,
        "Selected context\n+ new message\nReadable here",
        "#ffffff",
        20,
    )
    scene.text(
        "vps-warning", 680, 551, "VPS control can expose RAM", 21, color="#b91c1c", centered=True
    )
    scene.text(
        "transport-note",
        1057,
        479,
        "Encrypted in transit.\nReadable on arrival.",
        21,
        centered=True,
    )
    scene.text(
        "repeat-note",
        600,
        604,
        "Repeat steps 2-5 for every turn while the data key is available.",
        25,
        centered=True,
    )
    # 3. Make the continuity and privacy tradeoff explicit.
    scene.node(
        "user-held",
        "rectangle",
        40,
        659,
        540,
        155,
        "USER PASSWORD ONLY\nExpiry or restart needs another grant.\nA trusted device can restore access\nwhen it is online.",
        BLUE,
        22,
    )
    scene.node(
        "automatic",
        "rectangle",
        620,
        659,
        540,
        155,
        "AUTOMATIC RESTORATION\nA key service restores access on restart.\nThe runtime has ongoing decryption access.",
        GREEN,
        22,
    )
    scene.text(
        "accounting-note",
        600,
        841,
        "Usage totals stay readable. Old history stays encrypted even when the runtime loses its key.",
        22,
        centered=True,
    )
    return scene


def main():
    scene = encryption_boundary()
    scene.save()
    path = OUT / "theos-encryption-proposal.elements.json"
    elements = json.loads(path.read_text())
    for element in elements:
        if element["type"] == "cameraUpdate":
            element.update(x=0, y=0, width=1200, height=900)
    path.write_text(json.dumps(elements, indent=2) + "\n")


if __name__ == "__main__":
    main()
