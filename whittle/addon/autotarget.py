# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto targets: with scene.whittle.target_auto on, the target list follows
the selection in Object Mode (targets.auto_pick). A depsgraph handler sees
selection changes and a message-bus subscription sees the active object
change, which on its own does not always update the depsgraph."""

import logging

import bpy

from . import compare, sketch, targets, turn

log = logging.getLogger("whittle")

_OWNER = object()


def can_sync(scene, view_layer) -> bool:
    """Auto holds still while a turn runs (its targets are locked), during a
    comparison (the scene shows another node), while sketching and outside
    Object Mode, where the selection is not about which objects to edit."""
    if not getattr(scene, "whittle", None) or not scene.whittle.target_auto:
        return False
    if turn.busy(turn.current()):
        return False
    if compare.active() is not None or sketch.current_session() is not None:
        return False
    active = view_layer.objects.active
    return active is None or active.mode == "OBJECT"


def sync(scene, view_layer) -> bool:
    """Makes the target list follow the selection when Auto may; returns
    whether the list changed."""
    if scene is None or view_layer is None or not can_sync(scene, view_layer):
        return False
    return targets.sync_auto(scene, view_layer)


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    try:
        sync(scene, depsgraph.view_layer)
    except Exception:
        log.exception("could not follow the selection")


def _on_active():
    try:
        sync(bpy.context.scene, bpy.context.view_layer)
    except Exception:
        log.exception("could not follow the active object")


def subscribe() -> None:
    bpy.msgbus.clear_by_owner(_OWNER)
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_OWNER, args=(),
                             notify=_on_active)


@bpy.app.handlers.persistent
def _after_load(*_args):
    # Loading a file drops every message-bus subscription; the file's own
    # selection is what Auto targets from the start.
    subscribe()
    _on_active()


HANDLERS = ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
            (bpy.app.handlers.load_post, _after_load))


def _first_sync():
    _on_active()
    return None


def register() -> None:
    for handlers, handler in HANDLERS:
        if handler not in handlers:
            handlers.append(handler)
    subscribe()
    # Registering inside an open file (enabling the add-on) gets no load_post:
    # the first timer tick, with a full context, takes the selection.
    if not bpy.app.timers.is_registered(_first_sync):
        bpy.app.timers.register(_first_sync, first_interval=0.0)


def unregister() -> None:
    for handlers, handler in HANDLERS:
        while handler in handlers:
            handlers.remove(handler)
    if bpy.app.timers.is_registered(_first_sync):
        bpy.app.timers.unregister(_first_sync)
    bpy.msgbus.clear_by_owner(_OWNER)
