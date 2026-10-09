from __future__ import annotations

import subprocess
from pathlib import Path

from renderer import clipboard


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44"
    "ae426082"
)


def test_macos_clipboard_prefers_original_file_over_preview(monkeypatch, tmp_path) -> None:
    source = tmp_path / "meal.heic"
    source.write_bytes(b"original HEIC bytes")
    commands: list[list[str]] = []

    def run(command: list[str], *, timeout: int = 10):
        commands.append(command)
        if command[0] == "osascript":
            return subprocess.CompletedProcess(command, 0, f"{source}\n".encode(), b"")
        assert command[0] == "sips"
        output = command[command.index("--out") + 1]
        with open(output, "wb") as handle:
            handle.write(PNG_1X1)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(clipboard, "_run", run)

    data, filename = clipboard._read_macos_clipboard()
    assert data == PNG_1X1
    assert filename == "meal.png"
    sips = next(command for command in commands if command[0] == "sips")
    assert str(source) in sips


def test_macos_clipboard_decodes_finder_file_url(monkeypatch, tmp_path) -> None:
    source = tmp_path / "meal photo.heic"
    source.write_bytes(b"original HEIC bytes")

    def run(command: list[str], *, timeout: int = 10):
        if command[:3] == ["osascript", "-l", "JavaScript"]:
            url = source.as_uri().replace("%20", "%20")
            return subprocess.CompletedProcess(command, 0, f"{url}\n".encode(), b"")
        if command[0] == "osascript":
            return subprocess.CompletedProcess(command, 0, b"", b"")
        output = Path(command[command.index("--out") + 1])
        output.write_bytes(PNG_1X1)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(clipboard, "_run", run)

    data, filename = clipboard._read_macos_clipboard()
    assert data == PNG_1X1
    assert filename == "meal photo.png"


def test_macos_source_path_rejects_non_file_urls() -> None:
    assert clipboard._macos_source_path("https://example.com/meal.png") is None
    assert clipboard._macos_source_path("file:///tmp/meal%20photo.heic") == Path(
        "/tmp/meal photo.heic"
    )
