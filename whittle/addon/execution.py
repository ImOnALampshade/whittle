# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs agent code in the live scene and reports what changed."""

import contextlib
import io
import linecache
import math
import traceback
from collections.abc import Callable

import bmesh
import bpy
import mathutils
from mathutils import Matrix, Vector

from . import meshcheck

# Each run's source is registered under its own name, so a traceback through
# a helper an earlier run defined shows that run's lines.
FILENAME = "<whittle exec>"


def _filename(run: int) -> str:
    return f"<whittle exec {run}>"
STDOUT_LIMIT = 20_000


class WhittleHelper:
    """The `whittle` object agent code sees."""

    def __init__(self, targets: Callable[[], list]):
        self._targets = targets

    def targets(self) -> list:
        return list(self._targets())

    def mesh_report(self, obj, evaluated: bool = True) -> dict:
        """Counts that describe obj's mesh: shells, open edges, self-intersections,
        triangles and so on (see the mesh-check skill)."""
        return meshcheck.mesh_report(obj, evaluated=evaluated)

    def weld(self, obj, dist: float = 1e-4) -> dict:
        """Merges near-duplicate vertices and fixes normals on obj's own mesh."""
        return meshcheck.weld(obj, dist=dist)

    def view3d_override(self):
        """A temp_override for the first 3D viewport, for operators that need one."""
        # Background Blender keeps the startup screen's areas, but they never draw.
        if bpy.app.background:
            raise RuntimeError("no 3D viewport: Blender is running in the background")
        wm = bpy.context.window_manager
        for window in (wm.windows if wm else []):
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is not None:
                    return bpy.context.temp_override(window=window, area=area, region=region)
        raise RuntimeError("no 3D viewport is open (Blender may be running in the background)")


class ExecNamespace:
    """One namespace per agent session, so variables persist between exec calls."""

    def __init__(self, targets: Callable[[], list] = list):
        self.globals = {
            "__name__": "__whittle__",
            "__builtins__": __builtins__,
            "bpy": bpy,
            "bmesh": bmesh,
            "mathutils": mathutils,
            "math": math,
            "Vector": Vector,
            "Matrix": Matrix,
            "whittle": WhittleHelper(targets),
        }
        self.runs = 0


def run(code: str, ns: ExecNamespace) -> dict:
    ns.runs += 1
    before = summarize_objects()
    out = io.StringIO()
    error = None
    # Registering the source lets tracebacks show the agent's own lines.
    filename = _filename(ns.runs)
    linecache.cache[filename] = (len(code), None, code.splitlines(keepends=True), filename)
    try:
        compiled = compile(code, filename, "exec")
    except SyntaxError as exc:
        error = {"type": "SyntaxError", "message": str(exc),
                 "traceback": "".join(traceback.format_exception_only(exc)).rstrip()}
    else:
        with contextlib.redirect_stdout(out):
            try:
                exec(compiled, ns.globals)
            except BaseException as exc:
                # BaseException so that sys.exit() in agent code cannot quit
                # Blender, and a KeyboardInterrupt it raises cannot stop the
                # bridge's timer.
                error = {"type": type(exc).__name__, "message": str(exc),
                         "traceback": trimmed_traceback(exc)}
    stdout = out.getvalue()
    if len(stdout) > STDOUT_LIMIT:
        stdout = stdout[:STDOUT_LIMIT] + f"\n... (truncated, {len(stdout)} characters in all)"
    return {"stdout": stdout, "error": error, "diff": scene_diff(before, summarize_objects())}


def trimmed_traceback(exc: BaseException) -> str:
    """Drops the frames above the agent's code (this module's exec call)."""
    frames = traceback.extract_tb(exc.__traceback__)
    start = next((i for i, f in enumerate(frames) if f.filename.startswith(FILENAME[:-1])), 0)
    lines = ["Traceback (most recent call last):\n"]
    lines += traceback.format_list(frames[start:])
    lines += traceback.format_exception_only(exc)
    return "".join(lines).rstrip()


def _r(values) -> list:
    return [round(v, 4) + 0.0 for v in values]


def summarize_object(obj) -> dict:
    summary = {
        "type": obj.type,
        "location": _r(obj.location),
        "rotation": _r(obj.rotation_euler),
        "scale": _r(obj.scale),
        "parent": obj.parent.name if obj.parent else None,
        "modifiers": [f"{m.name}:{m.type}" for m in obj.modifiers],
        "materials": [s.material.name if s.material else None for s in obj.material_slots],
        "data": obj.data.name if obj.data else None,
    }
    if obj.type == "MESH":
        mesh = obj.data
        summary["counts"] = [len(mesh.vertices), len(mesh.edges), len(mesh.polygons)]
    return summary


def summarize_objects() -> dict[str, dict]:
    return {obj.name: summarize_object(obj) for obj in bpy.data.objects}


def scene_diff(before: dict, after: dict) -> dict:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = []
    for name in sorted(set(before) & set(after)):
        fields = [k for k in after[name] if before[name].get(k) != after[name][k]]
        if fields:
            changed.append({"name": name, "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}
