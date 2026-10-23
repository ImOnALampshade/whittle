# SPDX-License-Identifier: GPL-3.0-or-later
"""Whittle: sketch-driven modeling with a Claude agent inside Blender.

This module stays free of bpy at import time so the agent process can run
`python -m whittle.agent` with the same package.
"""

__version__ = "0.1.0"


def register():
    from . import addon

    addon.register()


def unregister():
    from . import addon

    addon.unregister()
