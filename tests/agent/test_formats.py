# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from whittle import formats
from whittle.formats import FormatError

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "tests" / "fixtures" / "crate" / "request"


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-formats-"))
        self.copy = self.tmp / "request"
        shutil.copytree(BUNDLE, self.copy)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, name, change):
        path = self.copy / name
        obj = json.loads(path.read_text())
        change(obj)
        path.write_text(json.dumps(obj))

    def test_fixture_reads(self):
        bundle = formats.read_bundle(BUNDLE)
        self.assertEqual(bundle.request.node, "n0001")
        self.assertEqual(bundle.request.target[0]["name"], "Crate")
        self.assertEqual(sorted(bundle.views), [1, 2])
        self.assertEqual([s.type for s in bundle.strokes], ["add", "add", "carve"])
        self.assertTrue(bundle.overlay_path(1).is_file())
        self.assertTrue(bundle.strokes_png_path(2).is_file())
        self.assertAlmostEqual(bundle.views[1].aspect, 800 / 600)

    def test_each_required_request_key(self):
        for key in ["node", "parent", "prompt", "amend", "target", "stroke_types", "views",
                    "refs", "units", "settings", "format", "version"]:
            with self.subTest(key=key):
                original = (self.copy / "request.json").read_text()
                self.edit("request.json", lambda o: o.pop(key))
                with self.assertRaises(FormatError) as cm:
                    formats.read_bundle(self.copy)
                self.assertIn("request.json", str(cm.exception))
                self.assertIn(key, str(cm.exception))
                (self.copy / "request.json").write_text(original)

    def test_each_required_stroke_key(self):
        for key in ["index", "type", "view", "cyclic", "points", "radius", "opacity",
                    "on_surface", "normal", "hit_object"]:
            with self.subTest(key=key):
                original = (self.copy / "strokes.json").read_text()
                self.edit("strokes.json", lambda o: o["strokes"][1].pop(key))
                with self.assertRaises(FormatError) as cm:
                    formats.read_bundle(self.copy)
                self.assertIn("strokes[1]", str(cm.exception))
                self.assertIn(key, str(cm.exception))
                (self.copy / "strokes.json").write_text(original)

    def test_each_required_camera_key(self):
        for key in ["id", "view_matrix", "window_matrix", "is_perspective", "width", "height",
                    "from_camera", "camera"]:
            with self.subTest(key=key):
                path = self.copy / "views" / "2" / "camera.json"
                original = path.read_text()
                self.edit("views/2/camera.json", lambda o: o.pop(key))
                with self.assertRaises(FormatError) as cm:
                    formats.read_bundle(self.copy)
                self.assertIn("camera.json", str(cm.exception))
                self.assertIn(key, str(cm.exception))
                path.write_text(original)

    def test_bad_values(self):
        cases = [
            ("request.json", lambda o: o.update(format="whittle.other")),
            ("request.json", lambda o: o.update(version=2)),
            ("request.json", lambda o: o.update(stroke_types=["scribble"])),
            ("request.json", lambda o: o.update(views=[1, 2, 3])),
            ("request.json", lambda o: o.update(refs=["refs/missing.png"])),
            ("request.json", lambda o: o.update(refs=["/etc/hostname"])),
            ("request.json", lambda o: o.update(refs=["refs/../../outside.png"])),
            ("request.json", lambda o: o["units"].pop("scale_length")),
            ("strokes.json", lambda o: o["strokes"][0].update(view=5)),
            ("strokes.json", lambda o: o["strokes"][0]["radius"].pop()),
            ("strokes.json", lambda o: o["strokes"][0].update(points=[])),
            ("strokes.json", lambda o: o["strokes"][0].update(cyclic=1)),
            ("views/1/camera.json", lambda o: o.update(id=3)),
            ("views/1/camera.json", lambda o: o["view_matrix"].pop()),
            ("views/1/camera.json", lambda o: o["camera"].update(type="FISHEYE")),
        ]
        for name, change in cases:
            with self.subTest(name=name):
                original = (self.copy / name).read_text()
                self.edit(name, change)
                with self.assertRaises(FormatError):
                    formats.read_bundle(self.copy)
                (self.copy / name).write_text(original)

    def test_missing_folder_and_bad_json(self):
        with self.assertRaises(FormatError):
            formats.read_bundle(self.tmp / "nope")
        (self.copy / "strokes.json").write_text("{")
        with self.assertRaises(FormatError):
            formats.read_bundle(self.copy)

    def test_write_then_read_round_trip(self):
        bundle = formats.read_bundle(BUNDLE)
        out = self.tmp / "written"
        request = copy.deepcopy(bundle.request)
        request.prompt = "Round trip ✓"
        formats.write_request(out, request, bundle.strokes, list(bundle.views.values()))
        again = formats.read_bundle(out)
        self.assertEqual(again.request, request)
        self.assertEqual(again.strokes, bundle.strokes)
        self.assertEqual(again.views, bundle.views)

    def test_target_collection_is_optional(self):
        self.assertIsNone(formats.read_bundle(BUNDLE).request.target_collection, "an older bundle")
        for value in ("Whittle Target", None):
            with self.subTest(value=value):
                self.edit("request.json", lambda o: o.update(target_collection=value))
                self.assertEqual(formats.read_bundle(self.copy).request.target_collection, value)
        self.edit("request.json", lambda o: o.update(target_collection=3))
        with self.assertRaises(FormatError) as cm:
            formats.read_bundle(self.copy)
        self.assertIn("target_collection", str(cm.exception))

    def test_target_collection_round_trips(self):
        bundle = formats.read_bundle(BUNDLE)
        request = copy.deepcopy(bundle.request)
        request.target_collection = "Whittle Target"
        out = self.tmp / "written"
        formats.write_request(out, request, bundle.strokes, list(bundle.views.values()))
        self.assertEqual(formats.read_bundle(out).request.target_collection, "Whittle Target")

    def test_atomic_write_leaves_no_temp_files(self):
        formats.write_json_atomic(self.tmp / "a" / "x.json", {"k": 1})
        self.assertEqual([p.name for p in (self.tmp / "a").iterdir()], ["x.json"])
        with self.assertRaises(TypeError):
            formats.write_json_atomic(self.tmp / "a" / "y.json", {"k": object()})
        self.assertEqual([p.name for p in (self.tmp / "a").iterdir()], ["x.json"])


class SessionDirTest(unittest.TestCase):
    def test_paths_and_render_sequence(self):
        root = Path(tempfile.mkdtemp(prefix="whittle-session-"))
        try:
            s = formats.SessionDir(root)
            self.assertEqual(s.request_dir("n0001"), root / "nodes" / "n0001" / "request")
            self.assertEqual(s.transcript_path("n0002").name, "transcript.jsonl")
            first = s.next_render_path("n0001", 1, "overlay")
            self.assertEqual(first.name, "001-v1-overlay.png")
            first.write_bytes(b"")
            (first.parent / "001-v1-overlay-strokes.png").write_bytes(b"")
            self.assertEqual(s.next_render_path("n0001", None, "shaded").name, "002-cam-shaded.png")
            self.assertEqual(formats.node_id(7), "n0007")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_amend_checkpoint_and_node_paths(self):
        root = Path(tempfile.mkdtemp(prefix="whittle-session-"))
        try:
            s = formats.SessionDir(root)
            self.assertEqual(s.amend_dir("n0003", 2), root / "nodes" / "n0003" / "amend-2")
            blend, manifest = s.checkpoint_paths("n0003", "start")
            self.assertEqual(blend, root / "nodes" / "n0003" / "checkpoints" / "start.blend")
            self.assertEqual(manifest, blend.with_suffix(".json"))
            self.assertEqual(s.node_ids(), [])
            for name in ("n0010", "n0002", "notes", ".n0003.tmp"):
                (root / "nodes" / name).mkdir(parents=True)
            self.assertEqual(s.node_ids(), ["n0002", "n0010"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_history_paths(self):
        s = formats.SessionDir("/s")
        self.assertEqual(s.session_path(), Path("/s/session.json"))
        self.assertEqual(s.target_blend("n0002"), Path("/s/nodes/n0002/target.blend"))
        self.assertEqual(s.target_blend("n0002").with_suffix(".json").name, "target.json")
        self.assertEqual(s.thumb_path("n0002"), Path("/s/nodes/n0002/thumb.png"))
        self.assertEqual(s.compare_dir(), Path("/s/compare"))
        self.assertEqual(s.checkpoint_paths("n0002", "c1")[0].name, "c1.blend")


def target_manifest():
    return {
        "format": formats.TARGET_FORMAT, "version": 1,
        "objects": [{"uid": "abc", "name": "Crate", "type": "MESH", "data_name": "Crate",
                     "collections": ["Props"], "parent": None, "parent_uid": None,
                     "materials": ["Wood", None], "node_groups": ["GN"]}],
        "datablocks": {"materials": ["Wood"], "node_groups": ["GN"], "images": []},
    }


class TargetManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-target-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_round_trip(self):
        path = self.tmp / "checkpoints" / "start.json"
        formats.write_target_manifest(path, target_manifest())
        self.assertEqual(formats.read_target_manifest(path), target_manifest())

    def test_validation_errors(self):
        cases = {
            "format": lambda m: m.update(format="whittle.request"),
            "objects": lambda m: m.pop("objects"),
            "data_name": lambda m: m["objects"][0].update(data_name=3),
            "materials": lambda m: m["objects"][0].update(materials=[1]),
            "node_groups": lambda m: m["objects"][0].update(node_groups=[None]),
            "images": lambda m: m["datablocks"].pop("images"),
        }
        for key, change in cases.items():
            with self.subTest(key=key):
                manifest = target_manifest()
                change(manifest)
                with self.assertRaises(FormatError) as cm:
                    formats.write_target_manifest(self.tmp / "t.json", manifest)
                self.assertIn(key, str(cm.exception))
        self.assertFalse((self.tmp / "t.json").exists())
        (self.tmp / "bad.json").write_text(json.dumps({**target_manifest(), "version": 9}))
        with self.assertRaises(FormatError):
            formats.read_target_manifest(self.tmp / "bad.json")
