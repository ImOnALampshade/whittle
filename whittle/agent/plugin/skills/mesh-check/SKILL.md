---
name: mesh-check
description: Explains the numbers whittle.mesh_report returns (shells, open edges, self-intersections, duplicate vertices, flipped normals, volume, triangle and n-gon counts) and how to weld or tidy what they show. Use when checking a mesh after an edit, when a report looks wrong, or before saying a part is fused, closed or within the triangle budget.
---

# Mesh check

A render cannot show a horn base buried inside a head, an unwelded seam or a flipped face. `whittle.mesh_report(obj)` can. It measures the evaluated mesh (live modifiers included) in world space and returns a dict of counts. It is a way of seeing what you built, not a pass or fail: read the numbers against what you meant to make.

```python
for obj in whittle.targets():
    if obj.type == "MESH":
        print(obj.name, whittle.mesh_report(obj))
```

What each number tells you:

| key | what it counts | what to make of it |
|---|---|---|
| `shells` | connected pieces of surface | One for a single solid thing. More is right for parts you meant to keep apart (planks with gaps, rivets); otherwise a part floats free, a seam is unwelded, or a part is only pushed into the body. |
| `self_intersections` | face pairs that cross each other | With `shells` > 1 it is the fake join: parts overlapping or a base buried under the surface. A self-union fixes it (`whittle:fuse-parts`). |
| `open_edges` | edges without exactly two faces | Holes, open seams, fins, or faces left inside after an extrude. Fine for something meant to be a sheet (a flag, a leaf). |
| `bad_verts` | loose or non-manifold vertices | Stray vertices, or two pieces touching at a single point. |
| `duplicate_verts` | vertices on top of each other | Seams and caps that look closed but are not joined. Weld. |
| `flipped_edges`, `volume` | inconsistent winding; signed volume | Flipped edges mean mixed normals. A negative volume means the mesh is inside out. Weld recalculates normals. |
| `tiny_faces` | faces with almost no area | Boolean slivers. Weld dissolves them. |
| `tris`, `quads`, `ngons` | face counts (`tris` is the triangulated total) | Compare `tris` with the budget. N-gons are fine on flat faces; on curved ones they shade badly and subdivide poorly. |
| `watertight` | closed, consistently wound, positive volume | True for a buried-base join too, since each shell is closed on its own. Read it together with `shells` and `self_intersections`. |

A step that should have changed the shape but left `volume` and `tris` where they were did nothing; booleans fail that way without raising an error.

Weld after booleans, curve-to-mesh, joins and imports. It merges vertices closer than `dist`, dissolves degenerate faces, deletes loose vertices and points normals outward. It never fuses overlapping parts; only a union or growing the part does that.

```python
target = whittle.targets()[0]
print(whittle.weld(target, dist=1e-4))
print(target.name, whittle.mesh_report(target))
```

Turning seam n-gons on a curved surface into quads after a boolean:

```python
target = whittle.targets()[0]
mesh = target.data
bm = bmesh.new()
bm.from_mesh(mesh)
curved_ngons = [f for f in bm.faces if len(f.verts) > 4
                and any(f.normal.angle(g.normal, 0.0) > math.radians(5) for e in f.edges for g in e.link_faces)]
if curved_ngons:
    tris = bmesh.ops.triangulate(bm, faces=curved_ngons)["faces"]
    bmesh.ops.join_triangles(bm, faces=tris, angle_face_threshold=math.radians(40),
                             angle_shape_threshold=math.radians(40))
bm.to_mesh(mesh)
bm.free()
mesh.update()
print(target.name, len(curved_ngons), "n-gons tidied", whittle.mesh_report(target)["ngons"], "left")
```

Notes:
- Keep the weld `dist` well below the smallest real detail: 0.1 mm (`1e-4`) suits props measured in metres.
- `evaluated=False` measures the object's own mesh without its modifiers, which helps tell whether a problem comes from the base mesh or from a modifier (a Mirror without merge, an Array without merge).
- Geometry Nodes instances (a scatter) are not in the report; it measures the mesh the modifiers realise.
- `mesh.validate()` only repairs corrupt data. It is not a watertight test.
- Large meshes (tens of thousands of faces) take a moment; there is no need to measure after every small step on those.
