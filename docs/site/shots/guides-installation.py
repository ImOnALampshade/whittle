# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing and updating: Blender's extension screens, and the agent
environment box in each state a user meets. No shot installs anything: a
finished setup is a marker over a link, and the download in progress is a
stand-in that only sleeps."""

import sys
from pathlib import Path

from tests.docshots.spec import Shot, preferences, window

# What a user sees for the default folder, not the run's own.
USER_VENV = "/home/you/.config/blender/5.2/extensions/.user/user_default/whittle/venv"
SHOWN_LOCK = "/home/you/.config/blender/5.2/extensions/user_default/whittle/requirements.lock"
# The Agent Environment box, six wheel steps down the Preferences.
BOX = (176, 241, 652, 120)
# The packages before the SDK in the lock, as pip reports each: its wheel's
# name after the version, and its size.
BEFORE_SDK = (("annotated-types", "annotated_types", "py3-none-any", "13 kB"),
              ("anyio", "anyio", "py3-none-any", "114 kB"), ("attrs", "attrs", "py3-none-any", "68 kB"),
              ("cffi", "cffi", "cp314-cp314-manylinux_2_17_x86_64", "220 kB"))


def install_dialog(stage):
    """Install from Disk's file browser, as its menu item opens it."""
    import bpy

    with bpy.context.temp_override(window=stage.window, screen=stage.window.screen):
        bpy.ops.extensions.package_install_files("INVOKE_DEFAULT")
    yield 1.0


def confirm(stage):
    """The confirmation names the folder, so it shows the default one's path;
    over the main window, as the Preferences' is too narrow for its line."""
    import bpy

    stage.preferences.venv_dir = USER_VENV
    with bpy.context.temp_override(window=stage.window, screen=stage.window.screen):
        bpy.ops.whittle.venv_install("INVOKE_DEFAULT")
    yield 1.0


def ready(stage):
    stage.agent_ready()
    yield 0.1


def earlier_version(stage):
    """A finished setup from a lock this extension no longer ships."""
    from whittle import venv
    from whittle.addon import setup

    stage.agent_ready()
    other = stage.work / "earlier.lock"
    other.write_text(f"{venv.SDK}==0.0.1 --hash=sha256:{'0' * 64}\n")
    venv.write_marker(setup.venv_dir(), other, sdk="0.0.1", base_python=Path(sys.executable))
    yield 0.1


def downloading(stage):
    """A setup partway through the big download: a stand-in step that sleeps
    (no timer drives it, so it stays as shot) with pip's lines in its log."""
    from whittle import venv
    from whittle.addon import setup

    lock = setup.lock_path()
    lines = lock.read_text(encoding="utf-8").splitlines()

    def collecting(name: str) -> str:
        number = next(i for i, line in enumerate(lines, 1) if line.startswith(f"{name}=="))
        return f"Collecting {name}=={venv.read_pins(lock)[name]} (from -r {SHOWN_LOCK} (line {number}))\n"

    stand_in = venv.VenvSetup([venv.Step("install", [sys.executable, "-c", "import time; time.sleep(45)"], 90.0)],
                              venv=setup.venv_dir(), lock=lock, log_path=stage.work / "stand-in.log",
                              base_python=Path(sys.executable))
    setup._current = stand_in
    stand_in.start()
    for name, wheel, tags, size in BEFORE_SDK:
        stand_in._write(collecting(name))
        stand_in._write(f"  Downloading {wheel}-{venv.read_pins(lock)[name]}-{tags}.whl ({size})\n")
    sdk = venv.read_pins(lock)[venv.SDK]
    stand_in._write(collecting(venv.SDK))
    stand_in._write(f"  Downloading claude_agent_sdk-{sdk}-py3-none-manylinux_2_17_x86_64.whl (114.1 MB)\n")
    stand_in._write("Progress 43100000 of 114100000\n")
    yield 0.2


SHOTS = [
    Shot("install-from-disk", "Install from Disk in the Get Extensions menu.",
         preferences("EXTENSIONS", menu="USERPREF_MT_extensions_settings")),
    Shot("install-options", "Enable on Install in Install from Disk's file browser.",
         window(of="FILE_BROWSER", crop=(820, 40, 240, 130)), setup=install_dialog),
    Shot("online-access", "Allow Online Access in the System section.", preferences("SYSTEM", crop=(168, 214, 672, 106))),
    Shot("environment-not-set-up", "The Agent Environment box before setup.", preferences(scroll=6, crop=BOX)),
    Shot("environment-confirm", "The confirmation before anything is downloaded.",
         window(crop=(345, 445, 910, 112)), setup=confirm),
    Shot("environment-downloading", "The Agent Environment box during the big download.",
         preferences(scroll=6, crop=(176, 241, 652, 286)), setup=downloading),
    Shot("environment-ready", "The Agent Environment box once set up.", preferences(scroll=6, crop=BOX), setup=ready),
    Shot("environment-earlier-version", "The box after an update that ships a different lock.",
         preferences(scroll=6, crop=BOX), setup=earlier_version),
    Shot("sidebar-set-up", "The sidebar's offer to set up.", scenario="setup_needed"),
    Shot("extension-row", "Whittle's row in Get Extensions.", preferences("EXTENSIONS", search="Whittle", crop=(160, 186, 680, 66))),
]
