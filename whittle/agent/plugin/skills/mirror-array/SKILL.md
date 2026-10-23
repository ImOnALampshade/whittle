---
name: mirror-array
description: Sets up Mirror and Array modifiers for symmetric props and repeated parts, including arrays fitted to a length or along a curve. Use when a prop is symmetric, when parts come in matching pairs (two horns, two ears), or for rows of planks, slats, bolts, fence posts or steps.
---

# Mirror and array

Build half (or one) and let modifiers do the rest. Live modifiers stay editable; apply them when a later step needs the real geometry (a union, a remesh).

Mirror across the object's own X axis, with bisect so geometry that crosses the middle is cut cleanly:

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]
mirror = target.modifiers.get("Mirror") or target.modifiers.new("Mirror", "MIRROR")
mirror.use_axis = (True, False, False)
mirror.use_bisect_axis = (True, False, False)
mirror.use_clip = True
mirror.use_mirror_merge = True
mirror.merge_threshold = 0.001
print([m.name for m in target.modifiers])
```

Mirror around another object's origin (e.g. the prop's centre when the part is off-centre): set `mirror.mirror_object = some_empty_or_object`.

A row of planks: one plank, repeated with a gap.

```python
mesh = bpy.data.meshes.new("Prop_Plank")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=(0.12, 0.5, 0.02), verts=bm.verts)
bm.to_mesh(mesh)
bm.free()
plank = bpy.data.objects.new("Prop_Plank", mesh)
plank.location = (-0.25, 0.0, 0.52)
bpy.context.scene.collection.objects.link(plank)

array = plank.modifiers.new("Array", "ARRAY")
array.count = 4
array.use_relative_offset = True
array.relative_offset_displace = (1.15, 0.0, 0.0)   # 15% gap between planks
array.use_merge_vertices = False
print(plank.name, array.count)
```

Notes:
- Fixed spacing in metres: `use_relative_offset = False`, `use_constant_offset = True`, `constant_offset_displace = (0.3, 0, 0)`.
- Fit a run to a length: `fit_type = "FIT_LENGTH"` and `fit_length`.
- Along a path: `fit_type = "FIT_CURVE"`, `curve = curve_object`, and add a Curve modifier after the Array so the copies bend along it.
- Order matters: Array before Mirror repeats then mirrors; Mirror before Bevel keeps the seam bevelled consistently.
- Where the halves meet, keep `use_clip` and `use_mirror_merge` on: without merge the two halves are open shells that only touch. `whittle.mesh_report(obj)` measures the evaluated mesh, so it shows an unmerged seam as open edges.
- Paired parts on a symmetric body (two horns, two ears): build one into the half and let the Mirror make the other, so both are part of the same welded shell.
- Array copies that should form one piece (segments of a rail, links of a chain bar): `use_merge_vertices = True` with the copies just touching. Copies with gaps between them, like the planks above, are separate pieces by design.
