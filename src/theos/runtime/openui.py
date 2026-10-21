"""Load OpenUI prompt artifacts generated from the browser component library."""

import json
from importlib.resources import files

OPENUI_FORMAT = "openui-lang"
_ARTIFACTS = files("theos.prompts").joinpath("openui")


def manifest():
    """Read the pinned component and renderer versions shipped with Theos."""
    return json.loads(_ARTIFACTS.joinpath("manifest.json").read_text(encoding="utf-8"))


def library_version():
    """Return the version marker used by stored browser responses."""
    return manifest()["library_version"]


def system_prompt():
    """Return OpenUI Lang and component instructions generated at build time."""
    return _ARTIFACTS.joinpath("system-prompt.md").read_text(encoding="utf-8").strip()
