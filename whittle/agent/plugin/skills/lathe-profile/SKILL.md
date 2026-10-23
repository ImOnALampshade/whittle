---
name: lathe-profile
description: Makes round props by spinning a half-profile stroke around an axis with bmesh.ops.spin. Use when the sketch or prompt describes something turned or round, such as a barrel, bottle, vase, lamp, pot, post, wheel or column.
---

# Lathe from a profile

Use when the user drew half a silhouette of something round (the outline on one side of its axis), or a full silhouette of a symmetric round object (use one half).

1. Convert the profile to (radius, height) pairs relative to the axis: the radius is the distance from the axis, the height is the position along it.
2. Build the profile as connected edges in a plane through the axis and spin it a full turn. 8 to 16 steps suits most props; more for a large or close-up smooth object.
3. Merge the seam, and cap the ends when the profile does not touch the axis.

```python
profile = [(0.0, 0.0, 0.0), (0.22, 0.0, 0.0), (0.26, 0.0, 0.15), (0.27, 0.0, 0.35), (0.26, 0.0, 0.55), (0.22, 0.0, 0.7), (0.0, 0.0, 0.7)]
axis_origin = Vector((0.0, 0.0, 0.0))
axis = Vector((0.0, 0.0, 1.0))
steps = 12
name = "Prop_Barrel"

axis = axis.normalized()
# A direction perpendicular to the axis to lay the profile out in.
side = axis.orthogonal().normalized()
pairs = []
for p in profile:
    rel = Vector(p) - axis_origin
    height = rel.dot(axis)
    radius = (rel - axis * height).length
    pairs.append((radius, height))

bm = bmesh.new()
verts = [bm.verts.new(axis_origin + side * r + axis * h) for r, h in pairs]
edges = [bm.edges.new((a, b)) for a, b in zip(verts, verts[1:])]
bmesh.ops.spin(bm, geom=verts + edges, cent=axis_origin, axis=axis, angle=math.tau, steps=steps,
               use_merge=True, use_duplicate=False)
# Profile points on the axis collapse into poles; merge them.
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

mesh = bpy.data.meshes.new(name)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new(name, mesh)
bpy.context.scene.collection.objects.link(obj)
print(obj.name, whittle.mesh_report(obj))
```

Notes:
- Simplify a hand-drawn profile first (5 to 10 points); every profile point becomes a ring of `steps` vertices.
- If the profile does not reach the axis, the ends are open (`open_edges` in the report): fill them with `bmesh.ops.holes_fill(bm, edges=bm.edges[:], sides=0)` before writing the mesh, unless the object is meant to be open (a cup, a pipe).
- Smooth shading with `mesh.shade_smooth()` and `mesh.set_sharp_from_angle(angle=math.radians(35))` keeps rims crisp.
