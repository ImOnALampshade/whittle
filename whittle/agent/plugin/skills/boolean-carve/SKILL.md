---
name: boolean-carve
description: Carves a hole, slot, notch, groove or recess with a Boolean difference, using a cutter built from the stroke, and keeps the boolean live or bakes it without operators. Use for carve (red) strokes and for prompts that ask to cut, drill, hollow or recess.
---

# Boolean carve

Use for carve (red) strokes: handle slots, windows, notches, grooves, recesses.

1. Build a cutter: extrude the carve outline through the surface along the surface normal (the bundle gives `normal` for on-surface points). Make the cutter deeper than the wall it cuts, and a little proud of the surface on the outside so coplanar faces never happen.
2. Add a Boolean modifier (DIFFERENCE, EXACT solver) to the target. Hide the cutter in renders and show it as wire.
3. Keep it live or apply it. Live, the cut stays editable (move or resize the cutter), but a helper object stays in the scene and the base mesh is not the final shape. Applied, the mesh is the real result with no helpers. Keep it live while the user is likely to adjust it; apply it when the shape is settled or a later step needs the real geometry. Say which you did.
4. Measure the evaluated result with `whittle.mesh_report` (`whittle:mesh-check`). Exact booleans leave near-duplicate vertices and slivers along the cut, so weld after applying.

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]
slot = [(0.09 * math.cos(a), -0.25, 0.38 + 0.028 * math.sin(a)) for a in (i * math.tau / 12 for i in range(12))]
surface_normal = Vector((0.0, -1.0, 0.0))
depth = 0.06            # how far into the target to cut
outside = 0.01          # how far the cutter starts above the surface

bm = bmesh.new()
verts = [bm.verts.new(Vector(p) + surface_normal * outside) for p in slot]
face = bm.faces.new(verts)
extruded = bmesh.ops.extrude_face_region(bm, geom=[face])
moved = [g for g in extruded["geom"] if isinstance(g, bmesh.types.BMVert)]
bmesh.ops.translate(bm, vec=-surface_normal * (depth + outside), verts=moved)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
cutter_mesh = bpy.data.meshes.new(target.name + "_cutter")
bm.to_mesh(cutter_mesh)
bm.free()

cutter = bpy.data.objects.new(target.name + "_cutter", cutter_mesh)
bpy.context.scene.collection.objects.link(cutter)
cutter.display_type = "WIRE"
cutter.hide_render = True
cutter.parent = target
cutter.matrix_parent_inverse = target.matrix_world.inverted()

mod = target.modifiers.new("Carve_slot", "BOOLEAN")
mod.operation = "DIFFERENCE"
mod.solver = "EXACT"
mod.object = cutter
print(target.name, [m.name for m in target.modifiers])
```

Applying a boolean without `bpy.ops` (only when it should be permanent):

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]
mod = target.modifiers.get("Carve_slot")
if mod is not None:
    cutter = mod.object
    depsgraph = bpy.context.evaluated_depsgraph_get()
    old_mesh = target.data
    # new_from_object bakes every modifier, so set aside the ones that should stay live.
    others = [m for m in target.modifiers if m != mod and m.show_viewport]
    for m in others:
        m.show_viewport = False
    depsgraph.update()
    baked = bpy.data.meshes.new_from_object(target.evaluated_get(depsgraph))
    for m in others:
        m.show_viewport = True
    target.modifiers.remove(mod)
    target.data = baked
    baked.name = target.name
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    # Weld the slivers and near-duplicate vertices the cut leaves behind.
    whittle.weld(target)
    if cutter is not None:
        cutter_mesh = cutter.data
        bpy.data.objects.remove(cutter)
        if cutter_mesh.users == 0:
            bpy.data.meshes.remove(cutter_mesh)
    print(target.name, "after applying:", whittle.mesh_report(target))
```

Notes:
- The EXACT solver needs a closed (manifold) cutter; the extruded outline is closed. The MANIFOLD solver with an open cutter does nothing and raises no error.
- If `volume` and `tris` in the report did not change, the cutter missed the target or only touched it.
- A slot that should go all the way through: make `depth` larger than the target's thickness.
- Cutter faces lying exactly on target faces give unpredictable results; offset them by a millimetre or two.
