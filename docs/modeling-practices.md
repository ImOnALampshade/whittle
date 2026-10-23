# Modeling practices

The research behind the "Modeling practice" section of the system prompt
(`whittle/agent/system_prompt.md`) and the `mesh-check` and `fuse-parts` skills. The prompt
gives the agent these as defaults with reasons, not as rules: it should know them and know
when to break them, and say what it chose.

Points marked **verified** were run headless in Blender 5.2.2 LTS
(`blender -b --factory-startup`); the rest come from practitioners and documentation.

## Why: the horns

Asked to add horns to a sphere head, the agent produced meshes that rendered fine but were
not one solid:

| what the agent did | mesh_report | problem |
|---|---|---|
| horns as separate objects overlapping the sphere | several objects | not attached at all |
| horns joined into the sphere mesh, bases buried | open_edges 0, shells 3, self_intersections 50 | passes an edge check, but is three crossing shells with hidden faces |
| horns unioned (EXACT) and welded | shells 1, no intersections | right |
| horns grown from the sphere's faces | shells 1, no intersections, no n-gons | right, cleanest |

A check for open or non-manifold edges passes the bad join, because each buried shell is
closed on its own. Counting connected shells and testing for self-intersection catches it.
**Verified.** That is what `whittle.mesh_report` reports (`whittle/addon/meshcheck.py`).

## One solid thing, one closed shell

- An object the user thinks of as one solid thing is best as one closed manifold shell:
  every edge has two faces, normals point out, nothing is hidden inside. Overlapping shells
  break booleans, bevel, solidify, subdivision, remesh, normal baking, 3D printing and
  volume calculations, and moving a part later exposes the buried base. Sources: Blender
  manual, Booleans and Clean Up. **Verified.**
- Parts that move on their own (lid, door, wheel, drawer), linked repeats and swappable kit
  pieces are separate objects, parented to the body with the origin on the hinge or axle.
  Small repeated details (rivets, studs, gapped planks) may stay separate closed pieces or
  instances. Source: Epic, FBX Static Mesh Pipeline.
- Seams need welding: a curve sweep with `use_fill_caps` converts to 3 shells (tube plus two
  caps) until `remove_doubles`; a Mirror without merge leaves an open seam; Array needs
  `use_merge_vertices` when copies should fuse; spin needs `use_merge`. **Verified.**
- Normals: `recalc_face_normals` after topology edits. Mixed winding shows as manifold edges
  that are not contiguous; a fully inverted mesh shows only as a negative signed volume.
  **Verified.**
- `mesh.validate()` repairs corrupt data; it is not a watertight test (it returned False,
  "nothing wrong", on a mesh with 144 non-manifold edges). **Verified.**

## Attaching a part

From cleanest to most general:

1. **Grow it from the surface**: extrude a face patch in steps, deleting the extrude's input
   faces each time (`extrude_face_region` keeps them, and on a closed mesh they become
   interior walls), translating along the averaged normal and scaling each ring. Big flat
   faces need an `inset_region` first. One shell, all quads. **Verified.**
2. **Boolean union (EXACT), bake, weld**: operands closed and clearly overlapping (10 to 30%
   of the part's length). `material_mode='TRANSFER'`, since the default `INDEX` repaints the
   part. The seam gets n-gons and near-duplicates; weld it. **Verified.**
3. **Bridge edge loops** for tubes meeting a hole with the same edge count: all-quad seam.
   **Verified.**
4. **Self-union** (`use_self=True`, empty collection operand) repairs a mesh that already has
   overlapping shells: shells 3 to 1, self-intersections 50 to 0. MANIFOLD and FLOAT do not.
   **Verified.**
5. **Voxel remesh** always gives one shell, but faces grow from about 530 to 21k to 43k, hard
   edges round off and thin tips vanish at coarse voxel sizes; decimating after leaves a
   triangle soup. Best kept for organic blobs. **Verified.**

Joining objects, `bm.from_mesh` of a second mesh, the Weld modifier, `remove_doubles` and
Decimate do not fuse overlapping parts. **Verified.**

### Booleans that fail silently (Blender 5.2, verified, none raise)

- An operand that only touches the body is dropped; the body is unchanged.
- An operand floating off the surface stays a second shell.
- MANIFOLD with an open operand returns the body unchanged and only logs a warning.
- EXACT with an open operand leaves duplicate vertices or a self-intersection.

So measure each operand before a boolean and compare volume and triangle count after. The
solvers in 5.2 are FLOAT, EXACT and MANIFOLD.

Live or baked: a baked boolean is the real single mesh with no helpers; a live one stays
editable but leaves a helper object and a base mesh that is not the final shape. There is no
fixed answer; the agent picks for the situation and says which.

## Measuring

`mesh_report` runs on the evaluated mesh (live modifiers count) in world space: `tris`,
`quads`, `ngons`, `shells`, `open_edges`, `bad_verts`, `flipped_edges`, `duplicate_verts`,
`tiny_faces`, `self_intersections` (BVH self-overlap, ignoring face pairs that share a
vertex) and signed `volume`, plus `watertight`. An unfiltered `BVHTree.overlap(self)` either
finds nothing or counts neighbours; filtering pairs that share a vertex with `epsilon=0.0`
was right in every test. Fast enough on a 43k-triangle mesh. **Verified.**

Clean-up after booleans and joins (`whittle.weld`): `remove_doubles(dist=1e-4)`,
`dissolve_degenerate`, delete loose vertices, `recalc_face_normals`. Keep `dist` well below
the smallest detail. **Verified.**

Numbers and pictures catch different things: the horn failure passed the visual check.

## Topology

- Quads where it matters: curved, organic, subdivided or deforming surfaces. Triangles are
  fine on flat areas, caps and tips; n-gons on flat faces that will not be subdivided.
  Sources: Blender manual, Mesh Structure; Polycount, "ngons, tris and quads".
- Avoid slivers and sudden density jumps. After a boolean, `triangulate` then
  `join_triangles` turns seam n-gons into quads. **Verified.**
- Poles away from tight curvature: a UV sphere's two many-edged poles are bad places to grow
  from; an icosphere or a spherified subdivided cube is a better base. **Verified.**
- Typical counts for props: 8 to 16 segments round a cylinder, 12 to 24 round a sphere, 4 to
  8 steps along a horn or tail. Source: Polycount.
- A low-poly cage with Subdivision Surface beats hand-built density for smooth organic
  shapes, at 4x the triangles per level.
- Symmetric objects: model half with a Mirror (merge, clip); `bmesh.ops.symmetrize` makes a
  near-symmetric mesh exact. **Verified.**

## Shading

- Smooth plus sharp by angle: `mesh.shade_smooth(); mesh.set_sharp_from_angle(angle=radians(30 to 40))`.
  Auto Smooth was removed in 4.1. **Verified.**
- Hard surface: a 1 to 3 segment Bevel with `harden_normals`, then Weighted Normal
  (`keep_sharp=True`) last. Sources: Blender manual, Weighted Normal and Bevel.
- Flat shading for a deliberately faceted look.

## Transforms and scale

- 1 unit = 1 m, real sizes, props resting on z = 0. Sources: katsbits, Unity/Blender FBX
  scale; Epic docs.
- Build at real size; if a transform must be applied:
  `obj.data.transform(obj.matrix_basis); obj.matrix_basis = Matrix()`. **Verified.**
- `obj.matrix_world` is stale after setting `location`, `rotation_euler` or `scale` until
  `view_layer.update()`; a part placed with it lands at the origin, which is another way to
  bury it silently. **Verified.**

## Asset hygiene

- Spend triangles on the silhouette, counted on the evaluated mesh. Source: Polycount.
- Flat-colour material slots, reused; a fused part keeps its colour per face. **Verified.**
- bmesh `create_*(calc_uvs=True)` writes nothing without a UV layer, and boolean results of
  UV-less inputs have no UVs. **Verified.** Not in the prompt.
- Names `<Target>_<Part>`; `mesh.name = obj.name` after a bake. LODs, collision meshes,
  export and print-thickness checks only when asked. The 3D-Print Toolbox is an extension
  in 5.2, not bundled. **Verified.**

## Agent workflow

- Data API and bmesh over `bpy.ops`; when an operator is unavoidable,
  `bpy.context.temp_override(object=o, active_object=o, selected_objects=[o])` works
  headless for `modifier_apply`. Source: Blender API, Gotchas. **Verified.**
- Checkpoint before destructive steps.
- Report mesh health in the summary, and say plainly when something is not one closed shell.

## Project defaults

| topic | choice |
|---|---|
| separate parts | fuse what is rigid and belongs together; moving parts, parts the user wants apart, and small repeated details may stay separate; say what was left separate |
| booleans | no rule: explain the trade-off, let the agent choose and say what it did |
| topology | quads where it matters; triangles on flat areas, caps, tips; n-gons on flat faces |
| style | general purpose; follow the prompt and the file's style (palette, bevel style, notes) |
| shading | judged by shape and style; say what was chosen |
| triangle budget | a loose guide; report the count |
| voxel remesh | a tool with known costs; fine for organic blobs |

## Sources

- Blender manual: Boolean modifier (https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/booleans.html),
  Mesh Clean Up, Mesh Structure, Extrude Faces, Subdivision Surface, Mirror, Remesh,
  Weighted Normal, Bevel, Shading, Normals, Apply Transforms, Origin.
- Blender Python API: bmesh.ops (https://docs.blender.org/api/current/bmesh.ops.html), Gotchas.
- Blender 4.1 release notes, modeling (Auto Smooth removal).
- Epic Games, FBX Static Mesh Pipeline (https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine).
- Polycount, "ngons, tris and quads" (https://polycount.com/discussion/155894), and budget and silhouette threads.
- katsbits, Unity/Blender FBX scale; dev.to, "Looks right in Blender, wrong in engine"; a Blender to UE5 export guide on Substack.
