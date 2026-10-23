---
name: extrude-along-stroke
description: Sweeps a round or square profile along a stroke path and turns it into a welded, closed mesh. Use when a stroke is a path rather than an outline, such as a handle arc, pipe, rail, rope, cable, branch or trim.
---

# Extrude along a stroke

Use when a stroke is a path, not an outline: a handle arc, a pipe, a hanging rope, a tree branch, a rim trim.

1. Resample the stroke to a handful of evenly spaced points (6 to 16 for a typical prop-sized path; more for a smooth close-up).
2. Build a curve object with a bevel to give it thickness; keep the resolution low.
3. Convert to a mesh through the evaluated depsgraph, so no operator or viewport is needed.
4. Weld it: the converted tube and its end caps come out as separate, unwelded pieces (three shells).
5. If it attaches to the body (a handle, a branch, a pipe into a wall), it usually belongs fused into the body: see `whittle:fuse-parts`.

```python
path = [(-0.15, -0.26, 0.30), (-0.12, -0.32, 0.38), (0.0, -0.34, 0.42), (0.12, -0.32, 0.38), (0.15, -0.26, 0.30)]
radius = 0.015
samples = 8
name = "Prop_Handle"


def resample(points, count):
    pts = [Vector(p) for p in points]
    lengths = [0.0]
    for a, b in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + (b - a).length)
    total = lengths[-1]
    out = []
    for i in range(count):
        target = total * i / (count - 1)
        j = max(k for k in range(len(pts) - 1) if lengths[k] <= target + 1e-9) if target < total else len(pts) - 2
        seg = lengths[j + 1] - lengths[j]
        t = 0.0 if seg < 1e-9 else (target - lengths[j]) / seg
        out.append(pts[j].lerp(pts[j + 1], min(t, 1.0)))
    return out


curve = bpy.data.curves.new(name + "_curve", "CURVE")
curve.dimensions = "3D"
curve.bevel_mode = "ROUND"
curve.bevel_depth = radius
curve.bevel_resolution = 1          # 1 gives a 6-sided tube; 0 gives a flat ribbon
curve.use_fill_caps = True
curve.resolution_u = 2
spline = curve.splines.new("POLY")
points = resample(path, samples)
spline.points.add(len(points) - 1)
for sp, p in zip(spline.points, points):
    sp.co = (p.x, p.y, p.z, 1.0)

tmp = bpy.data.objects.new(name + "_tmp", curve)
bpy.context.scene.collection.objects.link(tmp)
depsgraph = bpy.context.evaluated_depsgraph_get()
mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph))
mesh.name = name
bpy.data.objects.remove(tmp)
bpy.data.curves.remove(curve)

obj = bpy.data.objects.new(name, mesh)
bpy.context.scene.collection.objects.link(obj)
# Weld the caps to the tube so the sweep is one closed shell.
whittle.weld(obj)
print(obj.name, whittle.mesh_report(obj))
```

Notes:
- For a square profile (planks, trims) set `curve.bevel_resolution = 0` and use a Solidify modifier, or sweep with `bevel_mode = "OBJECT"` and a small square curve as `bevel_object`.
- Use "SMOOTH"/NURBS splines only for organic shapes; POLY keeps the vertex count predictable.
- Where the path meets the body, run each end into the body by about twice the radius and union the sweep in (`fuse_parts` in `whittle:fuse-parts`). Ends only pushed into the body, as a separate object or a separate shell, look joined but leave buried faces.
- A sweep can stay its own object when it should: a rope that hangs free, a rail the user wants to move. Say so in your reply.
