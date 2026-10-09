"""Installed `theos` command and local application lifecycle."""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path
from uuid import uuid4


def build_parser():
    parser = argparse.ArgumentParser(prog="theos", description="Chat with Theos in your terminal.")
    parser.add_argument("--config", type=Path, help="path to an AGENT_ .env file")
    parser.add_argument("--data-dir", type=Path, help="override the application data directory")
    parser.add_argument("--owner", help="standalone local profile name")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--server", help="deployment URL, including a Tailscale or tunnel address")
    mode.add_argument("--local", action="store_true", help="use the standalone runtime")
    parser.add_argument(
        "--token-file", type=Path, help="file containing the deployment browser token"
    )
    parser.add_argument("--session", help="open or create a named terminal session")
    parser.add_argument("--resume", nargs="?", const="", help="choose a session or resume its ID")
    parser.add_argument("--prompt", help="submit a prompt after startup")
    parser.add_argument("--image", action="append", default=[], type=Path, help="attach an image")
    return parser


def load_settings(args):
    from theos.settings import ClientSettings, Settings

    config = args.config
    if config is not None and not config.is_file():
        raise ValueError("The configuration file does not exist.")
    if config is None:
        source_root = Path(__file__).resolve().parents[4]
        candidates = [Path.cwd() / ".env"]
        if (source_root / "pyproject.toml").is_file():
            candidates.append(source_root / ".env")
        candidates.append(Path.home() / ".config/theos/.env")
        config = next((path for path in candidates if path.is_file()), None)
    client = ClientSettings(_env_file=config)
    if not args.local and (args.server is not None or client.server_url):
        return client
    settings = Settings(_env_file=config)
    if args.data_dir:
        settings.data_dir = args.data_dir.resolve()
    elif "data_dir" not in settings.model_fields_set:
        settings.data_dir = Path.home() / ".theos"
    elif not settings.data_dir.is_absolute():
        settings.data_dir = (
            (config.parent if config else Path.cwd()) / settings.data_dir
        ).resolve()
    return settings


async def run(args):
    # Import optional packages only after parsing so installed help remains available.
    from harness import ImageInput
    from renderer.tui import TEXTUAL_AVAILABLE

    from .app import TheosTui

    if not TEXTUAL_AVAILABLE:
        raise RuntimeError(
            "Install `theos[client]` for remote use or `theos[terminal]` for standalone use."
        )
    settings = load_settings(args)
    remote_url = args.server if args.server is not None else settings.server_url
    if not args.local and (args.server is not None or remote_url):
        return await run_remote(args, settings, remote_url)
    if args.token_file:
        raise ValueError("Use --token-file with --server or AGENT_SERVER_URL.")
    owner = args.owner if args.owner is not None else getpass.getuser()
    if not owner.strip() or ":" in owner:
        raise ValueError("Use a nonempty local profile name without a colon.")
    from theos.operations.logging import configure_logging
    from theos.runtime import Runtime
    from theos.runtime.scheduler import Scheduler
    from theos.storage.database import Database

    from .session import TerminalSession

    # 1. Validate configuration and images before opening durable state.
    images = [
        ImageInput.from_path(path, max_bytes=settings.max_upload_bytes) for path in args.image
    ]
    db = Database(settings.data_dir)
    runtime = None
    scheduler = None
    task = None
    handler = None
    try:
        # 2. Bind the local profile and conversation to the application runtime.
        handler = configure_logging(settings.data_dir / "logs")
        runtime = Runtime(settings, db)
        session = TerminalSession(runtime, "terminal:" + owner.strip())
        session_id = args.resume or args.session
        if args.resume:
            session._session(session_id)
        elif session_id:
            if session_id in session.sessions():
                session._session(session_id)
            else:
                session.create_session(session_id)
        else:
            session_id = uuid4().hex
            session.create_session(session_id)
        if (args.prompt is not None or images) and session.pending_interactions(session_id):
            raise ValueError(
                "Resume this session without a prompt to answer its pending approvals."
            )
        # 3. Run one scheduler alongside the interactive UI.
        scheduler = Scheduler(runtime)
        task = asyncio.create_task(scheduler.run())
        app = TheosTui(
            session,
            session_id=session_id,
            title=settings.name,
            initial_prompt=args.prompt,
            initial_images=images,
            open_session_picker=args.resume == "",
        )
        await app.run_async()
    finally:
        # 4. Stop scheduled work and live turns before releasing the process lock.
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if scheduler is not None:
            await scheduler.close()
        if runtime is not None:
            await runtime.close()
        db.close()
        if handler is not None:
            handler.close()


async def run_remote(args, settings, url):
    from harness import ImageInput

    from .app import TheosTui
    from .remote import RemoteSession

    if args.data_dir is not None or args.owner is not None:
        raise ValueError(
            "Remote mode uses the deployment's storage and authenticated user. Omit --data-dir and --owner."
        )
    token = (
        args.token_file.read_text().strip()
        if args.token_file is not None
        else settings.server_token.get_secret_value()
    )
    if not token:
        if not sys.stdin.isatty():
            raise ValueError("Set AGENT_SERVER_TOKEN or use --token-file for the deployment token.")
        token = getpass.getpass("Deployment browser token: ")
    session = RemoteSession(url, token)
    try:
        # Authenticate before opening the UI. Never fall back to local state on failure.
        await session.connect()
        images = [
            ImageInput.from_path(path, max_bytes=session.info["max_upload_bytes"])
            for path in args.image
        ]
        sessions = await session.sessions()
        session_id = args.resume or args.session
        picker = args.resume == "" or (session_id is None and args.prompt is None and not images)
        if session_id:
            if session_id in sessions or args.resume:
                await session.snapshot(session_id)
            else:
                await session.create_session(session_id)
        elif sessions:
            session_id = sessions[0]
        else:
            session_id = uuid4().hex
            await session.create_session(session_id)
            picker = False
        if (args.prompt is not None or images) and await session.pending_interactions(session_id):
            raise ValueError(
                "Resume this conversation without a prompt to answer its pending approvals."
            )
        app = TheosTui(
            session,
            session_id=session_id,
            title=session.info["name"],
            initial_prompt=args.prompt,
            initial_images=images,
            open_session_picker=picker,
        )
        await app.run_async()
    finally:
        # Closing the client leaves server-owned work and scheduled delivery running.
        await session.close()


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.session is not None and args.resume is not None:
        parser.error("Use either --session or --resume.")
    try:
        asyncio.run(run(args))
    except ImportError:
        parser.exit(
            2, "Install `theos[client]` for remote use or `theos[terminal]` for standalone use.\n"
        )
    except (ValueError, LookupError, RuntimeError, OSError) as error:
        parser.exit(2, f"theos: {error}\n")
    except KeyboardInterrupt:
        pass
