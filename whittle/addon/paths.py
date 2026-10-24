# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Whittle keeps its files and which Python runs the agent."""

import os
import tempfile
from pathlib import Path

import bpy

from .. import venv
from ..venv import VenvStatus, venv_python
from . import prefs

# The extension root package: "whittle" in tests, "bl_ext.<repo>.whittle" when installed.
PACKAGE = __package__.rpartition(".")[0]


def user_dir() -> Path:
    override = os.environ.get("WHITTLE_USER_DIR")
    if override:
        path = Path(override)
    elif PACKAGE.startswith("bl_ext."):
        path = Path(bpy.utils.extension_path_user(PACKAGE, create=True))
    else:
        path = Path(tempfile.gettempdir()) / "whittle-user"
    path.mkdir(parents=True, exist_ok=True)
    return path


def agent_python() -> Path | None:
    """First hit wins: env override, the development preference, then the
    private venv, which only counts once its setup was verified against the
    lock this extension ships."""
    for candidate in (os.environ.get("WHITTLE_AGENT_PYTHON"), prefs.get().agent_python):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    from . import setup

    folder = setup.venv_dir()
    if venv.status(folder, setup.lock_path()) == VenvStatus.READY:
        return venv_python(folder)
    return None


_PROBLEMS = {
    VenvStatus.STALE: "The agent environment was set up for an earlier version of Whittle: "
                      "reinstall it",
    VenvStatus.BROKEN: "The agent environment is incomplete or its Python is gone: reinstall it",
    VenvStatus.FOREIGN: "The agent environment folder holds something Whittle did not make: "
                        "remove it or choose another folder in the preferences",
}


def agent_python_problem() -> str | None:
    """Why the private venv cannot run the agent, when it exists but is not
    usable; None when it is missing or ready."""
    from . import setup

    return _PROBLEMS.get(venv.status(setup.venv_dir(), setup.lock_path()))


def package_parent() -> Path:
    """The folder to put on PYTHONPATH so `python -m whittle.agent` resolves."""
    return Path(__file__).resolve().parent.parent.parent


def agent_module() -> str:
    """The agent's module path as importable from package_parent()."""
    return f"{Path(__file__).resolve().parent.parent.name}.agent"


def blend_path() -> Path | None:
    """The open file, None while it was never saved."""
    filepath = bpy.data.filepath
    return Path(filepath) if filepath else None


def cache_dir() -> Path:
    """Where every file's chats cache lives (caches.py): never beside a .blend."""
    return user_dir() / "cache"


def is_recovery_file(path: Path) -> bool:
    """Whether Blender opened one of its own recovery files: an autosave or
    the last session's quit.blend, in its temporary folder."""
    name = Path(path).name
    return name == "quit.blend" or name.endswith("_autosave.blend")


def claude_config_dir() -> Path:
    """The bundled CLI's configuration folder (its CLAUDE_CONFIG_DIR): its
    transcripts and state live here, never in the user's own Claude folder,
    so the CLI finds no login, settings, hooks or MCP servers but Whittle's."""
    path = user_dir() / "claude"
    path.mkdir(parents=True, exist_ok=True)
    return path


def agents_dir() -> Path:
    """Where a Windows agent is recorded while it runs (platforms.note_agent),
    so an agent starting in any Blender knows which resume folders may be in
    use. Not made until one is recorded."""
    return user_dir() / "agents"


def logs_dir() -> Path:
    path = user_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
