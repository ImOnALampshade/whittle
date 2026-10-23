# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP tool handlers. Plain async functions of (ctx, args), so tests can call
them without the SDK; build_servers wraps them for the SDK's in-process server.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import formats
from ..protocol import Event, Method
from .connection import BridgeCallError

IMAGE_RESULT_CHARS = 4_000_000
STROKES_TEXT_LIMIT = 200_000

# Image paths appear on their own caption lines so the runner can report them in
# tool_result events without tracking which tool call produced which image.
IMAGE_LINE = re.compile(r"^image: (.+)$", re.MULTILINE)

MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif"}


@dataclass
class Amendment:
    number: int | None
    text: str
    bundle_dir: str | None


def amend_note(number: int | None, text: str, has_bundle: bool) -> str:
    """A message the user sent mid-turn, tagged so the model can tell it from
    the tool output it rides on."""
    label = f"User amendment {number}" if number is not None else "User amendment"
    lines = [f"{label}: {text.strip() or '(new strokes only)'}"]
    if has_bundle and number is not None:
        lines.append(f"New strokes: call mcp__whittle__request with amend={number} to see them.")
    return "<user_amendment>\n" + "\n".join(lines) + "\n</user_amendment>"


def follow_up_text(notes: list[str]) -> str:
    return ("\n".join(notes) + "\n\nThe user sent this after your last reply. Fold this into the "
            "current turn and continue.")


@dataclass
class ToolContext:
    connection: object
    turn_id: str | None = None
    bundle_dir: str | None = None
    # Amendments the user sent during the turn, waiting for the next tool result.
    amends: list[Amendment] = field(default_factory=list)

    async def event(self, name: str, data: dict) -> None:
        await self.connection.send_event(name, {"turn_id": self.turn_id, **data})

    def queue_amend(self, number: int | None, text: str, bundle_dir: str | None) -> None:
        self.amends.append(Amendment(number, text, bundle_dir))

    def take_amend_notes(self) -> list[tuple[int | None, str]]:
        amends, self.amends = self.amends, []
        return [(a.number, amend_note(a.number, a.text, a.bundle_dir is not None)) for a in amends]

    async def deliver_notes(self, result: dict) -> dict:
        """Appends queued amendments to a tool result. Every result carries
        them, errors included, so the model sees them at its next step."""
        for number, note in self.take_amend_notes():
            result.setdefault("content", []).append(text_block(note))
            await self.event(Event.AMEND_DELIVERED, {"amend": number, "via": "tool_result"})
        return result


# -- result helpers -----------------------------------------------------------

def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def image_block(path: Path) -> dict:
    mime = MIME_TYPES.get(path.suffix.lower(), "image/png")
    return {"type": "image", "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            "mimeType": mime}


def error_result(exc: BridgeCallError) -> dict:
    text = f"Blender error ({exc.code}): {exc.message}"
    if exc.detail:
        text += f"\n{exc.detail}"
    return {"content": [text_block(text)], "is_error": True}


def image_paths(text: str) -> list[str]:
    return [m.strip() for m in IMAGE_LINE.findall(text)]


def format_exec_result(data: dict) -> str:
    parts = []
    stdout = data.get("stdout") or ""
    parts.append("stdout:\n" + stdout if stdout else "stdout: (empty)")
    error = data.get("error")
    if error:
        parts.append(f"error: {error.get('type')}: {error.get('message')}\n{error.get('traceback', '')}".rstrip())
    diff = data.get("diff") or {}
    changes = []
    if diff.get("added"):
        changes.append("added: " + ", ".join(diff["added"]))
    if diff.get("removed"):
        changes.append("removed: " + ", ".join(diff["removed"]))
    for c in diff.get("changed") or []:
        changes.append(f"changed: {c['name']} ({', '.join(c['fields'])})")
    parts.append("scene diff:\n" + "\n".join(changes) if changes else "scene diff: no object changes")
    for note in data.get("notes") or []:
        parts.append(f"note: {note}")
    return "\n".join(parts)


# -- handlers -----------------------------------------------------------------

async def exec_tool(ctx: ToolContext, args: dict) -> dict:
    params = {"code": args["code"], "label": args.get("label") or ""}
    try:
        # No time limit: Blender cannot stop code once it runs, so a timeout
        # here would only report as not done what may still complete.
        data = await ctx.connection.call(Method.EXEC, params, timeout=None)
    except BridgeCallError as exc:
        return error_result(exc)
    result = {"content": [text_block(format_exec_result(data))]}
    if data.get("error"):
        result["is_error"] = True
    return result


async def inspect_tool(ctx: ToolContext, args: dict) -> dict:
    params = {"query": args["query"]}
    if args.get("name") is not None:
        params["name"] = args["name"]
    try:
        data = await ctx.connection.call(Method.INSPECT, params)
    except BridgeCallError as exc:
        return error_result(exc)
    notes = data.pop("notes", None) or []
    text = json.dumps(data, indent=1, ensure_ascii=False)
    text += "".join(f"\nnote: {note}" for note in notes)
    return {"content": [text_block(text)]}


async def render_tool(ctx: ToolContext, args: dict) -> dict:
    params = {"mode": args["mode"], "view": args.get("view"), "camera": args.get("camera")}
    if args.get("size") is not None:
        params["size"] = args["size"]
    try:
        data = await ctx.connection.call(Method.RENDER, params)
    except BridgeCallError as exc:
        return error_result(exc)
    path = Path(data["path"])
    source = f"view {params['view']}" if params["view"] is not None else "a custom camera"
    caption = [f"{params['mode']} render from {source}, {data['width']}x{data['height']} px, "
               f"{data.get('ms', 0):.0f} ms", f"image: {path}"]
    caption += [f"note: {note}" for note in data.get("notes") or []]
    content = [text_block("\n".join(caption)), image_block(path)]
    if data.get("strokes_path"):
        content[0]["text"] += f"\nstrokes only (not attached): {data['strokes_path']}"
    return {"content": content}


async def checkpoint_tool(ctx: ToolContext, args: dict) -> dict:
    try:
        data = await ctx.connection.call(Method.CHECKPOINT, {"label": args.get("label") or ""})
    except BridgeCallError as exc:
        return error_result(exc)
    checkpoint = data.get("checkpoint_id")
    objects = ", ".join(data.get("objects") or []) or "no objects"
    text = f"checkpoint {checkpoint} saved ({objects})"
    if data.get("restorable") is False:
        text += "; it cannot be restored"
    else:
        text += "; restore it with mcp__blender__restore_checkpoint"
    text += "".join(f"\nnote: {note}" for note in data.get("notes") or [])
    return {"content": [text_block(text)]}


async def restore_checkpoint_tool(ctx: ToolContext, args: dict) -> dict:
    try:
        data = await ctx.connection.call(Method.RESTORE_CHECKPOINT,
                                         {"checkpoint_id": args["checkpoint_id"]}, timeout=None)
    except BridgeCallError as exc:
        return error_result(exc)
    lines = [f"restored checkpoint {args['checkpoint_id']}: "
             + (", ".join(data.get("restored") or []) or "no objects")]
    if data.get("removed"):
        lines.append("removed (made after the checkpoint): " + ", ".join(data["removed"]))
    lines.append("The restored objects are new datablocks: Python variables from earlier exec "
                 "calls that hold them are stale; look them up again by name.")
    lines += [f"note: {note}" for note in data.get("notes") or []]
    return {"content": [text_block("\n".join(lines))]}


async def request_tool(ctx: ToolContext, args: dict) -> dict:
    if not ctx.bundle_dir:
        return {"content": [text_block("There is no request bundle for this turn.")], "is_error": True}
    root = Path(ctx.bundle_dir)
    if args.get("amend") is not None:
        number = int(args["amend"])
        root = root.parent / f"amend-{number}"
        if not root.is_dir():
            known = sorted(int(p.name[6:]) for p in root.parent.glob("amend-*") if p.name[6:].isdigit())
            return {"content": [text_block(
                f"Amendment {number} has no strokes to read. Amendments with new strokes this turn: "
                f"{', '.join(map(str, known)) or 'none'}. Leave amend out for the turn's own request.")],
                    "is_error": True}
    try:
        bundle = formats.read_bundle(root)
    except formats.FormatError as exc:
        return {"content": [text_block(f"Cannot read the request bundle: {exc}")], "is_error": True}
    return {"content": describe_bundle(bundle)}


POINT_KEYS = ("points", "radius", "opacity", "on_surface", "normal", "hit_object")


def decimate(strokes: list[dict], step: int) -> list[dict]:
    """Keeps every step-th point of each stroke, always both endpoints, with
    the per-point arrays kept aligned."""
    out = []
    for stroke in strokes:
        n = len(stroke["points"])
        keep = list(range(0, n, step))
        if keep[-1] != n - 1:
            keep.append(n - 1)
        out.append({**stroke, **{k: [stroke[k][i] for i in keep] for k in POINT_KEYS}})
    return out


def strokes_text(bundle: formats.Bundle, limit: int = STROKES_TEXT_LIMIT) -> tuple[str, str]:
    """(heading, JSON) for the strokes. A dense sketch is decimated until it
    fits the limit, never cut mid-JSON; the heading then says so and where the
    full data is."""
    strokes = [s.to_json() for s in bundle.strokes]
    text = json.dumps(strokes, separators=(",", ":"))
    heading = f"Strokes ({len(strokes)}, world space)"
    if len(text) <= limit:
        return heading, text
    longest = max(len(s["points"]) for s in strokes)
    step = 2
    while True:
        text = json.dumps(decimate(strokes, step), separators=(",", ":"))
        if len(text) <= limit or step >= longest:
            break
        step *= 2
    full = (bundle.root / "strokes.json").resolve()
    heading += (f", decimated to one point in {step} plus endpoints to fit; the full data is in "
                f"{full} (load it with json in mcp__blender__exec when you need every point)")
    if len(text) > limit:
        # Even two points per stroke is too much: send whole strokes that
        # fit. Each is serialised once, so thousands of strokes cost no more
        # than one pass.
        parts = [json.dumps(s, separators=(",", ":")) for s in decimate(strokes, step)]
        size, count = 2, 0
        for part in parts:
            if size + len(part) + (1 if count else 0) > limit:
                break
            size += len(part) + (1 if count else 0)
            count += 1
        text = "[" + ",".join(parts[:count]) + "]"
        heading += f"; only the first {count} strokes are listed"
    return heading, text


def stroke_summary(bundle: formats.Bundle) -> list[str]:
    lines = []
    for stroke_type in formats.STROKE_TYPES:
        group = [s for s in bundle.strokes if s.type == stroke_type]
        if not group:
            continue
        points = sum(len(s.points) for s in group)
        on = sum(sum(s.on_surface) for s in group)
        view_ids = sorted({s.view for s in group})
        lines.append(f"  {stroke_type}: {len(group)} stroke{'s' if len(group) != 1 else ''}, "
                     f"views {', '.join(map(str, view_ids))}, {on} of {points} points on a surface")
    return lines


def describe_bundle(bundle: formats.Bundle) -> list[dict]:
    req = bundle.request
    lines = [
        f"Request {req.node} (parent {req.parent})" + (f", amendment {req.amend}" if req.amend else ""),
        f"Prompt: {req.prompt or '(none: interpret the sketch)'}",
        "Target: " + (", ".join(f"{t['name']} ({t['type']})" for t in req.target) or "(none: create new objects)"),
        *([f"New objects go in collection '{req.target_collection}'."] if req.target_collection else []),
        f"Stroke types used: {', '.join(req.stroke_types) or 'none'}",
        *stroke_summary(bundle),
        f"Units: {req.units['system']}, scale_length {req.units['scale_length']}",
        f"Settings: {json.dumps(req.settings)}",
    ]
    if not bundle.views and not bundle.strokes:
        lines.append("Sketch: none. There are no strokes, sketch views or overlay images in this "
                     "request. Self-check with mcp__blender__render from cameras you place "
                     "(camera={location, look_at}); view ids and overlay mode need a sketch view.")
    for view_id, view in sorted(bundle.views.items()):
        eye = [row[3] for row in view.camera["matrix_world"][:3]]
        lines.append(f"View {view_id}: {view.width}x{view.height}, {view.camera['type']}, "
                     f"eye at {[round(v, 3) for v in eye]}; strokes only (not attached): "
                     f"{bundle.strokes_png_path(view_id)}")
    heading, strokes = strokes_text(bundle)
    lines.append(f"{heading}:\n{strokes}")

    content = [text_block("\n".join(lines))]
    for view_id in sorted(bundle.views):
        overlay = bundle.overlay_path(view_id)
        if overlay.is_file():
            content.append(text_block(f"View {view_id} overlay (render with strokes composited)\n"
                                      f"image: {overlay}"))
            content.append(image_block(overlay))
    for ref in req.refs:
        path = bundle.root / ref
        if path.suffix.lower() in MIME_TYPES:
            content.append(text_block(f"Reference image {ref}\nimage: {path}"))
            content.append(image_block(path))
    return content


async def ask_tool(ctx: ToolContext, args: dict) -> dict:
    params = {"question": args["question"], "choices": list(args.get("choices") or [])}
    await ctx.event(Event.STATUS, {"state": "waiting_user", "detail": params["question"]})
    try:
        data = await ctx.connection.call(Method.ASK, params, timeout=None)
    except BridgeCallError as exc:
        return error_result(exc)
    finally:
        await ctx.event(Event.STATUS, {"state": "running", "detail": None})
    if data.get("unattended"):
        text = ("The user is not available (unattended run). Go on with your best judgement, and "
                "say in your reply which reading you chose.")
    else:
        text = f"The user answered: {data.get('answer', '')}"
    text += "".join(f"\nnote: {note}" for note in data.get("notes") or [])
    return {"content": [text_block(text)]}


# -- schemas and server wiring ------------------------------------------------

_VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}

EXEC_DESCRIPTION = (
    "Runs Python in the user's live Blender scene; this is where edits happen. Returns stdout, "
    "any exception with a traceback trimmed to your code, and a diff of the scene's objects "
    "(added, removed, and which fields changed). The code runs on Blender's main thread: "
    "Blender is frozen until it returns and it cannot be interrupted, so each call should be "
    "one short step. Variables persist between calls. Already imported: bpy, bmesh, "
    "mathutils, math, Vector, Matrix, and a `whittle` helper. whittle.targets() lists the "
    "target objects. whittle.mesh_report(obj, evaluated=True) measures a mesh in world space, "
    "live modifiers included, and returns a dict: shells, open_edges, bad_verts, "
    "flipped_edges, duplicate_verts, tiny_faces, self_intersections, volume, verts, faces, "
    "tris, quads, ngons and watertight (the whittle:mesh-check skill explains them). "
    "whittle.weld(obj, dist=1e-4) merges near-duplicate vertices, dissolves degenerate faces, "
    "deletes loose vertices and points normals outward on obj's own mesh; it does not fuse "
    "overlapping parts. whittle.view3d_override() is a context manager for the few operators "
    "that need a 3D viewport. bmesh and the data API (bpy.data, object.modifiers, bmesh.ops) "
    "are more dependable here than bpy.ops operators, which need a viewport context that may "
    "not exist. After setting location, rotation_euler or scale, call "
    "bpy.context.view_layer.update() before reading matrix_world, which is stale until then "
    "(a part placed with the stale matrix lands at the origin). stdout is cut at 20,000 "
    "characters, so print summaries rather than whole meshes.")

TOOLS = {
    # name: (server, handler, description, schema, returns images)
    "exec": ("blender", exec_tool, EXEC_DESCRIPTION,
             {"type": "object",
              "properties": {"code": {"type": "string", "description": "Python source to run."},
                             "label": {"type": "string",
                                       "description": "A few words shown to the user in the sidebar "
                                                      "for this step, e.g. 'grow the horns'."}},
              "required": ["code"]}, False),
    "inspect": ("blender", inspect_tool,
                "Reads the scene without changing it and returns JSON. query 'summary' lists every "
                "object in the scene with its type, transform, dimensions, parent, modifiers, "
                "materials, mesh counts and whether it is a target. 'object' describes one object, "
                "named by `name`, in more detail: world-space bounds, modifier settings, vertex "
                "groups, custom properties, colour attributes and UV layers. 'materials' lists "
                "materials with their diffuse and base colours; 'node_groups' lists node groups "
                "with their interface sockets; 'scene' gives the unit settings, render engine, "
                "camera and datablock counts. For mesh health use whittle.mesh_report in exec, "
                "and for anything else print it from exec.",
                {"type": "object",
                 "properties": {"query": {"type": "string",
                                          "enum": ["summary", "object", "materials", "node_groups", "scene"],
                                          "description": "What to read."},
                                "name": {"type": "string",
                                         "description": "The object's name. Needed with query 'object', "
                                                        "ignored otherwise."}},
                 "required": ["query"]}, False),
    "render": ("blender", render_tool,
               "Renders the scene with Workbench and returns the image, so you can see what you "
               "built. Give exactly one of `view` or `camera`. `view` is a sketch view id from the "
               "request, so the render matches what the user saw when they drew. `camera` places "
               "a temporary camera instead, for requests without a sketch, close-ups and other "
               "angles. mode 'shaded' shows material colours (material.diffuse_color) under studio "
               "light; 'wireframe' shows the target meshes as wire, to judge topology; 'matcap' "
               "shows surface shape and shading problems; 'overlay' is shaded with the user's "
               "strokes for this turn drawn on top, and needs a view. The Whittle Sketch itself "
               "never appears in the render.",
               {"type": "object",
                "properties": {"mode": {"type": "string", "enum": list(formats.RENDER_MODES),
                                        "description": "What the render shows."},
                               "view": {"type": "integer",
                                        "description": "A sketch view id from the request."},
                               "camera": {"type": "object",
                                          "description": "A camera you place. Positions are world "
                                                         "space, in metres.",
                                          "properties": {"location": {**_VEC3, "description": "Where the camera is."},
                                                         "look_at": {**_VEC3, "description": "The point it aims at."},
                                                         "lens_mm": {"type": "number", "exclusiveMinimum": 0,
                                                                     "description": "Focal length on a 36 mm "
                                                                                    "sensor; 50 when left out."}},
                                          "required": ["location", "look_at"]},
                               "size": {"type": "integer", "minimum": 64, "maximum": 1024,
                                        "description": "Longest side in pixels; the session's render "
                                                       "size when left out."}},
                "required": ["mode"]}, True),
    "checkpoint": ("blender", checkpoint_tool,
                   "Saves the target objects and the objects you made this turn, with their mesh "
                   "data, materials and node groups, so a later step can be undone with "
                   "restore_checkpoint. Returns an id such as c1. Worth taking before a destructive "
                   "step: applying a boolean, deleting geometry, a remesh. Checkpoints last until "
                   "the end of this turn.",
                   {"type": "object",
                    "properties": {"label": {"type": "string",
                                             "description": "A few words on what comes next, e.g. "
                                                            "'before applying the carve'."}},
                    "required": ["label"]}, False),
    "restore_checkpoint": ("blender", restore_checkpoint_tool,
                           "Puts the objects a checkpoint of this turn saved back as they were: "
                           "their data, materials and node groups return, and objects you made "
                           "after the checkpoint are removed. Other objects in the scene are left "
                           "alone. The restored objects are new datablocks, so variables from "
                           "earlier exec calls that point at them are stale; look them up again "
                           "by name.",
                           {"type": "object",
                            "properties": {"checkpoint_id": {"type": "string",
                                                             "description": "An id checkpoint returned "
                                                                            "this turn, e.g. 'c1'."}},
                            "required": ["checkpoint_id"]}, False),
    "request": ("whittle", request_tool,
                "Returns this turn's request: the prompt, the target objects, the stroke types "
                "used, unit settings, each sketch view's camera, the strokes as world-space points "
                "(with on_surface, and the surface normal and hit_object where a point lies on "
                "geometry), an overlay image per sketch view (the user's strokes over a render from "
                "that view) and any reference images. Call it at the start of every turn. With "
                "`amend`, it returns that amendment's new strokes and views instead.",
                {"type": "object",
                 "properties": {"amend": {"type": "integer", "minimum": 1,
                                          "description": "The number of a user amendment that has "
                                                         "new strokes. Leave it out for the turn's "
                                                         "own request."}}}, True),
    "ask": ("whittle", ask_tool,
            "Asks the user a question in the sidebar and waits for the answer; the turn pauses "
            "until they reply. It fits a real fork, where readings of the sketch or prompt lead to "
            "materially different geometry; routine modeling choices are yours to make. Returns "
            "the user's answer, or says that nobody is there to answer (an unattended run), in "
            "which case go on with your best judgement.",
            {"type": "object",
             "properties": {"question": {"type": "string",
                                         "description": "One short question; the sidebar is narrow."},
                            "choices": {"type": "array", "items": {"type": "string"},
                                        "description": "A few short answers, shown as buttons in one "
                                                       "row. The user can also type a different "
                                                       "answer."}},
             "required": ["question"]}, False),
}

SERVERS = ("blender", "whittle")
TOOL_NAMES = [f"mcp__{server}__{name}" for name, (server, *_rest) in TOOLS.items()]


def short_name(tool_name: str) -> str:
    """mcp__blender__exec -> exec; other names pass through."""
    if tool_name.startswith("mcp__"):
        return tool_name.split("__", 2)[-1]
    return tool_name


def build_servers(ctx: ToolContext) -> dict:
    from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

    by_server: dict[str, list] = {s: [] for s in SERVERS}
    for name, (server, handler, description, schema, images) in TOOLS.items():
        annotations = ToolAnnotations(maxResultSizeChars=IMAGE_RESULT_CHARS) if images else None

        async def run(args, _handler=handler):
            return await ctx.deliver_notes(await _handler(ctx, args))

        by_server[server].append(tool(name, description, schema, annotations)(run))
    return {s: create_sdk_mcp_server(s, tools=tools) for s, tools in by_server.items()}
