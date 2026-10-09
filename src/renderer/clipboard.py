"""Read an image from the operating-system clipboard."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from harness import ImageInput


class ClipboardImageError(RuntimeError):
    """Raised when the clipboard does not contain a readable image."""


async def read_clipboard_image() -> ImageInput:
    """Return the current clipboard image as a durable PNG input."""
    return await asyncio.to_thread(_read_clipboard_image)


def _read_clipboard_image() -> ImageInput:
    if sys.platform == "darwin":
        data, filename = _read_macos_clipboard()
    elif sys.platform.startswith("linux"):
        data = _read_linux_clipboard()
        filename = "clipboard.png"
    elif sys.platform == "win32":
        data = _read_windows_clipboard()
        filename = "clipboard.png"
    else:
        raise ClipboardImageError(f"image clipboard is not supported on {sys.platform}")
    return ImageInput.from_bytes(data, media_type="image/png", filename=filename)


def _run(command: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise ClipboardImageError(f"clipboard helper failed: {error}") from error


def _read_macos_clipboard() -> tuple[bytes, str]:
    source_script = r"""
ObjC.import('AppKit');
function run() {
    const board = $.NSPasteboard.generalPasteboard;

    // Finder publishes the original item through one or both of these types.
    // Read them before public.png/public.tiff, which may only be a file icon.
    const fileURL = board.stringForType('public.file-url');
    if (fileURL) {
        return ObjC.unwrap(fileURL);
    }
    const filenames = board.propertyListForType('NSFilenamesPboardType');
    if (filenames && filenames.count > 0) {
        return ObjC.unwrap(filenames.objectAtIndex(0));
    }
    return '';
}
"""
    alias_script = 'try\nPOSIX path of (the clipboard as alias)\non error\nreturn ""\nend try'
    pasteboard_script = r"""
ObjC.import('AppKit');
function run(argv) {
    const board = $.NSPasteboard.generalPasteboard;
    const png = board.dataForType($.NSPasteboardTypePNG);
    if (png && png.length > 0) {
        png.writeToFileAtomically($(argv[0]), true);
        return 'png';
    }
    const tiff = board.dataForType($.NSPasteboardTypeTIFF);
    if (tiff && tiff.length > 0) {
        tiff.writeToFileAtomically($(argv[1]), true);
        return 'tiff';
    }
    return '';
}
"""
    with tempfile.TemporaryDirectory(prefix="harness-clipboard-") as directory:
        output = Path(directory) / "clipboard.png"
        tiff_output = Path(directory) / "clipboard.tiff"

        # A copied Finder/Photos file may expose only a preview as PNG. Prefer
        # its native pasteboard file URL so HEIC and other source formats are
        # converted from the actual file rather than from a Quick Look icon.
        source_results = (
            _run(["osascript", "-l", "JavaScript", "-e", source_script]),
            _run(["osascript", "-e", alias_script]),
        )
        for source_result in source_results:
            if source_result.returncode != 0:
                continue
            source_text = source_result.stdout.decode("utf-8", errors="replace").strip()
            source = _macos_source_path(source_text)
            if source is not None and source.is_file() and _convert_with_sips(source, output):
                return output.read_bytes(), f"{source.stem}.png"

        result = _run(
            [
                "osascript",
                "-l",
                "JavaScript",
                "-e",
                pasteboard_script,
                str(output),
                str(tiff_output),
            ]
        )
        kind = result.stdout.decode("utf-8", errors="replace").strip()
        if kind == "png" and output.is_file() and output.stat().st_size:
            return output.read_bytes(), "clipboard.png"
        if kind == "tiff" and tiff_output.is_file() and _convert_with_sips(tiff_output, output):
            return output.read_bytes(), "clipboard.png"

        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ClipboardImageError(detail or "the clipboard does not contain image pixels")


def _macos_source_path(value: str) -> Path | None:
    """Decode a Finder pasteboard file reference without accepting web URLs."""
    candidate = value.strip().splitlines()[0] if value.strip() else ""
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme == "file" and parsed.hostname in (None, "", "localhost"):
        return Path(unquote(parsed.path))
    if not parsed.scheme and candidate.startswith("/"):
        return Path(candidate)
    return None


def _convert_with_sips(source: Path, output: Path) -> bool:
    result = _run(["sips", "-s", "format", "png", str(source), "--out", str(output)])
    return result.returncode == 0 and output.is_file() and output.stat().st_size > 0


def _read_linux_clipboard() -> bytes:
    if shutil.which("wl-paste"):
        result = _run(["wl-paste", "--no-newline", "--type", "image/png"])
    elif shutil.which("xclip"):
        result = _run(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"])
    else:
        raise ClipboardImageError("install wl-clipboard or xclip to paste clipboard images")
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ClipboardImageError(detail or "the clipboard does not contain a PNG image")
    return result.stdout


def _read_windows_clipboard() -> bytes:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$image = [System.Windows.Forms.Clipboard]::GetImage(); "
        "if ($null -eq $image) { exit 2 }; "
        "$image.Save($args[0], [System.Drawing.Imaging.ImageFormat]::Png)"
    )
    with tempfile.TemporaryDirectory(prefix="harness-clipboard-") as directory:
        output = Path(directory) / "clipboard.png"
        result = _run(["powershell", "-NoProfile", "-Command", script, str(output)])
        if result.returncode != 0 or not output.is_file() or not output.stat().st_size:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ClipboardImageError(detail or "the clipboard does not contain an image")
        return output.read_bytes()


__all__ = ["ClipboardImageError", "read_clipboard_image"]
