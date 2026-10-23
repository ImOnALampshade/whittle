---
name: gn-scatter
description: Scatters copies of a small object over a surface with a Geometry Nodes modifier built in Python, with density and seed controls. Use for many small repeated details on a surface, such as rivets, studs, leaves, pebbles, moss or grass clumps.
---

# Geometry Nodes scatter

Use for many small repeated details on a surface. Build the node group in code, add it as a NODES modifier, and expose density and seed as modifier inputs.

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]

# A tiny stud to scatter, hidden from renders on its own.
stud_mesh = bpy.data.meshes.new("Prop_Stud")
bm = bmesh.new()
bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.012)
bm.to_mesh(stud_mesh)
bm.free()
stud = bpy.data.objects.new("Prop_Stud", stud_mesh)
bpy.context.scene.collection.objects.link(stud)
stud.hide_render = True
stud.hide_set(True)

group = bpy.data.node_groups.new("Whittle_Scatter", "GeometryNodeTree")
iface = group.interface
iface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
iface.new_socket("Instance", in_out="INPUT", socket_type="NodeSocketObject")
density = iface.new_socket("Density", in_out="INPUT", socket_type="NodeSocketFloat")
density.default_value = 40.0
density.min_value = 0.0
seed = iface.new_socket("Seed", in_out="INPUT", socket_type="NodeSocketInt")
iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

nodes, links = group.nodes, group.links
g_in = nodes.new("NodeGroupInput")
g_out = nodes.new("NodeGroupOutput")
distribute = nodes.new("GeometryNodeDistributePointsOnFaces")
info = nodes.new("GeometryNodeObjectInfo")
info.inputs["As Instance"].default_value = True
instance = nodes.new("GeometryNodeInstanceOnPoints")
join = nodes.new("GeometryNodeJoinGeometry")

links.new(g_in.outputs["Geometry"], distribute.inputs["Mesh"])
links.new(g_in.outputs["Density"], distribute.inputs["Density"])
links.new(g_in.outputs["Seed"], distribute.inputs["Seed"])
links.new(g_in.outputs["Instance"], info.inputs["Object"])
links.new(distribute.outputs["Points"], instance.inputs["Points"])
links.new(distribute.outputs["Rotation"], instance.inputs["Rotation"])
links.new(info.outputs["Geometry"], instance.inputs["Instance"])
links.new(g_in.outputs["Geometry"], join.inputs["Geometry"])
links.new(instance.outputs["Instances"], join.inputs["Geometry"])
links.new(join.outputs["Geometry"], g_out.inputs["Geometry"])

mod = target.modifiers.new("Scatter", "NODES")
mod.node_group = group
# Blender 5.2: modifier inputs live on mod.properties.inputs, keyed by socket
# identifier (not name); the old mod["Socket_2"] = value form raises TypeError.
ids = {item.name: item.identifier for item in iface.items_tree
       if item.item_type == "SOCKET" and item.in_out == "INPUT"}
inputs = mod.properties.inputs
getattr(inputs, ids["Instance"]).value = stud
getattr(inputs, ids["Density"]).value = 60.0
getattr(inputs, ids["Seed"]).value = 3
target.update_tag()
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = target.evaluated_get(depsgraph)
print(mod.name, "instances:", sum(1 for i in depsgraph.object_instances if i.is_instance and i.parent == evaluated))
```

Notes:
- Restrict scattering to part of the surface with the Distribute node's Selection input (e.g. faces whose normal points up via a Compare on the Normal node).
- Density is per square metre; a 0.5 m crate face is 0.25 m².
- Keep instances low-poly; hundreds of instances of a 20-face stud is fine, thousands of detailed meshes is not.
- Add a Realize Instances node before the output only if a later step needs the scattered geometry as real mesh.
- Scattered instances are separate pieces sitting on or in the surface, not fused into it. That is usually right for small repeated details: cheap, and easy to change. `whittle.mesh_report` does not see them. Say in your reply that the details are instances.
