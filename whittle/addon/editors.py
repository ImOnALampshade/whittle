# SPDX-License-Identifier: GPL-3.0-or-later
"""Showing images and texts in editors from the sidebar: an editor already
open is reused, otherwise a 3D viewport is duplicated into a new window and
turned into one."""

import logging
from pathlib import Path

import bpy

log = logging.getLogger("whittle")


def find_area(wm, area_type: str):
    """(window, area) of the first area of that type in any window."""
    for window in (wm.windows if wm is not None else []):
        for area in window.screen.areas:
            if area.type == area_type:
                return window, area
    return None


def _open_area(context, area_type: str):
    if bpy.app.background:
        return None
    wm = context.window_manager
    found = find_area(wm, area_type)
    if found is not None:
        return found[1]
    window = context.window or (wm.windows[0] if wm.windows else None)
    if window is None:
        return None
    viewports = [a for a in window.screen.areas if a.type == "VIEW_3D"]
    if not viewports:
        return None
    source = max(viewports, key=lambda a: a.width * a.height)
    count = len(wm.windows)
    try:
        with context.temp_override(window=window, area=source):
            bpy.ops.screen.area_dupli("INVOKE_DEFAULT")
    except RuntimeError as exc:
        log.warning("could not open a %s: %s", area_type, exc)
        return None
    if len(wm.windows) <= count:
        return None
    area = wm.windows[-1].screen.areas[0]
    area.type = area_type
    return area


def show_image(context, path) -> "bpy.types.Image":
    """Loads (or reloads) the image and shows it in an Image Editor."""
    image = bpy.data.images.load(str(Path(path)), check_existing=True)
    image.reload()
    area = _open_area(context, "IMAGE_EDITOR")
    if area is not None:
        area.spaces.active.image = image
        area.tag_redraw()
    return image


def show_text(context, text) -> None:
    area = _open_area(context, "TEXT_EDITOR")
    if area is not None:
        area.spaces.active.text = text
        area.tag_redraw()
