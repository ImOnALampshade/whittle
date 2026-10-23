# SPDX-License-Identifier: GPL-3.0-or-later
"""On-disk formats: request bundles and session folder layout.

Stdlib only, so the agent process and Blender share one reader. JSON files carry
"format" and "version" keys and are written atomically.
"""

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

REQUEST_FORMAT = "whittle.request"
STROKES_FORMAT = "whittle.strokes"
TARGET_FORMAT = "whittle.target"
VERSION = 1

STROKE_TYPES = ("free", "add", "carve", "crease", "region", "note")
RENDER_MODES = ("shaded", "wireframe", "matcap", "overlay")


class FormatError(ValueError):
    pass


def write_json_atomic(path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        # mkstemp creates the file private; give it the usual permissions.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read_json(path) -> dict:
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except FileNotFoundError:
        raise FormatError(f"{path}: missing") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FormatError(f"{path}: invalid JSON: {exc}") from None
    if not isinstance(obj, dict):
        raise FormatError(f"{path}: top level is not an object")
    return obj


# -- validation ---------------------------------------------------------------

_NUMBER = (int, float)


def _type_ok(value, expected) -> bool:
    if expected is None:
        return value is None
    if expected is float:
        return isinstance(value, _NUMBER) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def _check(obj: dict, where: str, spec: dict) -> None:
    """spec maps key -> type or tuple of types (None allowed in the tuple)."""
    for key, types in spec.items():
        if key not in obj:
            raise FormatError(f"{where}: missing key {key!r}")
        options = types if isinstance(types, tuple) else (types,)
        if not any(_type_ok(obj[key], t) for t in options):
            raise FormatError(f"{where}: key {key!r} has the wrong type")


def _check_header(obj: dict, where: str, fmt: str) -> None:
    _check(obj, where, {"format": str, "version": int})
    if obj["format"] != fmt:
        raise FormatError(f"{where}: format is {obj['format']!r}, expected {fmt!r}")
    if obj["version"] != VERSION:
        raise FormatError(f"{where}: unsupported version {obj['version']}")


def _check_matrix(value, where: str, key: str) -> None:
    ok = (isinstance(value, list) and len(value) == 4
          and all(isinstance(r, list) and len(r) == 4 and all(_type_ok(x, float) for x in r)
                  for r in value))
    if not ok:
        raise FormatError(f"{where}: key {key!r} is not a 4x4 matrix")


def _check_vec3(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(_type_ok(x, float) for x in value)


def validate_request(obj: dict, where: str = "request.json") -> None:
    _check_header(obj, where, REQUEST_FORMAT)
    _check(obj, where, {
        "node": str, "parent": (str, None), "prompt": str, "amend": (int, None),
        "target": list, "stroke_types": list, "views": list, "refs": list,
        "units": dict, "settings": dict,
    })
    for i, t in enumerate(obj["target"]):
        if not isinstance(t, dict):
            raise FormatError(f"{where}: target[{i}] is not an object")
        _check(t, f"{where}: target[{i}]", {"uid": str, "name": str, "type": str})
    for st in obj["stroke_types"]:
        if st not in STROKE_TYPES:
            raise FormatError(f"{where}: unknown stroke type {st!r}")
    if not all(_type_ok(v, int) for v in obj["views"]):
        raise FormatError(f"{where}: key 'views' must hold integers")
    if not all(isinstance(r, str) for r in obj["refs"]):
        raise FormatError(f"{where}: key 'refs' must hold strings")
    for ref in obj["refs"]:
        # A ref names a file inside the bundle, never one elsewhere.
        if not _inside(ref):
            raise FormatError(f"{where}: ref {ref!r} is not a path inside the bundle")
    # Optional: bundles written before it existed have no such key.
    if not isinstance(obj.get("target_collection"), (str, type(None))):
        raise FormatError(f"{where}: key 'target_collection' has the wrong type")
    _check(obj["units"], f"{where}: units", {"system": str, "scale_length": float})


def _inside(rel: str) -> bool:
    """A relative path that stays inside the folder it is relative to."""
    path = PurePosixPath(rel.replace("\\", "/"))
    return bool(rel) and not path.is_absolute() and not PureWindowsPath(rel).drive and ".." not in path.parts


def validate_strokes(obj: dict, where: str = "strokes.json") -> None:
    _check_header(obj, where, STROKES_FORMAT)
    _check(obj, where, {"strokes": list})
    for i, s in enumerate(obj["strokes"]):
        w = f"{where}: strokes[{i}]"
        if not isinstance(s, dict):
            raise FormatError(f"{w} is not an object")
        _check(s, w, {
            "index": int, "type": str, "view": int, "cyclic": bool, "points": list,
            "radius": list, "opacity": list, "on_surface": list, "normal": list,
            "hit_object": list,
        })
        if s["type"] not in STROKE_TYPES:
            raise FormatError(f"{w}: unknown stroke type {s['type']!r}")
        n = len(s["points"])
        if n == 0:
            raise FormatError(f"{w}: no points")
        if not all(_check_vec3(p) for p in s["points"]):
            raise FormatError(f"{w}: key 'points' must hold [x, y, z] triples")
        for key in ("radius", "opacity", "on_surface", "normal", "hit_object"):
            if len(s[key]) != n:
                raise FormatError(f"{w}: key {key!r} has {len(s[key])} entries for {n} points")
        if not all(n is None or _check_vec3(n) for n in s["normal"]):
            raise FormatError(f"{w}: key 'normal' must hold [x, y, z] or null")


def validate_camera(obj: dict, where: str = "camera.json") -> None:
    _check(obj, where, {
        "id": int, "view_matrix": list, "window_matrix": list, "is_perspective": bool,
        "width": int, "height": int, "from_camera": (str, None), "camera": dict,
    })
    _check_matrix(obj["view_matrix"], where, "view_matrix")
    _check_matrix(obj["window_matrix"], where, "window_matrix")
    if obj["width"] <= 0 or obj["height"] <= 0:
        raise FormatError(f"{where}: width and height must be positive")
    cam = obj["camera"]
    _check(cam, f"{where}: camera", {
        "matrix_world": list, "type": str, "angle": float, "ortho_scale": float,
        "sensor_fit": str, "clip_start": float, "clip_end": float,
    })
    _check_matrix(cam["matrix_world"], f"{where}: camera", "matrix_world")
    if cam["type"] not in ("PERSP", "ORTHO"):
        raise FormatError(f"{where}: camera type {cam['type']!r} is not PERSP or ORTHO")
    if cam["sensor_fit"] not in ("HORIZONTAL", "VERTICAL"):
        raise FormatError(f"{where}: camera sensor_fit {cam['sensor_fit']!r} is invalid")


def _check_names(value, where: str, key: str, *, nullable: bool = False) -> None:
    ok = isinstance(value, list) and all(isinstance(v, str) or (nullable and v is None) for v in value)
    if not ok:
        raise FormatError(f"{where}: key {key!r} must hold strings")


def validate_target(obj: dict, where: str = "target.json") -> None:
    """A snapshot manifest: what was written, and the names restore pairs the
    appended datablocks with."""
    _check_header(obj, where, TARGET_FORMAT)
    _check(obj, where, {"objects": list, "datablocks": dict})
    for i, o in enumerate(obj["objects"]):
        w = f"{where}: objects[{i}]"
        if not isinstance(o, dict):
            raise FormatError(f"{w} is not an object")
        _check(o, w, {"uid": str, "name": str, "type": str, "data_name": (str, None),
                      "collections": list, "parent": (str, None), "parent_uid": (str, None),
                      "materials": list, "node_groups": list})
        _check_names(o["collections"], w, "collections")
        _check_names(o["materials"], w, "materials", nullable=True)
        _check_names(o["node_groups"], w, "node_groups")
    blocks = obj["datablocks"]
    _check(blocks, f"{where}: datablocks", {"materials": list, "node_groups": list, "images": list})
    for key in ("materials", "node_groups", "images"):
        _check_names(blocks[key], f"{where}: datablocks", key)
    # Optional: materials and node groups written for their own sake, which
    # no object in the snapshot uses.
    loose = obj.get("loose", {})
    if not isinstance(loose, dict):
        raise FormatError(f"{where}: key 'loose' has the wrong type")
    for key in ("materials", "node_groups"):
        _check_names(loose.get(key, []), f"{where}: loose", key)


def write_target_manifest(path, manifest: dict) -> None:
    validate_target(manifest, str(path))
    write_json_atomic(path, manifest)


def read_target_manifest(path) -> dict:
    obj = read_json(path)
    validate_target(obj, str(path))
    return obj


# -- data ---------------------------------------------------------------------

@dataclass
class View:
    id: int
    view_matrix: list
    window_matrix: list
    is_perspective: bool
    width: int
    height: int
    from_camera: str | None
    camera: dict

    @classmethod
    def from_json(cls, obj: dict) -> "View":
        validate_camera(obj)
        return cls(**{k: obj[k] for k in cls.__dataclass_fields__})

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def aspect(self) -> float:
        return self.width / self.height


@dataclass
class Stroke:
    index: int
    type: str
    view: int
    cyclic: bool
    points: list
    radius: list
    opacity: list
    on_surface: list
    normal: list
    hit_object: list

    @classmethod
    def from_json(cls, obj: dict) -> "Stroke":
        return cls(**{k: obj[k] for k in cls.__dataclass_fields__})

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Request:
    node: str
    parent: str | None
    prompt: str
    target: list
    stroke_types: list
    views: list
    units: dict
    settings: dict
    refs: list = field(default_factory=list)
    amend: int | None = None
    # The collection new objects belong in, when the target is one.
    target_collection: str | None = None

    @classmethod
    def from_json(cls, obj: dict) -> "Request":
        validate_request(obj)
        return cls(**{k: obj[k] for k in cls.__dataclass_fields__ if k in obj})

    def to_json(self) -> dict:
        return {"format": REQUEST_FORMAT, "version": VERSION, **asdict(self)}


@dataclass
class Bundle:
    root: Path
    request: Request
    strokes: list[Stroke]
    views: dict[int, View]

    def view_dir(self, view_id: int) -> Path:
        return self.root / "views" / str(view_id)

    def overlay_path(self, view_id: int) -> Path:
        return self.view_dir(view_id) / "overlay.png"

    def strokes_png_path(self, view_id: int) -> Path:
        return self.view_dir(view_id) / "strokes.png"


def read_bundle(path) -> Bundle:
    """Reads and validates a request bundle; FormatError names the file and key."""
    root = Path(path)
    if not root.is_dir():
        raise FormatError(f"{root}: bundle folder does not exist")
    req_obj = read_json(root / "request.json")
    validate_request(req_obj, str(root / "request.json"))
    request = Request.from_json(req_obj)

    strokes_obj = read_json(root / "strokes.json")
    validate_strokes(strokes_obj, str(root / "strokes.json"))
    strokes = [Stroke.from_json(s) for s in strokes_obj["strokes"]]

    views = {}
    for view_id in request.views:
        cam_path = root / "views" / str(view_id) / "camera.json"
        cam_obj = read_json(cam_path)
        validate_camera(cam_obj, str(cam_path))
        if cam_obj["id"] != view_id:
            raise FormatError(f"{cam_path}: id {cam_obj['id']} does not match folder {view_id}")
        views[view_id] = View.from_json(cam_obj)
    for s in strokes:
        if s.view not in views:
            raise FormatError(f"{root / 'strokes.json'}: stroke {s.index} uses unknown view {s.view}")
    for ref in request.refs:
        if not (root / ref).is_file():
            raise FormatError(f"{root / 'request.json'}: ref {ref!r} is missing")
    return Bundle(root=root, request=request, strokes=strokes, views=views)


def write_request(path, request: Request, strokes: list[Stroke], views: list[View]) -> None:
    """Writes the JSON half of a bundle; images are written by the caller."""
    root = Path(path)
    write_json_atomic(root / "request.json", request.to_json())
    write_json_atomic(root / "strokes.json", {
        "format": STROKES_FORMAT, "version": VERSION,
        "strokes": [s.to_json() for s in strokes],
    })
    for view in views:
        write_json_atomic(root / "views" / str(view.id) / "camera.json", view.to_json())


# -- session folder -----------------------------------------------------------

_RENDER_SEQ = re.compile(r"^(\d{3,})-")
_NODE_ID = re.compile(r"^n\d{4,}$")


def node_id(n: int) -> str:
    return f"n{n:04d}"


def is_node_id(node: object) -> bool:
    return isinstance(node, str) and _NODE_ID.fullmatch(node) is not None


def node_number(node: str) -> int:
    """The number in a node id; ValueError for anything that is not one."""
    if not is_node_id(node):
        raise ValueError(f"not a node id: {node!r}")
    return int(node[1:])


class SessionDir:
    """Paths inside a session folder."""

    def __init__(self, root):
        self.root = Path(root)

    def session_path(self) -> Path:
        return self.root / "session.json"

    def target_blend(self, node: str) -> Path:
        """The node's snapshot; its manifest is target.json beside it."""
        return self.node_dir(node) / "target.blend"

    def thumb_path(self, node: str) -> Path:
        return self.node_dir(node) / "thumb.png"

    def compare_dir(self) -> Path:
        return self.root / "compare"

    def node_dir(self, node: str) -> Path:
        return self.root / "nodes" / node

    def request_dir(self, node: str) -> Path:
        return self.node_dir(node) / "request"

    def renders_dir(self, node: str) -> Path:
        return self.node_dir(node) / "renders"

    def amend_dir(self, node: str, n: int) -> Path:
        return self.node_dir(node) / f"amend-{n}"

    def checkpoint_paths(self, node: str, name: str) -> tuple[Path, Path]:
        """(<name>.blend, <name>.json) under the node's checkpoints folder."""
        folder = self.node_dir(node) / "checkpoints"
        return folder / f"{name}.blend", folder / f"{name}.json"

    def transcript_path(self, node: str) -> Path:
        return self.node_dir(node) / "transcript.jsonl"

    def node_ids(self) -> list[str]:
        """Node folders in node order."""
        nodes = self.root / "nodes"
        if not nodes.is_dir():
            return []
        found = [p.name for p in nodes.iterdir() if p.is_dir() and is_node_id(p.name)]
        return sorted(found, key=node_number)

    def next_render_path(self, node: str, view: int | None, mode: str) -> Path:
        d = self.renders_dir(node)
        d.mkdir(parents=True, exist_ok=True)
        seqs = [int(m.group(1)) for p in d.iterdir() if (m := _RENDER_SEQ.match(p.name))]
        seq = max(seqs, default=0) + 1
        tag = f"v{view}" if view is not None else "cam"
        return d / f"{seq:03d}-{tag}-{mode}.png"
