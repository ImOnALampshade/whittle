---
name: bevel-crease
description: Bevels hard-surface edges and turns crease strokes into bevelled or sharp edges by picking the mesh edges that lie under the stroke. Use for crease (yellow) strokes, for prompts about bevels, chamfers, rounded or sharp edges, and for hard-surface shading.
---

# Bevel and crease edges

Use for crease (yellow) strokes and for general hard-surface polish.

Whole-object bevel, which suits most hard-surface props:

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]
bevel = target.modifiers.get("Bevel") or target.modifiers.new("Bevel", "BEVEL")
bevel.width = 0.01              # metres; about 2% of the prop's size reads well
bevel.segments = 1              # 1 is a chamfer; 2 or 3 for a rounder edge
bevel.limit_method = "ANGLE"
bevel.angle_limit = math.radians(40)
bevel.harden_normals = True
target.data.shade_smooth()
target.data.set_sharp_from_angle(angle=math.radians(40))
print([m.name for m in target.modifiers])
```

Bevelling only the edges under a crease stroke: give those edges a bevel weight and switch the modifier to the WEIGHT limit method. Edges are picked by how close their midpoints lie to the stroke.

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]
crease_stroke = [(-0.25, -0.25, 0.5), (0.0, -0.25, 0.5), (0.25, -0.25, 0.5)]
tolerance = 0.03


def distance_to_polyline(p, points):
    best = float("inf")
    for a, b in zip(points, points[1:]):
        ab = b - a
        t = 0.0 if ab.length_squared < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        best = min(best, (a + ab * t - p).length)
    return best


mesh = target.data
world = target.matrix_world
stroke = [Vector(p) for p in crease_stroke]
weights = mesh.attributes.get("bevel_weight_edge") or mesh.attributes.new("bevel_weight_edge", "FLOAT", "EDGE")
picked = 0
for edge in mesh.edges:
    a = world @ mesh.vertices[edge.vertices[0]].co
    b = world @ mesh.vertices[edge.vertices[1]].co
    if distance_to_polyline((a + b) / 2, stroke) < tolerance and distance_to_polyline(a, stroke) < tolerance * 2 \
            and distance_to_polyline(b, stroke) < tolerance * 2:
        weights.data[edge.index].value = 1.0
        picked += 1

bevel = target.modifiers.get("Crease_bevel") or target.modifiers.new("Crease_bevel", "BEVEL")
bevel.limit_method = "WEIGHT"
bevel.width = 0.015
bevel.segments = 2
print("weighted edges:", picked)
```

Notes:
- If no edge lies under the stroke, the mesh needs a loop there first: cut one with `bmesh.ops.bisect_plane` through the stroke, then pick again.
- For a sharp (unbevelled) crease on a smooth-shaded object, write `True` into the `sharp_edge` BOOLEAN EDGE attribute instead of a bevel weight.
- Segments multiply triangles: 1 or 2 is plenty for most props, more for a large, close-up rounded edge.
- For hard-surface shading, add a Weighted Normal modifier (`keep_sharp = True`) last in the stack, after the Bevel: flat faces then shade flat and the bevels carry the smoothing.
