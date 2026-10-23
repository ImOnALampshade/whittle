# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender side of Whittle. May import bpy everywhere; never imports the agent."""

import logging

import bpy

from . import autotarget, chats, compare, enter, history, models, operators, prefs, previews, props, refs, setup, sketch, start, turn, ui
from . import shortcut

log = logging.getLogger("whittle")

CLASSES = (*prefs.CLASSES, *props.CLASSES, *operators.CLASSES, *setup.CLASSES, *start.CLASSES,
           *refs.CLASSES, *enter.CLASSES, *shortcut.CLASSES, *models.CLASSES, *ui.CLASSES)


def _filepath(args) -> str | None:
    """The file a load or save handler is called for (Blender passes it first)."""
    return args[0] if args and isinstance(args[0], str) and args[0] else None


@bpy.app.handlers.persistent
def _stop_agent(*_args):
    # No more timer ticks come after a file load or quit, so stop synchronously.
    sketch.end_session()
    turn.shutdown_current()
    # The file being closed lets go of its chats' cache.
    chats.release()


@bpy.app.handlers.persistent
def _after_load(*_args):
    # A comparison or a ghost belongs to the session of the file it was made
    # in; a saved ghost is cleaned out of the file just loaded.
    compare.reset()
    try:
        compare.clear_ghost()
    except Exception:
        log.exception("could not clear the history ghost")
    history.invalidate()
    # The file's chats come out of its data into its cache.
    try:
        chats.after_load()
    except Exception:
        log.exception("could not restore the file's chats")
    # session.json moves on with every restore, but the file only records the
    # node it shows when it is saved: the reopened scene is what the next
    # turn starts from.
    try:
        history.sync_from_scene(reason="load")
    except Exception:
        log.exception("could not match the history to the file just loaded")


@bpy.app.handlers.persistent
def _after_undo(*_args):
    for step in (history.sync_from_scene,
                 # A comparison is no undo step: an undo puts back a scene from
                 # before it, so it is over.
                 compare.forget,
                 sketch.after_undo,
                 _tell_the_turn):
        try:
            step()
        except Exception:
            log.exception("after undo: %s failed", step.__name__)


def _tell_the_turn():
    ctl = turn.current()
    if ctl is not None:
        ctl.after_undo()


@bpy.app.handlers.persistent
def _before_save(*_args):
    # Every chat goes into the file being written.
    try:
        chats.before_save()
    except Exception:
        log.exception("could not store the chats in the file")


@bpy.app.handlers.persistent
def _after_save(*args):
    # The open file lets go of the chats again. The cache stays where it
    # is, whatever the file is now called: its id names it.
    try:
        chats.after_save(_filepath(args))
    except Exception:
        log.exception("could not take the chats back out of the file")


@bpy.app.handlers.persistent
def _save_failed(*_args):
    # No save_post comes: the chats must not stay in the open file's data.
    try:
        chats.save_failed()
    except Exception:
        log.exception("could not take the chats back out of the file")


@bpy.app.handlers.persistent
def _load_failed(*_args):
    # The file stays open: it takes its chats' cache back.
    try:
        chats.load_failed()
    except Exception:
        log.exception("could not take the chats' cache back")


HANDLERS = ((bpy.app.handlers.load_pre, _stop_agent), (bpy.app.handlers.exit_pre, _stop_agent),
            (bpy.app.handlers.load_post, _after_load), (bpy.app.handlers.load_post_fail, _load_failed),
            (bpy.app.handlers.undo_post, _after_undo), (bpy.app.handlers.redo_post, _after_undo),
            (bpy.app.handlers.save_pre, _before_save), (bpy.app.handlers.save_post, _after_save),
            (bpy.app.handlers.save_post_fail, _save_failed))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    props.register_props()
    previews.register()
    for handlers, handler in HANDLERS:
        if handler not in handlers:
            handlers.append(handler)
    _remove_asset_entry()
    bpy.types.ASSETBROWSER_MT_context_menu.append(start.draw_asset_menu)
    autotarget.register()
    enter.register_keymap()
    shortcut.register_keymap()
    _find_open_file_chats()


def _find_open_file_chats():
    # Enabled with a saved file already open: its chats are found now (and
    # old caches cleaned up). At startup the data cannot be read yet, and
    # load_post does both.
    if not isinstance(bpy.data, bpy.types.BlendData) or not bpy.data.filepath:
        return
    try:
        if chats.root() is None:
            chats.after_load()
    except Exception:
        log.exception("could not find the open file's chats")


def _remove_asset_entry():
    # Removing an entry that is not there is a no-op, so a second register
    # never adds the entry twice.
    bpy.types.ASSETBROWSER_MT_context_menu.remove(start.draw_asset_menu)


def unregister():
    shortcut.unregister_keymap()
    enter.unregister_keymap()
    autotarget.unregister()
    sketch.end_session()
    turn.shutdown_current()
    setup.shutdown()
    _remove_asset_entry()
    for handlers, handler in HANDLERS:
        while handler in handlers:
            handlers.remove(handler)
    compare.reset()
    chats.reset()
    previews.unregister()
    props.unregister_props()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
