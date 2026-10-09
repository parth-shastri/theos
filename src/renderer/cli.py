"""Command-line entry point for the framework-neutral harness TUI."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import os
from pathlib import Path
from typing import Any

from renderer import run_tui
from harness import ImageInput


def load_object(reference: str) -> Any:
    """Load ``module:attribute`` and return the referenced object."""
    module_name, separator, attribute_path = reference.partition(":")
    if not separator or not module_name or not attribute_path:
        raise ValueError("target must use module:attribute syntax")
    value: Any = importlib.import_module(module_name)
    for part in attribute_path.split("."):
        value = getattr(value, part)
    return value


async def _build(reference: str) -> Any:
    value = load_object(reference)
    is_session = all(
        hasattr(value, name)
        for name in ("stream", "respond", "steer", "history", "sessions", "create_session")
    )
    if callable(value) and not is_session:
        value = value()
    return await value if inspect.isawaitable(value) else value


async def run(args: argparse.Namespace) -> None:
    session = await _build(args.target)
    adapter = await _build(args.adapter) if args.adapter else None
    images = [ImageInput.from_path(path) for path in args.image]
    session_id = args.resume or args.session
    await run_tui(
        session,
        session_id=session_id,
        title=args.title,
        adapter=adapter,
        initial_prompt=args.prompt,
        initial_images=images,
        open_session_picker=args.resume == "",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness-cli",
        description="Run any streaming agent harness in the interactive terminal UI.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=os.getenv("HARNESS_CLI_APP"),
        help="Agent, InteractiveSession, or zero-argument factory as module:attribute",
    )
    parser.add_argument("--session", default="default", help="conversation session id")
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        help="choose an existing session, or resume the supplied session id",
    )
    parser.add_argument("--title", default="Harness", help="title shown in the TUI")
    parser.add_argument("--prompt", help="submit an initial prompt after startup")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        type=Path,
        help="attach an image to the initial prompt; repeat for multiple images",
    )
    parser.add_argument(
        "--adapter",
        help="optional event adapter instance or factory as module:attribute",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.target:
        parser.error("target is required (or set HARNESS_CLI_APP)")
    try:
        asyncio.run(run(args))
    except (AttributeError, ImportError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
