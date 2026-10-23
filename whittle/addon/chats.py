# SPDX-License-Identifier: GPL-3.0-or-later
"""The open file's chats on the Blender side: which cache root it uses,
storing every chat in the .blend around a save and taking them back out when
the file opens, and the turn hooks that keep each chat's entry current.
whittle/chats.py does the work on disk, whittle/caches.py finds a file's
cache (architecture §14).

The chats are in the file's data only while it is being saved and just
after it opened: save_pre puts them on the hidden .whittle Text as bytes
ID properties, save_post and load_post take them off again. So undo never
copies them, and Ctrl+Z can never roll a chat back. The Text also keeps the
file's id, which names its cache in Whittle's user folder."""

import json
import logging
import time
from pathlib import Path

import bpy

from .. import caches
from .. import chats as store
from .. import formats
from . import paths, prefs

log = logging.getLogger("whittle")

HOLDER = ".whittle"
INDEX_PROP = "whittle_chats_index"
PAYLOAD_PROP = "whittle_chats"
ID_PROP = "whittle_file_id"
SWITCH_NOTE = ("This conversation was switched back to: the scene may have changed since its last "
               "turn (other chats or the user edited it). Inspect the target before editing.")

# The open file's id, its cache root and its chats, found once per file.
_file_id: str | None = None
_root: Path | None = None
_chats: store.Chats | None = None
# The stamp of what the save under way stores, for its save_post.
_saving: str | None = None
# Whether another Blender has the open file open: (when it was last
# checked, the answer). The sidebar asks at every redraw.
_elsewhere: tuple[float, bool] | None = None
ELSEWHERE_EVERY = 2.0


def config_dir() -> Path:
    """The bundled CLI's configuration folder: Whittle's own."""
    return paths.claude_config_dir()


def file_id() -> str | None:
    return _file_id


def root(*, create: bool = False) -> Path | None:
    """The cache root the open file uses, <user dir>/cache/<file id>/. A
    file that never had chats has none until one is made (with create);
    an unsaved file gets a fresh id then, and keeps it when it is saved."""
    global _file_id
    if _root is None:
        if _file_id is None:
            if not create:
                return None
            _file_id = caches.new_file_id()
        _use(paths.cache_dir() / _file_id)
    return _root


def _use(found: Path, *, record_path: bool = True) -> None:
    """The open file's cache is found: this Blender holds it, it records the
    file and the time, and the file's data names it."""
    global _root
    _root = found
    blend = paths.blend_path()
    values = {"used": time.time()}
    if record_path:
        values["path"] = str(blend) if blend is not None else None
    try:
        caches.take(found)
        caches.update_record(found, **values)
    except OSError as exc:
        log.error("cannot write the chats' cache %s: %s", found, exc)
    _name_cache()


def _name_cache() -> None:
    """The file's data carries its id from now on, so an autosave names the
    cache too. Not possible while Blender draws; the next save writes it."""
    try:
        text = _holder(create=True)
        if text.get(ID_PROP) != _file_id:
            text[ID_PROP] = _file_id
    except (AttributeError, RuntimeError, TypeError) as exc:
        log.debug("the file's id waits for the next save: %s", exc)


def get(*, create: bool = False) -> store.Chats | None:
    """The open file's chats, read once."""
    global _chats
    found = root(create=create)
    if found is None:
        return None
    if _chats is None or _chats.root != found:
        _chats = store.Chats(found, origin=install_id())
        _chats.load()
    return _chats


def install_id() -> str | None:
    """This install's id, which the chats it makes record as their origin."""
    try:
        return caches.install_id(paths.user_dir())
    except OSError as exc:
        log.warning("cannot keep this install's id: %s", exc)
        return None


def current_foreign() -> bool:
    """Whether the current chat was made by another install and not
    continued here yet: the sidebar asks before it sends anything in it."""
    found = _chats
    return found is not None and found.foreign(found.current)


def adopt_current() -> None:
    """Continue the current chat here: it is not asked about again."""
    found = get()
    if found is not None and found.current is not None:
        found.adopt(found.current)


def open_elsewhere(*, now: float | None = None) -> bool:
    """Whether another Blender has this file open (each then keeps a cache
    of its own, so their chats do not merge), checked at most every
    ELSEWHERE_EVERY seconds."""
    global _elsewhere
    now = time.monotonic() if now is None else now
    if _elsewhere is not None and now - _elsewhere[0] < ELSEWHERE_EVERY:
        return _elsewhere[1]
    blend = paths.blend_path()
    try:
        found = blend is not None and caches.open_elsewhere(paths.cache_dir(), blend, skip=_file_id)
    except OSError:
        found = False
    _elsewhere = (now, found)
    return found


def current_folder(*, create: bool = False) -> Path | None:
    """The current chat's folder, which is also its session folder; with
    create, a chat is made when there is none."""
    chats = get(create=create)
    if chats is None:
        return None
    if create:
        chats.ensure_current()
    if chats.current is None:
        return None
    try:
        chats.ensure_unpacked(chats.current)
    except (OSError, formats.FormatError) as exc:
        log.error("cannot unpack chat %s: %s", chats.current, exc)
        return None
    return chats.folder(chats.current)


def release() -> None:
    """This Blender lets go of the open file's cache (closing the file or quitting)."""
    if _root is not None:
        try:
            caches.release(_root)
        except OSError as exc:
            log.warning("cannot release the chats' cache %s: %s", _root, exc)


def reset() -> None:
    """Forgets the file's chats and lets go of its cache; the next use finds them again."""
    global _file_id, _root, _chats, _saving, _elsewhere
    release()
    _file_id = None
    _root = None
    _chats = None
    _saving = None
    _elsewhere = None


def chat_of(folder) -> tuple[store.Chats, str] | None:
    """The chats and the chat a session folder is, when it is one of the
    open file's chats."""
    if _chats is None or folder is None:
        return None
    folder = Path(folder)
    if folder.parent != _chats.root / "chats":
        return None
    return (_chats, folder.name) if folder.name in _chats else None


# -- turn hooks ---------------------------------------------------------------------

def model_for(folder) -> str | None:
    """The model of the chat a session folder is; None when it follows the
    default, or the folder is not one of the file's chats."""
    found = chat_of(folder)
    return found[0].model(found[1]) if found is not None else None


def switch_note(folder) -> list[str]:
    """The context lines a turn about to be sent in a chat carries for the
    agent: after a switch, that the scene may have changed since the chat's
    last turn."""
    found = chat_of(folder)
    return [SWITCH_NOTE] if found is not None and found[0].switched == found[1] else []


def turn_began(folder, prompt: str, targets=(), model: str | None = None) -> None:
    """The agent took a turn in a chat: its first turn names it, and keeps
    the model it went with. A switch note it carried was said."""
    found = chat_of(folder)
    if found is None:
        return
    chats, chat = found
    try:
        names = [o.name for o in targets if o is not None]
        chats.began(chat, prompt, names[0] if names else None, model)
    except (OSError, ReferenceError) as exc:
        log.warning("could not name chat %s: %s", chat, exc)
    if chats.switched == chat:
        chats.switched = None


def turn_ended(folder) -> None:
    """A turn ended: the chat's entry gets its turn count, time and size."""
    found = chat_of(folder)
    if found is None:
        return
    chats, chat = found
    try:
        chats.refresh(chat, ended=True)
        caches.update_record(chats.root, used=time.time())
    except OSError as exc:
        log.warning("could not update chat %s: %s", chat, exc)


# -- the .blend ---------------------------------------------------------------------

def _holder(create: bool = False):
    text = bpy.data.texts.get(HOLDER)
    if text is None and create:
        text = bpy.data.texts.new(HOLDER)
        text.use_fake_user = True
    return text


def _take_payload(text) -> tuple[str, dict, dict[str, bytes]] | None:
    """The chats the file stores (the index as written, read, and the zips),
    removed from its data."""
    if text is None or INDEX_PROP not in text:
        return None
    raw = text[INDEX_PROP]
    try:
        index = json.loads(raw)
        packed = {chat: bytes(data) for chat, data in text.get(PAYLOAD_PROP, {}).items()}
    except (TypeError, ValueError) as exc:
        log.error("the file's chats cannot be read: %s", exc)
        index, packed = None, {}
    for key in (INDEX_PROP, PAYLOAD_PROP):
        if key in text:
            del text[key]
    return (raw, index, packed) if index is not None and isinstance(raw, str) else None


def before_save(scene=None) -> None:
    """Every chat goes into the file being saved: the index and one zip per
    chat with a history, on the hidden holder Text, with the file's id. The
    scene names the current chat and its node, so the saved file says which
    it shows."""
    global _saving
    if _root is None and bpy.data.filepath:
        # A file opened before Whittle was enabled or updated: its cache
        # is found first.
        after_load()
    chats = get()
    # A file that never had a chat gets no holder; one that had chats keeps
    # it, so a file whose chats were all deleted says so.
    text = _holder(create=chats is not None and bool(chats.index.chats))
    if text is None:
        return
    if _file_id is not None:
        text[ID_PROP] = _file_id
    if not prefs.get().store_chats:
        # The file names its cache, and carries no chat: they stay on this
        # computer only.
        _saving = None
        return
    packed = chats.pack_all() if chats is not None else {}
    index = store.index_json(chats.index if chats is not None else store.Index())
    text[INDEX_PROP] = index
    text[PAYLOAD_PROP] = packed
    _saving = caches.state_stamp(index, packed) if chats is not None else None
    scene = scene or bpy.context.scene
    if scene is not None and hasattr(scene, "whittle") and chats is not None:
        from . import history

        scene.whittle.chat = chats.current or ""
        hist = history.active()
        if hist is not None and hist.tree is not None:
            scene.whittle.history_node = hist.current


def after_save(filepath: str | None = None) -> None:
    """The saved file has the chats; the open one lets go of them again. A
    save of the open file (not a copy) records where it is and what it now
    stores."""
    global _saving
    text = _holder()
    if text is not None:
        for key in (INDEX_PROP, PAYLOAD_PROP):
            if key in text:
                del text[key]
    stamp, _saving = _saving, None
    blend = paths.blend_path()
    if filepath is None or blend is None or not caches.same_file(filepath, blend):
        return
    if _root is None:
        return
    values = {"path": str(blend), "used": time.time()}
    if stamp is not None:
        values["base"] = stamp
    try:
        caches.update_record(_root, **values)
    except OSError as exc:
        log.error("cannot record the save in the chats' cache: %s", exc)


def save_failed() -> None:
    """The save failed (save_post_fail, no save_post): the chats come off
    the holder, or undo would copy them, and nothing was stored."""
    global _saving
    _saving = None
    text = _holder()
    if text is not None:
        for key in (INDEX_PROP, PAYLOAD_PROP):
            if key in text:
                del text[key]


def load_failed() -> None:
    """Opening another file failed (load_post_fail): the open file keeps its
    cache, which load_pre let go of."""
    if _root is not None:
        try:
            caches.take(_root)
        except OSError as exc:
            log.error("cannot take the chats' cache %s back: %s", _root, exc)


def after_load() -> None:
    """The opened file's chats: taken out of its data into its cache. The
    file's id names the cache (a copy whose cache is another file's gets a
    fresh one). Where the cache differs from the file the file wins, unless
    the cache was in step with exactly what the file stores and went on
    from there without a save (a crash): then its newer work stays. A file
    without chats uses the cache as it is."""
    global _file_id
    reset()
    text = _holder()
    payload = _take_payload(text)
    blend = paths.blend_path()
    recovery = blend is not None and paths.is_recovery_file(blend)
    # A new file's data may come from a startup file that once had chats:
    # only a saved file's id names its cache.
    stored = text.get(ID_PROP) if text is not None and blend is not None else None
    found, fresh = caches.find(paths.cache_dir(), stored, None if recovery else blend)
    if found is None and payload is None:
        cleanup()
        return
    _file_id = found or caches.new_file_id()
    if fresh:
        log.info("the chats' cache this file names is another file's (a copy, or open elsewhere): "
                 "it gets its own")
    root_dir = paths.cache_dir() / _file_id
    _use(root_dir, record_path=not recovery)
    chats = get()
    if chats is not None and payload is not None:
        raw, index, packed = payload
        stamp = caches.state_stamp(raw, packed)
        try:
            keep = caches.read_record(root_dir).get("base") == stamp
            report = chats.reconcile(index, packed, keep_newer=keep)
            if report["kept"]:
                log.debug("the chats' cache was built on what the file stores: kept as it is")
            caches.update_record(root_dir, base=stamp)
        except (OSError, formats.FormatError) as exc:
            log.error("could not restore the file's chats: %s", exc)
    cleanup()


def cleanup() -> None:
    """Caches not used for 30 days go, never the open file's."""
    try:
        caches.cleanup(paths.cache_dir(), keep=(_root,), config=config_dir())
    except OSError as exc:
        log.warning("could not clean up the chats' caches: %s", exc)
