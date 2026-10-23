---
name: blockout-silhouette
description: Builds a solid blockout by extruding a closed outline stroke into a prism, with the hand-drawn wobble simplified away. Use when an add or free stroke is the closed silhouette of a flat-sided prop (a crate side, a sign, a door, a tombstone), or for the first rough shape of a prop drawn as an outline.
---

# Blockout from a silhouette

Use when the user drew a closed outline and the prop is roughly that silhouette with some depth (a crate side, a sign, a door, a tombstone). The outline's points are world-space, so they already sit on the plane the user drew on.

1. Take the stroke's points. Drop near-duplicates and simplify the wobble so a hand-drawn edge becomes a few clean vertices.
2. Find the plane normal of the outline (Newell's method is robust for wobbly loops).
3. Make an n-gon, extrude it along the normal by the depth, and centre the result on the original plane.
4. Put the object origin at the centre of the shape.

```python
outline = [(-0.30, 0.0, 0.0), (0.30, 0.0, 0.0), (0.31, 0.0, 0.62), (0.0, 0.0, 0.80), (-0.29, 0.0, 0.61)]
depth = 0.2
name = "Prop_Body"


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker: keeps the corners, drops the wobble."""
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    ab = b - a
    def dist(p):
        if ab.length < 1e-9:
            return (p - a).length
        return ab.cross(p - a).length / ab.length
    index, worst = max(((i, dist(p)) for i, p in enumerate(points[1:-1], 1)), key=lambda t: t[1])
    if worst <= tolerance:
        return [a, b]
    return simplify(points[: index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


pts = [Vector(p) for p in outline]
# Simplify as an open path that starts at the first point, then close it again.
pts = simplify(pts + [pts[0]], tolerance=0.01)[:-1]

normal = Vector((0.0, 0.0, 0.0))
for a, b in zip(pts, pts[1:] + pts[:1]):
    normal.x += (a.y - b.y) * (a.z + b.z)
    normal.y += (a.z - b.z) * (a.x + b.x)
    normal.z += (a.x - b.x) * (a.y + b.y)
normal.normalize()
centre = sum(pts, Vector()) / len(pts)

bm = bmesh.new()
verts = [bm.verts.new(p - centre - normal * depth / 2) for p in pts]
face = bm.faces.new(verts)
extruded = bmesh.ops.extrude_face_region(bm, geom=[face])
moved = [g for g in extruded["geom"] if isinstance(g, bmesh.types.BMVert)]
bmesh.ops.translate(bm, vec=normal * depth, verts=moved)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

mesh = bpy.data.meshes.new(name)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new(name, mesh)
obj.location = centre
bpy.context.scene.collection.objects.link(obj)
print(obj.name, len(mesh.vertices), "verts")
```

Notes:
- Concave outlines are fine as an n-gon; add a Triangulate modifier only if the shading looks wrong.
- If the outline was drawn from an angle, check the result with an overlay render from that view before moving on.
- For a box-like prop, a cube scaled to the outline's bounds is often cleaner than the literal outline.
