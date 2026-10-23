# SPDX-License-Identifier: GPL-3.0-or-later
"""Thumbnails of render images for the sidebar, loaded lazily into one
bpy.utils.previews collection."""

import os

import bpy.utils.previews

MAX_PREVIEWS = 200

_collection = None


def register() -> None:
    global _collection
    if _collection is None:
        _collection = bpy.utils.previews.new()


def unregister() -> None:
    global _collection
    if _collection is not None:
        bpy.utils.previews.remove(_collection)
        _collection = None


def clear() -> None:
    if _collection is not None:
        _collection.clear()


def preview(path: str):
    """The preview for an image file, loaded on first use; None before register
    or for a file that is not there (a reference typed by hand, say)."""
    if _collection is None or not os.path.isfile(path):
        return None
    key = os.path.realpath(path)
    found = _collection.get(key)
    if found is None:
        if len(_collection) >= MAX_PREVIEWS:
            _collection.clear()
        found = _collection.load(key, key, "IMAGE")
    return found


def icon(path: str) -> int:
    """The icon id for template_icon; 0 when there is none."""
    found = preview(path)
    return found.icon_id if found is not None else 0
