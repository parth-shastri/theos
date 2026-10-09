"""Simple in-memory and JSONL conversation stores."""

from __future__ import annotations

import json
import copy
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from harness.debug import log_detail
from harness.types import Message, message_from_dict, message_to_dict


@runtime_checkable
class Store(Protocol):
    """Anything that can load and save one history under a key."""

    async def load(self, key: str) -> list[Message] | None: ...

    async def save(self, key: str, history: Sequence[Message]) -> None: ...


class MemoryStore:
    """A store that keeps histories in a dict. Useful for tests and demos."""

    def __init__(self) -> None:
        self._histories: dict[str, list[Message]] = {}
        self._states: dict[str, dict] = {}

    async def load(self, key: str) -> list[Message] | None:
        history = self._histories.get(key)
        loaded = list(history) if history is not None else None
        log_detail("memory store load key=%s result=%r", key, loaded)
        return loaded

    async def save(self, key: str, history: Sequence[Message]) -> None:
        log_detail("memory store save key=%s history=%r", key, history)
        self._histories[key] = list(history)

    async def keys(self) -> Sequence[str]:
        """Return the saved conversation keys in stable order."""
        return tuple(sorted(self._histories))


    async def load_state(self, key: str) -> dict:
        """Read session metadata and context memory, separate from model messages."""
        return copy.deepcopy(self._states.get(key, {}))

    async def save_state(self, key: str, state: dict) -> None:
        self._states[key] = copy.deepcopy(state)


class JsonlStore:
    """Store each conversation as a JSONL file."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.jsonl"

    async def load(self, key: str) -> list[Message] | None:
        path = self._path(key)
        log_detail("jsonl store load key=%s path=%s", key, path)
        if not path.exists():
            log_detail("jsonl store load missing key=%s", key)
            return None
        text = path.read_text(encoding="utf-8")
        loaded = [message_from_dict(json.loads(line)) for line in text.splitlines() if line.strip()]
        log_detail("jsonl store load complete key=%s history=%r", key, loaded)
        return loaded

    async def save(self, key: str, history: Sequence[Message]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        log_detail("jsonl store save key=%s path=%s history=%r", key, path, history)
        temporary = path.with_name(f"{path.name}.tmp")
        lines = "".join(json.dumps(message_to_dict(m)) + "\n" for m in history)
        temporary.write_text(lines, encoding="utf-8")
        os.replace(temporary, path)
        log_detail("jsonl store save complete key=%s path=%s bytes=%d", key, path, len(lines))

    async def keys(self) -> Sequence[str]:
        """List conversation keys stored as JSONL files."""
        if not self.directory.exists():
            return ()
        return tuple(sorted(path.stem for path in self.directory.glob("*.jsonl")))


    async def load_state(self, key: str) -> dict:
        """Read optional session state. Existing JSONL histories need no migration."""
        path = self._path(key).with_suffix(".state.json")
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            return {}
        return value if isinstance(value, dict) else {}

    async def save_state(self, key: str, state: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key).with_suffix(".state.json")
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
