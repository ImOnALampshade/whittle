# SPDX-License-Identifier: GPL-3.0-or-later
import base64
import json
import time
import unittest
from pathlib import Path

from tests.agent.fakes import StubConnection
from whittle import formats
from whittle.agent import tools
from whittle.agent.connection import BridgeCallError
from whittle.agent.tools import ToolContext

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "tests" / "fixtures" / "crate" / "request"
PNG = BUNDLE / "views" / "1" / "overlay.png"

EXEC_DATA = {"stdout": "4\n", "error": None,
             "diff": {"added": ["Crate_Lid"], "removed": [], "changed": [{"name": "Crate", "fields": ["location"]}]},
             "notes": ["the user edited the target"]}


def make_stroke(index, n):
    return {"index": index, "type": "free", "view": 1, "cyclic": False,
            "points": [[i * 0.001, 0.5, 0.25] for i in range(n)],
            "radius": [i * 1e-6 for i in range(n)], "opacity": [1.0] * n,
            "on_surface": [False] * n, "normal": [None] * n, "hit_object": [None] * n}


def texts(result):
    return "\n".join(b["text"] for b in result["content"] if b["type"] == "text")


class ToolHandlerTest(unittest.IsolatedAsyncioTestCase):
    def ctx(self, **responses):
        return ToolContext(StubConnection(responses), turn_id="n0001", bundle_dir=str(BUNDLE))

    async def test_exec_formats_everything(self):
        ctx = self.ctx(exec=EXEC_DATA)
        result = await tools.exec_tool(ctx, {"code": "print(2 + 2)"})
        self.assertNotIn("is_error", result)
        text = texts(result)
        for part in ("stdout:\n4", "added: Crate_Lid", "changed: Crate (location)", "note: the user edited"):
            self.assertIn(part, text)
        self.assertEqual(ctx.connection.calls, [("exec", {"code": "print(2 + 2)", "label": ""}, None)],
                         "Blender cannot stop running code, so the agent never gives up on it")

    async def test_exec_code_error_is_an_error_result(self):
        data = {**EXEC_DATA, "error": {"type": "ValueError", "message": "nope", "traceback": "Traceback..."}}
        result = await tools.exec_tool(self.ctx(exec=data), {"code": "x", "label": "l"})
        self.assertTrue(result["is_error"])
        self.assertIn("error: ValueError: nope", texts(result))

    async def test_bridge_error_becomes_error_result(self):
        result = await tools.inspect_tool(self.ctx(inspect=BridgeCallError("not_found", "no Foo")),
                                          {"query": "object", "name": "Foo"})
        self.assertTrue(result["is_error"])
        self.assertIn("not_found", texts(result))

    async def test_inspect_returns_json(self):
        ctx = self.ctx(inspect={"objects": [{"name": "Crate"}]})
        result = await tools.inspect_tool(ctx, {"query": "summary"})
        self.assertEqual(json.loads(texts(result)), {"objects": [{"name": "Crate"}]})
        self.assertEqual(ctx.connection.calls[0][1], {"query": "summary"})

    async def test_render_returns_the_image(self):
        data = {"path": str(PNG), "strokes_path": "/x/strokes.png", "width": 512, "height": 384, "ms": 80.0}
        ctx = self.ctx(render=data)
        result = await tools.render_tool(ctx, {"mode": "overlay", "view": 1})
        images = [b for b in result["content"] if b["type"] == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(images[0]["data"]), PNG.read_bytes())
        self.assertEqual(tools.image_paths(texts(result)), [str(PNG)])
        self.assertIn("512x384", texts(result))
        self.assertEqual(ctx.connection.calls[0][1], {"mode": "overlay", "view": 1, "camera": None})

    async def test_checkpoint(self):
        result = await tools.checkpoint_tool(self.ctx(checkpoint={"checkpoint_id": "c1", "restorable": False}),
                                             {"label": "before carve"})
        self.assertIn("c1", texts(result))
        self.assertIn("cannot be restored", texts(result))
        data = {"checkpoint_id": "c2", "label": "lid", "restorable": True,
                "objects": ["Crate", "Crate_Lid"], "notes": ["the user edited the target"]}
        ctx = self.ctx(checkpoint=data)
        result = await tools.checkpoint_tool(ctx, {"label": "lid"})
        self.assertEqual(texts(result).splitlines()[0],
                         "checkpoint c2 saved (Crate, Crate_Lid); restore it with "
                         "mcp__blender__restore_checkpoint")
        self.assertIn("note: the user edited the target", texts(result))
        self.assertEqual(ctx.connection.calls[0][:2], ("checkpoint", {"label": "lid"}))

    async def test_restore_checkpoint(self):
        ctx = self.ctx(restore_checkpoint={"restored": ["Crate"], "removed": ["Crate_Lid"], "notes": []})
        result = await tools.restore_checkpoint_tool(ctx, {"checkpoint_id": "c1"})
        text = texts(result)
        self.assertNotIn("is_error", result)
        self.assertIn("restored checkpoint c1: Crate", text)
        self.assertIn("removed (made after the checkpoint): Crate_Lid", text)
        self.assertIn("stale", text)
        self.assertEqual(ctx.connection.calls[0], ("restore_checkpoint", {"checkpoint_id": "c1"}, None))
        missing = self.ctx(restore_checkpoint=BridgeCallError("not_found", "no checkpoint c9"))
        result = await tools.restore_checkpoint_tool(missing, {"checkpoint_id": "c9"})
        self.assertTrue(result["is_error"])
        self.assertIn("not_found", texts(result))

    async def test_request_reads_the_bundle_from_disk(self):
        ctx = self.ctx()
        result = await tools.request_tool(ctx, {})
        text = texts(result)
        self.assertIn("handle slot", text)
        self.assertIn("Strokes (3, world space)", text)
        self.assertIn("Crate (MESH)", text)
        self.assertEqual(sum(b["type"] == "image" for b in result["content"]), 2)
        self.assertEqual(ctx.connection.calls, [], "the bundle is read without the bridge")

    async def test_request_summarises_each_stroke_type(self):
        text = texts(await tools.request_tool(self.ctx(), {}))
        self.assertIn("  add: 2 strokes, views 1, 2, 0 of 31 points on a surface", text)
        self.assertIn("  carve: 1 stroke, views 2, 14 of 14 points on a surface", text)
        self.assertIn(f"strokes only (not attached): {BUNDLE / 'views' / '1' / 'strokes.png'}", text)
        self.assertFalse(any(p.endswith("strokes.png") for p in tools.image_paths(text)),
                         "strokes.png is named, not attached")

    async def test_small_bundles_are_not_decimated(self):
        text = texts(await tools.request_tool(self.ctx(), {}))
        bundle = formats.read_bundle(BUNDLE)
        payload = text.split("Strokes (3, world space):\n", 1)[1].split("\n", 1)[0]
        self.assertEqual(payload, json.dumps([s.to_json() for s in bundle.strokes], separators=(",", ":")))

    def test_dense_strokes_are_decimated_into_valid_json(self):
        bundle = formats.read_bundle(BUNDLE)
        long = make_stroke(0, 20_000)
        short = make_stroke(1, 10)
        bundle.strokes = [formats.Stroke.from_json(long), formats.Stroke.from_json(short)]
        text = tools.describe_bundle(bundle)[0]["text"]
        heading, payload = text.split("Strokes (2, world space", 1)[1].split(":\n", 1)
        self.assertLessEqual(len(payload), tools.STROKES_TEXT_LIMIT)
        self.assertIn("decimated", heading)
        self.assertIn(str((BUNDLE / "strokes.json").resolve()), heading)
        got = json.loads(payload)
        self.assertEqual(len(got), 2)
        for stroke, original in zip(got, (long, short)):
            n = len(stroke["points"])
            self.assertGreaterEqual(n, 2)
            self.assertLess(n, len(original["points"]) + 1)
            self.assertEqual(stroke["points"][0], original["points"][0])
            self.assertEqual(stroke["points"][-1], original["points"][-1])
            for key in tools.POINT_KEYS:
                self.assertEqual(len(stroke[key]), n, key)
            # Every kept point carries its own per-point values.
            index = int(round(stroke["radius"][1] * 1e6))
            self.assertEqual(stroke["points"][1], original["points"][index])
        self.assertLess(len(got[0]["points"]), 20_000)

    def test_too_many_strokes_are_cut_to_whole_ones_that_fit(self):
        bundle = formats.read_bundle(BUNDLE)
        bundle.strokes = [formats.Stroke.from_json(make_stroke(i, 2)) for i in range(5000)]
        started = time.monotonic()
        heading, payload = tools.strokes_text(bundle, limit=100_000)
        self.assertLess(time.monotonic() - started, 2.0, "one pass, not one dump per stroke dropped")
        self.assertLessEqual(len(payload), 100_000)
        kept = json.loads(payload)
        self.assertGreater(len(kept), 0)
        self.assertLess(len(kept), 5000)
        self.assertIn(f"only the first {len(kept)} strokes are listed", heading)
        self.assertEqual(kept[0]["points"], bundle.strokes[0].to_json()["points"])

    def test_summary_says_when_there_is_no_sketch(self):
        bundle = formats.read_bundle(BUNDLE)
        self.assertNotIn("Sketch: none", tools.describe_bundle(bundle)[0]["text"])
        bundle.strokes, bundle.views = [], {}
        content = tools.describe_bundle(bundle)
        self.assertIn("Sketch: none. There are no strokes, sketch views or overlay images",
                      content[0]["text"])
        self.assertFalse(any("overlay (render" in c.get("text", "") for c in content))

    def test_summary_names_the_target_collection_only_when_set(self):
        bundle = formats.read_bundle(BUNDLE)
        self.assertNotIn("New objects go in", tools.describe_bundle(bundle)[0]["text"])
        bundle.request.target_collection = "Whittle Target"
        self.assertIn("New objects go in collection 'Whittle Target'.",
                      tools.describe_bundle(bundle)[0]["text"])

    async def test_request_errors(self):
        ctx = ToolContext(StubConnection(), bundle_dir=None)
        self.assertTrue((await tools.request_tool(ctx, {}))["is_error"])
        ctx.bundle_dir = str(BUNDLE)
        missing = await tools.request_tool(ctx, {"amend": 1})
        self.assertTrue(missing["is_error"])
        self.assertIn("Amendments with new strokes this turn: none", texts(missing))

    async def test_ask_waits_without_timeout(self):
        ctx = self.ctx(ask={"answer": "yes"})
        result = await tools.ask_tool(ctx, {"question": "Bevel?", "choices": ["yes", "no"]})
        self.assertIn("The user answered: yes", texts(result))
        self.assertEqual(ctx.connection.calls, [("ask", {"question": "Bevel?", "choices": ["yes", "no"]}, None)])
        states = [d["state"] for name, d in ctx.connection.events if name == "status"]
        self.assertEqual(states, ["waiting_user", "running"])
        self.assertEqual(ctx.connection.events[0][1]["turn_id"], "n0001")

    async def test_ask_prints_blender_notes(self):
        ctx = self.ctx(ask={"answer": "yes", "notes": ["The user edited the target"]})
        result = await tools.ask_tool(ctx, {"question": "Bevel?"})
        self.assertIn("The user answered: yes\nnote: The user edited the target", texts(result))

    async def test_ask_unattended(self):
        result = await tools.ask_tool(self.ctx(ask={"answer": "", "unattended": True}), {"question": "?"})
        self.assertIn("not available", texts(result))


class ServerTest(unittest.IsolatedAsyncioTestCase):
    def test_tool_names(self):
        self.assertEqual(tools.TOOL_NAMES, [
            "mcp__blender__exec", "mcp__blender__inspect", "mcp__blender__render",
            "mcp__blender__checkpoint", "mcp__blender__restore_checkpoint", "mcp__whittle__request",
            "mcp__whittle__ask"])
        self.assertEqual(tools.short_name("mcp__blender__exec"), "exec")

    def test_tools_are_documented_for_the_model(self):
        def properties(schema):
            for key, prop in (schema.get("properties") or {}).items():
                yield key, prop
                yield from properties(prop)

        for name, (_server, _handler, description, schema, _images) in tools.TOOLS.items():
            with self.subTest(tool=name):
                self.assertGreaterEqual(description.count(". "), 2, "a few sentences, not a label")
                for key, prop in properties(schema):
                    self.assertTrue(prop.get("description"), f"{name}.{key} is described")
                    self.assertNotIn(key, ("reasoning", "thinking", "explanation"),
                                     "no field asks for the model's reasoning")
        self.assertEqual(tools.short_name("Skill"), "Skill")

    async def test_servers_expose_exactly_the_tools_with_schemas(self):
        from claude_agent_sdk._internal.sdk_mcp_bridge import SdkMcpBridge

        servers = tools.build_servers(ToolContext(StubConnection({"exec": EXEC_DATA})))
        self.assertEqual(set(servers), {"blender", "whittle"})
        listed = []
        for key, config in servers.items():
            bridge = SdkMcpBridge(key, config["instance"])
            await bridge.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
            reply = await bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            for t in reply["result"]["tools"]:
                listed.append(f"mcp__{key}__{t['name']}")
                if t["name"] in ("render", "request"):
                    self.assertEqual(t["_meta"]["anthropic/maxResultSizeChars"], tools.IMAGE_RESULT_CHARS)
            if key == "blender":
                ok = await bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                          "params": {"name": "exec", "arguments": {"code": "x"}}})
                self.assertFalse(ok["result"]["isError"])
                bad = await bridge.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                           "params": {"name": "render", "arguments": {"mode": "toon"}}})
                self.assertTrue(bad["result"]["isError"])
            await bridge.aclose()
        self.assertEqual(sorted(listed), sorted(tools.TOOL_NAMES))


class NotesTest(unittest.IsolatedAsyncioTestCase):
    def ctx(self, **responses):
        return ToolContext(StubConnection(responses), turn_id="n0001", bundle_dir=str(BUNDLE))

    async def test_amendments_ride_on_any_result_once(self):
        ctx = self.ctx()
        ctx.queue_amend(1, "Make it taller", "/s/nodes/n0001/amend-1")
        ctx.queue_amend(2, "", None)
        result = await ctx.deliver_notes({"content": [tools.text_block("Blender error")], "is_error": True})
        self.assertTrue(result["is_error"])
        notes = [b["text"] for b in result["content"][1:]]
        self.assertEqual(notes, [
            "<user_amendment>\nUser amendment 1: Make it taller\n"
            "New strokes: call mcp__whittle__request with amend=1 to see them.\n</user_amendment>",
            "<user_amendment>\nUser amendment 2: (new strokes only)\n</user_amendment>"])
        self.assertEqual([(n, d["amend"], d["via"], d["turn_id"]) for n, d in ctx.connection.events],
                         [("amend_delivered", 1, "tool_result", "n0001"),
                          ("amend_delivered", 2, "tool_result", "n0001")])
        self.assertEqual(ctx.amends, [])
        again = await ctx.deliver_notes({"content": []})
        self.assertEqual(again["content"], [])

    async def test_inspect_prints_blender_notes(self):
        ctx = self.ctx(inspect={"objects": [], "notes": ["The user edited the target"]})
        text = texts(await tools.inspect_tool(ctx, {"query": "summary"}))
        body, note = text.rsplit("\n", 1)
        self.assertEqual(json.loads(body), {"objects": []})
        self.assertEqual(note, "note: The user edited the target")

    async def test_render_prints_blender_notes(self):
        data = {"path": str(PNG), "strokes_path": None, "width": 8, "height": 8, "ms": 1.0,
                "notes": ["The user edited the target"]}
        text = texts(await tools.render_tool(self.ctx(render=data), {"mode": "shaded", "view": 1}))
        self.assertIn("note: The user edited the target", text)
        self.assertEqual(tools.image_paths(text), [str(PNG)])

    async def test_exec_notes_are_unchanged(self):
        text = texts(await tools.exec_tool(self.ctx(exec=EXEC_DATA), {"code": "x"}))
        self.assertTrue(text.endswith("note: the user edited the target"))

    async def test_server_tools_deliver_amendments(self):
        from claude_agent_sdk._internal.sdk_mcp_bridge import SdkMcpBridge

        ctx = self.ctx(exec=EXEC_DATA)
        server = tools.build_servers(ctx)["blender"]
        bridge = SdkMcpBridge("blender", server["instance"])
        await bridge.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
        ctx.queue_amend(1, "taller", None)
        reply = await bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "exec", "arguments": {"code": "x"}}})
        self.assertEqual(reply["result"]["content"][-1]["text"],
                         "<user_amendment>\nUser amendment 1: taller\n</user_amendment>")
        await bridge.aclose()
