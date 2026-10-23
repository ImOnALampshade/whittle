---
name: fuse-parts
description: Fuses a part into a body as one closed mesh, by growing it out of the body's faces or with a baked Boolean union, and repairs a mesh whose parts overlap with a self-union. Use when adding horns, spikes, ears, limbs, tails, spouts, handles or chimneys to a body, or when mesh_report shows more than one shell with self-intersections.
---

# Fuse parts into one mesh

When a part belongs to the body (horns on a head, a spout on a kettle), the clean result is one closed shell: no part overlapping the body, no base hidden under the surface. Merely pushing a part into the body, as its own object or joined into the same mesh, looks right in a render, but it leaves two shells crossing each other with buried faces, which breaks bevels, booleans, subdivision and printing, and shows if the part is moved. `whittle.mesh_report` tells the two apart (`whittle:mesh-check`).

Ways to fuse, and what each costs:
- **Grow from the surface**: extrude a patch of the body's faces outward in steps. One shell by construction, all quads, few triangles. Suits tapering or tube-like parts: horns, spikes, ears, tails, limbs, stubs, chimneys.
- **Boolean union**: build the part on its own, overlap it with the body and union it. Any shape (a boxy nose, a lathed spout, a swept handle), but the seam gets n-gons and near-duplicate vertices that want a weld.
- **Bridge loops**: for a tube meeting a hole of the same edge count (necks, limbs, handles). An all-quad seam with no boolean slivers.
- **Self-union**: repairs a mesh that already holds overlapping parts.

A UV sphere has many-edged poles at top and bottom, which are poor places to grow from. Grow away from them, or start round bodies from an icosphere or a subdivided cube with its vertices pushed onto a sphere.

Grow a curved, tapering part out of the body's faces. Directions are in the object's local space.

```python
target = whittle.targets()[0]
direction = Vector((0.4, 0.0, 1.0))   # from the body's centre towards where the part starts
centre = Vector()                     # the body's centre in local space; the origin for most bodies
base_radius = 0.07                    # radius of the patch the part grows from; size these to the body
steps = 4                             # rings along the part
step_length = 0.06
taper = 0.75                          # each ring's size relative to the one before
bend = Vector((0.25, 0.0, 0.0))       # added to the growth direction each step; zero for straight
pointed = True                        # merge the last ring into a tip

mesh = target.data
bm = bmesh.new()
bm.from_mesh(mesh)
d = direction.normalized()
seed = max(bm.faces, key=lambda f: (f.calc_center_median() - centre).normalized().dot(d))
region = [f for f in bm.faces
          if (f.calc_center_median() - seed.calc_center_median()).length <= base_radius]
area = sum(f.calc_area() for f in region)
if area > 2 * math.pi * base_radius ** 2:
    # The patch is much bigger than the part (a big flat face): inset it down to size first.
    bmesh.ops.inset_region(bm, faces=region, thickness=max(0.0, math.sqrt(area) / 2 - base_radius))
grow = sum((f.normal for f in region), Vector()).normalized()
for _ in range(steps):
    result = bmesh.ops.extrude_face_region(bm, geom=region)
    # extrude_face_region keeps the input faces; on a closed mesh they become inner walls.
    bmesh.ops.delete(bm, geom=region, context="FACES")
    ring = [g for g in result["geom"] if isinstance(g, bmesh.types.BMVert)]
    region = [g for g in result["geom"] if isinstance(g, bmesh.types.BMFace)]
    grow = (grow + bend).normalized()
    bmesh.ops.translate(bm, vec=grow * step_length, verts=ring)
    mid = sum((v.co for v in ring), Vector()) / len(ring)
    bmesh.ops.scale(bm, vec=(taper, taper, taper), space=Matrix.Translation(-mid), verts=ring)
if pointed:
    tip = list({v for f in region for v in f.verts})
    bmesh.ops.pointmerge(bm, verts=tip, merge_co=sum((v.co for v in tip), Vector()) / len(tip))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
bm.to_mesh(mesh)
bm.free()
mesh.update()
print(target.name, whittle.mesh_report(target))
```

For a matching pair (two horns, two ears) on a symmetric body, grow one and let a Mirror modifier with merge and clip make the other (`whittle:mirror-array`): that guarantees they match. Running the block again with the direction mirrored also works when `centre` is the body's true centre (not the mean of the vertices, which the first part shifts). The new faces keep the material of the faces they grew from; set `material_index` on them for a different colour.

Fuse separately built parts with a Boolean union, baked into the body's mesh. Each part should be closed (cones and cylinders with `cap_ends=True`) and overlap the body clearly, by roughly 10 to 30% of its length. A part that only touches the body is dropped without an error, and one that floats stays a second shell.

```python
def fuse_parts(target, parts, weld_dist=1e-4):
    """Boolean-union parts (closed meshes) into target, bake it, delete the parts.
    With parts=[] it fuses target's own overlapping shells (self-union repair)."""
    bpy.context.view_layer.update()
    collection = bpy.data.collections.new(target.name + "_fuse")
    for part in parts:
        collection.objects.link(part)
    mod = target.modifiers.new("Fuse", "BOOLEAN")
    mod.operation = "UNION"
    mod.solver = "EXACT"              # MANIFOLD ignores open operands; FLOAT mishandles overlaps
    mod.operand_type = "COLLECTION"
    mod.collection = collection
    mod.material_mode = "TRANSFER"    # parts keep their own materials (INDEX repaints them)
    mod.use_self = not parts
    # new_from_object bakes every modifier, so set aside the ones that should stay live.
    others = [m for m in target.modifiers if m != mod and m.show_viewport]
    for m in others:
        m.show_viewport = False
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    baked = bpy.data.meshes.new_from_object(target.evaluated_get(depsgraph),
                                            preserve_all_data_layers=True, depsgraph=depsgraph)
    for m in others:
        m.show_viewport = True
    target.modifiers.remove(mod)
    old = target.data
    target.data = baked
    baked.name = target.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    for part in parts:
        part_mesh = part.data
        bpy.data.objects.remove(part)
        if part_mesh.users == 0:
            bpy.data.meshes.remove(part_mesh)
    bpy.data.collections.remove(collection)
    # Exact booleans leave near-duplicate vertices and slivers along the seam.
    whittle.weld(target, dist=weld_dist)


target = whittle.targets()[0]
spout_mesh = bpy.data.meshes.new(target.name + "_spout")
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.05, radius2=0.03, depth=0.2)
bm.to_mesh(spout_mesh)
bm.free()
spout = bpy.data.objects.new(target.name + "_spout", spout_mesh)
bpy.context.scene.collection.objects.link(spout)
# Point the cone's +Z along the outward direction and push its base well inside the body.
spout.matrix_world = target.matrix_world @ Matrix.LocRotScale(
    Vector((0.25, 0.0, -0.05)), Vector((1.0, 0.0, 0.3)).to_track_quat("Z", "Y"), None)
print("spout", whittle.mesh_report(spout)["watertight"])
before = whittle.mesh_report(target)
fuse_parts(target, [spout])
after = whittle.mesh_report(target)
print(target.name, "volume", before["volume"], "->", after["volume"], after)
```

Repair a mesh whose parts were joined but overlap (`shells` > 1 with `self_intersections` > 0):

```python
target = whittle.targets()[0]
fuse_parts(target, [])
print(target.name, whittle.mesh_report(target))
```

Notes:
- Take a `mcp__blender__checkpoint` before baking, and restore it if the result is worse than before.
- If `volume` and `tris` did not change, the union dropped the part: overlap it more, or close its holes.
- The union above is baked: the body really is one mesh and no helper objects are left. Keeping the Boolean modifier live instead keeps the part movable, at the cost of a helper object and a base mesh that is not the final shape. Pick for the situation and say which you did.
- Bridge loops: delete the body faces where the part meets it, build the part without caps using the same number of edges as the hole, and join the two boundary loops with `bmesh.ops.bridge_loops`.
- Joining meshes (`bm.from_mesh` of a second mesh, joining objects), the Weld modifier, `remove_doubles` and Decimate never fuse overlapping parts. Only a union, or growing the part, does.
- Voxel remesh (a Remesh modifier in VOXEL mode) also gives one closed shell, but it is dense, rounds hard edges and loses thin tips unless the voxel size is small. Growing and unions are usually cleaner; for organic blobs remeshing and then decimating can be the best fit.
- Some parts are better as separate objects: ones that move on their own (a lid, a door, a wheel), ones the user asks to keep apart, and small repeated details (rivets, studs) as separate closed pieces or instances. Parent them to the body and say in your reply what you left separate.
