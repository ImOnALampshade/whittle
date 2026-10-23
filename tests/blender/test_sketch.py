# SPDX-License-Identifier: GPL-3.0-or-later
import math
import unittest
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

from tests.blender.helpers import CRATE_BUNDLE
from tests.blender.sketch_helpers import add_stroke, fake_viewport, look_at_view
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import render, sketch, views


def remove_sketch():
    obj = sketch.find_sketch_object()
    if obj is not None:
        bpy.data.objects.remove(obj)


class SketchTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.bundle = formats.read_bundle(CRATE_BUNDLE)

    def test_load_strokes_from_fixture(self):
        obj = sketch.load_strokes(bpy.context.scene, self.bundle.strokes)
        self.assertEqual(obj.name, sketch.SKETCH_NAME)
        self.assertEqual(sorted(l.name for l in obj.data.layers), ["add", "carve"])
        loaded = sketch.read_strokes(obj)
        expected = [{"type": s.type, "view": s.view, "points": s.points} for s in self.bundle.strokes]
        self.assertEqual(len(loaded), len(expected))
        for got, want in zip(sorted(loaded, key=lambda s: (s["type"], s["view"])),
                             sorted(expected, key=lambda s: (s["type"], s["view"]))):
            self.assertEqual((got["type"], got["view"]), (want["type"], want["view"]))
            for p, q in zip(got["points"], want["points"]):
                for a, b in zip(p, q):
                    self.assertAlmostEqual(a, b, places=5)

    def test_layers_are_unlit_and_tinted(self):
        obj = sketch.load_strokes(bpy.context.scene, self.bundle.strokes)
        layer = obj.data.layers["carve"]
        self.assertFalse(layer.use_lights)
        self.assertEqual(layer.tint_factor, 1.0)
        self.assertAlmostEqual(layer.tint_color[0], sketch.LAYER_COLOURS["carve"][0], places=5)

    def test_reloading_replaces_strokes(self):
        sketch.load_strokes(bpy.context.scene, self.bundle.strokes)
        obj = sketch.load_strokes(bpy.context.scene, self.bundle.strokes[:1])
        self.assertEqual(len(sketch.read_strokes(obj)), 1)
        self.assertEqual(len([o for o in bpy.data.objects if o.name.startswith(sketch.SKETCH_NAME)]), 1)


class LayersTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.scene = bpy.context.scene

    def test_ensure_sketch_layers(self):
        obj = sketch.ensure_sketch_layers(self.scene)
        gp = obj.data
        self.assertEqual([l.name for l in gp.layers], list(formats.STROKE_TYPES))
        for layer in gp.layers:
            self.assertEqual(tuple(round(c, 5) for c in layer.tint_color),
                             tuple(round(c, 5) for c in sketch.LAYER_COLOURS[layer.name]))
            self.assertEqual(layer.tint_factor, 1.0)
            self.assertFalse(layer.use_lights)
            self.assertEqual([f.frame_number for f in layer.frames], [sketch.SKETCH_FRAME])
        self.assertEqual(gp.layers.active.name, "free")
        again = sketch.ensure_sketch_layers(self.scene)
        self.assertIs(again, obj)
        self.assertEqual(len(gp.layers), 6)
        self.assertEqual(len(gp.materials), 1)

    def test_sketch_does_not_depend_on_the_playhead(self):
        remove_sketch()
        self.scene.frame_set(10)
        try:
            obj = sketch.ensure_sketch_layers(self.scene)
            add_stroke(obj, "free", [(0, 0, 0), (1, 0, 0)])
            for frame in (1, 10, 20):
                self.scene.frame_set(frame)
                sketch.ensure_sketch_layers(self.scene)
                self.assertEqual(len(list(sketch.iter_strokes(obj))), 1, f"at frame {frame}")
                self.assertEqual(len(obj.data.layers["free"].frames), 1)
            self.scene.frame_set(1)
            self.assertEqual(sketch.stamp_strokes(obj, 4), 1)
            self.assertEqual(sketch.remove_turn_strokes(obj, 4), 1)
        finally:
            self.scene.frame_set(1)

    def test_layer_keyed_elsewhere_moves_to_the_sketch_key(self):
        remove_sketch()
        obj = sketch.ensure_sketch_object(self.scene)
        layer = obj.data.layers.new("add")
        layer.frames.new(7).drawing.add_strokes([2])
        layer.frames.new(9)
        sketch.ensure_sketch_layers(self.scene)
        self.assertEqual([f.frame_number for f in layer.frames], [sketch.SKETCH_FRAME])
        self.assertEqual(len(list(sketch.iter_strokes(obj))), 1)

    def test_active_type(self):
        obj = sketch.ensure_sketch_layers(self.scene)
        sketch.set_active_type(obj, "carve")
        self.assertEqual(obj.data.layers.active.name, "carve")
        self.assertEqual(sketch.active_type(obj), "carve")
        self.assertEqual(sketch.next_type(obj), "crease")
        sketch.set_active_type(obj, "note")
        self.assertEqual(sketch.next_type(obj), "free")
        with self.assertRaises(ValueError):
            sketch.set_active_type(obj, "sparkle")

    def test_region_strokes_are_filled(self):
        obj = sketch.ensure_sketch_layers(self.scene)
        circle = [(0.3 * math.cos(a), 0.0, 0.3 * math.sin(a) + 0.3)
                  for a in (2 * math.pi * i / 24 for i in range(24))]
        add_stroke(obj, "region", circle, cyclic=True)
        add_stroke(obj, "region", [(p[0] * 0.3 + 0.6, p[1], p[2]) for p in circle], cyclic=True)
        self.assertEqual(sketch.ensure_region_fills(obj), 2)
        drawing = obj.data.layers["region"].frames[0].drawing
        self.assertEqual([s.fill_id for s in drawing.strokes], [1, 2])
        self.assertEqual(sketch.ensure_region_fills(obj), 0)

        view = look_at_view(1, (0, -2, 0.3), (0, 0, 0.3))
        out = render.render(self.scene, view.camera, "overlay", 128,
                            self._tmp() / "region.png", aspect=view.aspect, sketch=obj)
        strokes = render.load_pixels(out["strokes_path"])
        x, y = views.to_pixel(view, (0.0, 0.0, 0.3), out["width"], out["height"])
        centre = strokes[out["height"] - 1 - int(y), int(x)]
        self.assertAlmostEqual(centre[3], sketch.FILL_ALPHA, delta=0.05)
        self.assertGreater(centre[2], centre[0], "the fill is region blue")

    def _tmp(self):
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp(prefix="whittle-sketch-"))
        self.addCleanup(__import__("shutil").rmtree, path, True)
        return path


class StrokeDataTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        remove_sketch()
        self.obj = sketch.ensure_sketch_layers(bpy.context.scene)

    def views_of(self):
        return [(s.layer, s.view) for s in sketch.iter_strokes(self.obj, include_hidden=True)]

    def test_tagging(self):
        add_stroke(self.obj, "free", [(0, 0, 0), (1, 0, 0)])
        add_stroke(self.obj, "carve", [(0, 0, 0), (0, 1, 0)])
        self.assertEqual(len(sketch.untagged(self.obj)), 2)
        self.assertEqual(sketch.tag_strokes(self.obj, 3), 2)
        add_stroke(self.obj, "free", [(0, 0, 1), (1, 0, 1)])
        self.assertEqual(sketch.tag_strokes(self.obj, 4), 1)
        self.assertEqual(self.views_of(), [("free", 3), ("free", 4), ("carve", 3)])
        self.assertEqual(sketch.used_views(self.obj), {3, 4})

    def test_tags_follow_reordered_strokes(self):
        add_stroke(self.obj, "free", [(0, 0, 0), (1, 0, 0)], view=2)
        add_stroke(self.obj, "free", [(0, 0, 1), (1, 0, 1), (2, 0, 1)])
        # The draw tool can insert a stroke first (draw on back).
        drawing = self.obj.data.layers["free"].frames[0].drawing
        drawing.reorder_strokes(new_indices=[1, 0])
        self.assertEqual(sketch.tag_strokes(self.obj, 5), 1)
        got = [(len(s.points), s.view) for s in sketch.iter_strokes(self.obj)]
        self.assertEqual(sorted(got), [(2, 2), (3, 5)])

    def test_stamp_and_remove(self):
        for i in range(3):
            add_stroke(self.obj, "add", [(i, 0, 0), (i, 1, 0)], view=1)
        self.assertEqual(sketch.stamp_strokes(self.obj, 7), 3)
        pending = [(0.5, 0.5, 0.5), (0.6, 0.5, 0.5)]
        add_stroke(self.obj, "add", pending, view=2)
        self.assertEqual(sketch.remove_turn_strokes(self.obj, 7), 3)
        left = list(sketch.iter_strokes(self.obj))
        self.assertEqual(len(left), 1)
        self.assertEqual((left[0].view, left[0].turn), (2, 0))
        for got, want in zip(left[0].points, pending):
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, places=6)

    def stamps(self):
        return [(s.layer, s.turn, s.amend) for s in sketch.iter_strokes(self.obj, include_hidden=True)]

    def test_amendment_stamps(self):
        add_stroke(self.obj, "add", [(0, 0, 0), (0, 1, 0)], view=1)
        sketch.stamp_strokes(self.obj, 3)
        add_stroke(self.obj, "free", [(1, 0, 0), (1, 1, 0)], view=1)
        add_stroke(self.obj, "crease", [(2, 0, 0), (2, 1, 0)], view=1)
        self.obj.data.layers["crease"].hide = True
        self.assertEqual(sketch.stroke_counts(self.obj), {3: 1, 0: 1}, "hidden layers are not counted")
        self.assertEqual(sketch.pending_count(self.obj), 1)
        self.assertEqual(sketch.stamp_pending(self.obj, 3, 1), 1, "hidden strokes are not sent")
        self.assertEqual(self.stamps(), [("free", 3, 1), ("add", 3, 0), ("crease", 0, 0)])
        self.assertEqual(sketch.unstamp_amend(self.obj, 3, 1), 1)
        self.assertEqual(self.stamps(), [("free", 0, 0), ("add", 3, 0), ("crease", 0, 0)])
        sketch.stamp_pending(self.obj, 3, 2)
        # A failed turn's strokes are sent again as the next turn's own.
        sketch.stamp_strokes(self.obj, 4)
        self.assertEqual(self.stamps(), [("free", 4, 0), ("add", 4, 0), ("crease", 0, 0)])
        self.assertEqual(sketch.remove_turn_strokes(self.obj, 4), 2)

    def test_isolate_hides_and_restores(self):
        add_stroke(self.obj, "free", [(0, 0, 0), (0, 1, 0)], turn=1)
        add_stroke(self.obj, "free", [(1, 0, 0), (1, 1, 0)])
        add_stroke(self.obj, "region", [(0, 0, 0), (1, 0, 0), (1, 1, 0)], turn=1)
        add_stroke(self.obj, "region", [(0, 0, 1), (1, 0, 1), (1, 1, 1)])
        sketch.ensure_region_fills(self.obj)
        free = self.obj.data.layers["free"].frames[0].drawing
        region = self.obj.data.layers["region"].frames[0].drawing
        self.assertIsNone(free.attributes.get("hide_stroke"))
        fills = [d.value for d in region.attributes["fill_id"].data]
        with sketch.isolate_strokes(self.obj, lambda turn, amend: turn == 1):
            self.assertEqual([d.value for d in free.attributes["hide_stroke"].data], [False, True])
            self.assertEqual([d.value for d in region.attributes["hide_stroke"].data], [False, True])
            self.assertEqual([d.value for d in region.attributes["fill_id"].data], [fills[0], 0])
        self.assertIsNone(free.attributes.get("hide_stroke"))
        self.assertIsNone(region.attributes.get("hide_stroke"))
        self.assertEqual([d.value for d in region.attributes["fill_id"].data], fills)
        with sketch.isolate_strokes(self.obj, lambda turn, amend: True):
            self.assertIsNone(free.attributes.get("hide_stroke"), "nothing hidden, nothing written")

    def test_world_transform_and_defaults(self):
        self.obj.location = (1.0, 0.0, 0.0)
        self.obj.data.layers["free"].translation = (0.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        add_stroke(self.obj, "free", [(0, 0, 0), (0, 1, 0)])
        stroke = next(sketch.iter_strokes(self.obj))
        for a, b in zip(stroke.points[0], (1.0, 0.0, 0.5)):
            self.assertAlmostEqual(a, b, places=6)
        self.assertEqual([round(r, 6) for r in stroke.radius], [0.01, 0.01])
        self.assertEqual(stroke.opacity, [1.0, 1.0])
        self.assertFalse(stroke.cyclic)

        add_stroke(self.obj, "carve", [(0, 0, 0), (1, 0, 0), (2, 0, 0)],
                   radius=[0.002, 0.004, 0.006], opacity=0.5, cyclic=True)
        carve = [s for s in sketch.iter_strokes(self.obj) if s.layer == "carve"][0]
        self.assertEqual([round(r, 5) for r in carve.radius], [0.002, 0.004, 0.006])
        self.assertEqual([round(o, 5) for o in carve.opacity], [0.5] * 3)
        self.assertTrue(carve.cyclic)
        free = [s for s in sketch.iter_strokes(self.obj) if s.layer == "free"][0]
        self.assertFalse(free.cyclic)
        self.assertEqual([round(r, 6) for r in free.radius], [0.01, 0.01])

    def test_hidden_layers(self):
        add_stroke(self.obj, "free", [(0, 0, 0), (1, 0, 0)])
        add_stroke(self.obj, "crease", [(0, 0, 0), (0, 0, 1)])
        self.obj.data.layers["crease"].hide = True
        self.assertEqual([s.layer for s in sketch.iter_strokes(self.obj)], ["free"])
        self.assertEqual([s.layer for s in sketch.iter_strokes(self.obj, include_hidden=True)],
                         ["free", "crease"])

    def test_clear(self):
        add_stroke(self.obj, "free", [(0, 0, 0), (1, 0, 0)])
        views.add_view(self.obj.data, lambda i: look_at_view(i, (0, -2, 0), (0, 0, 0)))
        sketch.clear_strokes(self.obj)
        self.assertEqual(list(sketch.iter_strokes(self.obj, include_hidden=True)), [])
        self.assertEqual(views.load_views(self.obj.data), [])


class SessionTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        remove_sketch()
        self.scene = bpy.context.scene
        self.viewport = None
        self.session = sketch.SketchSession(self.scene, viewport_provider=lambda: self.viewport,
                                            use_timer=False)

    def tearDown(self):
        self.session.exit(bpy.context)

    def test_enter_and_exit_restore_tool_settings(self):
        tools = self.scene.tool_settings
        tools.gpencil_stroke_placement_view3d = "CURSOR"
        tools.gpencil_surface_offset = 0.02
        tools.use_keyframe_insert_auto = True
        crate = bpy.data.objects["Crate"]
        bpy.context.view_layer.objects.active = crate
        self.session.enter(bpy.context)
        obj = sketch.find_sketch_object()
        self.assertEqual(tools.gpencil_stroke_placement_view3d, "SURFACE")
        self.assertEqual(tools.gpencil_surface_offset, 0.0)
        self.assertFalse(tools.use_keyframe_insert_auto)
        self.assertIs(bpy.context.view_layer.objects.active, obj)
        self.assertEqual(obj.mode, "PAINT_GREASE_PENCIL")
        self.session.exit(bpy.context)
        self.assertEqual(tools.gpencil_stroke_placement_view3d, "CURSOR")
        self.assertAlmostEqual(tools.gpencil_surface_offset, 0.02, places=6)
        self.assertTrue(tools.use_keyframe_insert_auto)
        tools.use_keyframe_insert_auto = False
        self.assertEqual(obj.mode, "OBJECT")
        self.assertIs(bpy.context.view_layer.objects.active, crate)

    def test_poll_captures_and_tags(self):
        self.session.enter(bpy.context)
        obj = sketch.find_sketch_object()
        front = look_at_view(0, (0, -2, 0.3), (0, 0, 0.3))
        self.viewport = fake_viewport(front)

        self.assertEqual(self.session.poll(), sketch.POLL_INTERVAL)
        self.assertEqual(views.load_views(obj.data), [], "no strokes, no view")

        add_stroke(obj, "free", [(0, -0.3, 0.3), (0.1, -0.3, 0.3)])
        self.session.poll()
        self.assertEqual([v.id for v in views.load_views(obj.data)], [1])
        self.assertEqual([s.view for s in sketch.iter_strokes(obj)], [1])

        add_stroke(obj, "free", [(0, -0.3, 0.4), (0.1, -0.3, 0.4)])
        self.session.poll()
        self.assertEqual(len(views.load_views(obj.data)), 1, "same angle, same view")

        a = math.radians(30)
        self.viewport = fake_viewport(look_at_view(0, (2 * math.sin(a), -2 * math.cos(a), 0.3), (0, 0, 0.3)))
        add_stroke(obj, "add", [(0, -0.3, 0.5), (0.1, -0.3, 0.5)])
        self.session.poll()
        self.assertEqual([s.view for s in sketch.iter_strokes(obj)], [1, 1, 2])

        self.assertEqual(self.session.capture().id, 3)
        add_stroke(obj, "note", [(0, -0.3, 0.6), (0.1, -0.3, 0.6)])
        self.session.poll()
        self.assertEqual([s.view for s in sketch.iter_strokes(obj)], [1, 1, 2, 3])

        self.viewport = None
        add_stroke(obj, "note", [(0, -0.3, 0.7), (0.1, -0.3, 0.7)])
        self.assertEqual(self.session.poll(), sketch.POLL_INTERVAL)
        self.assertEqual([s.view for s in sketch.iter_strokes(obj)][-1], 0)
        with self.assertRaises(RuntimeError):
            self.session.capture()

        self.session.exit(bpy.context)
        bpy.data.objects.remove(obj)
        self.session.active = True
        self.assertIsNone(self.session.poll(), "the sketch object is gone")

    def test_strokes_are_tagged_when_drawn_not_when_polled(self):
        self.session.enter(bpy.context)
        obj = sketch.find_sketch_object()
        self.viewport = fake_viewport(look_at_view(0, (0, -2, 0.3), (0, 0, 0.3)))
        add_stroke(obj, "free", [(0, -0.3, 0.3), (0.1, -0.3, 0.3)])
        # The draw tool's stroke reaches the depsgraph at once.
        bpy.context.view_layer.update()
        a = math.radians(60)
        self.viewport = fake_viewport(look_at_view(0, (2 * math.sin(a), -2 * math.cos(a), 0.3), (0, 0, 0.3)))
        self.session.poll()
        self.assertEqual([s.view for s in sketch.iter_strokes(obj)], [1])
        stored = views.load_views(obj.data)
        self.assertEqual([v.id for v in stored], [1])
        eye, _forward = views.eye_and_forward(stored[0])
        self.assertAlmostEqual((eye - Vector((0, -2, 0.3))).length, 0.0, places=4,
                               msg="tagged with the view the stroke was drawn from")

    def test_handler_goes_with_the_session(self):
        self.session.enter(bpy.context)
        self.assertIn(self.session._handler, bpy.app.handlers.depsgraph_update_post)
        self.session.exit(bpy.context)
        self.assertNotIn(self.session._handler, bpy.app.handlers.depsgraph_update_post)

    def test_capture_tags_pending_strokes_with_the_previous_view(self):
        obj = sketch.ensure_sketch_layers(self.scene)
        self.viewport = fake_viewport(look_at_view(0, (0, -2, 0.3), (0, 0, 0.3)))
        self.session.capture()
        add_stroke(obj, "free", [(0, 0, 0), (1, 0, 0)])
        self.session.capture()
        self.assertEqual([s.view for s in sketch.iter_strokes(obj)], [1])

    def test_module_session(self):
        session = sketch.start_session(bpy.context, use_timer=False,
                                       viewport_provider=lambda: None)
        self.assertIs(sketch.current_session(), session)
        sketch.end_session(bpy.context)
        self.assertIsNone(sketch.current_session())
        self.assertFalse(session.active)

    def test_deleting_the_sketch_ends_the_session_cleanly(self):
        tools = self.scene.tool_settings
        tools.gpencil_stroke_placement_view3d = "ORIGIN"
        tools.use_keyframe_insert_auto = True
        session = sketch.start_session(bpy.context, viewport_provider=lambda: None)
        self.assertFalse(tools.use_keyframe_insert_auto)
        bpy.data.objects.remove(sketch.find_sketch_object())
        self.assertIsNone(session._tick())
        self.assertIsNone(sketch.current_session())
        self.assertFalse(session.active)
        self.assertTrue(tools.use_keyframe_insert_auto)
        self.assertEqual(tools.gpencil_stroke_placement_view3d, "ORIGIN")
        self.assertNotIn(session._handler, bpy.app.handlers.depsgraph_update_post)
        tools.use_keyframe_insert_auto = False
        if bpy.app.timers.is_registered(session._timer):
            bpy.app.timers.unregister(session._timer)

    def test_watcher_timer_is_registered_while_sketching(self):
        session = sketch.start_session(bpy.context, viewport_provider=lambda: None)
        self.assertTrue(bpy.app.timers.is_registered(session._timer))
        sketch.end_session(bpy.context)
        self.assertFalse(bpy.app.timers.is_registered(session._timer))


def _fake_region(pointer, width, height, matrix=None, region_type="WINDOW"):
    rv3d = SimpleNamespace(view_matrix=matrix or Matrix.Identity(4))
    return SimpleNamespace(type=region_type, width=width, height=height, data=rv3d,
                           as_pointer=lambda: pointer)


def _fake_window_manager(*areas):
    return SimpleNamespace(windows=[SimpleNamespace(screen=SimpleNamespace(areas=list(areas)))])


class ViewportDiscoveryTest(unittest.TestCase):
    """The live path that picks the viewport, with fake screens standing in
    for a GUI."""

    def setUp(self):
        self.small = _fake_region(1, 400, 300)
        self.large = _fake_region(2, 1200, 800)
        header = _fake_region(3, 1200, 30, region_type="HEADER")
        header.data = None
        self.areas = [SimpleNamespace(type="VIEW_3D", regions=[self.small]),
                      SimpleNamespace(type="VIEW_3D", regions=[header, self.large]),
                      SimpleNamespace(type="PROPERTIES", regions=[_fake_region(4, 2000, 2000)])]
        self.now = 1.0
        self.session = sketch.SketchSession(bpy.context.scene, clock=lambda: self.now,
                                            use_timer=False,
                                            window_manager=_fake_window_manager(*self.areas))

    def test_viewports_lists_3d_window_regions(self):
        found = views.viewports(_fake_window_manager(*self.areas))
        self.assertEqual([vp.region for vp in found], [self.small, self.large])
        self.assertIs(found[0].rv3d, self.small.data)

    def test_largest_until_one_moves_then_the_latest_moved(self):
        self.assertIs(self.session.active_viewport().region, self.large)
        self.now = 2.0
        self.assertIs(self.session.active_viewport().region, self.large, "nothing moved")
        self.now = 3.0
        self.small.data.view_matrix = Matrix.Translation((0, 0, -1))
        self.assertIs(self.session.active_viewport().region, self.small)
        self.now = 4.0
        self.assertIs(self.session.active_viewport().region, self.small, "still the latest moved")
        self.now = 5.0
        self.large.data.view_matrix = Matrix.Translation((1, 0, 0))
        self.assertIs(self.session.active_viewport().region, self.large)

    def test_no_viewports(self):
        session = sketch.SketchSession(bpy.context.scene, use_timer=False,
                                       window_manager=_fake_window_manager(self.areas[2]))
        self.assertIsNone(session.active_viewport())

    def test_viewport_from_context(self):
        area = self.areas[1]
        header = area.regions[0]
        found = views.viewport_from_context(
            SimpleNamespace(area=area, region=header, region_data=None))
        self.assertIs(found.region, self.large, "falls back from a non-window region")
        self.assertIs(found.rv3d, self.large.data)

        rv3d = SimpleNamespace()
        found = views.viewport_from_context(
            SimpleNamespace(area=area, region=self.large, region_data=rv3d))
        self.assertIs(found.rv3d, rv3d)

        self.assertIsNone(views.viewport_from_context(
            SimpleNamespace(area=self.areas[2], region=None, region_data=None)))
        self.assertIsNone(views.viewport_from_context(
            SimpleNamespace(area=None, region=None, region_data=None)))
        no_window = SimpleNamespace(type="VIEW_3D", regions=[header])
        self.assertIsNone(views.viewport_from_context(
            SimpleNamespace(area=no_window, region=header, region_data=None)))
