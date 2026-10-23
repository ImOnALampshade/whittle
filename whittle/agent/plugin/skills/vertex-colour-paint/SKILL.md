---
name: vertex-colour-paint
description: Colours props with flat per-face materials or vertex colours that Whittle's Workbench renders can show, covering material slots, diffuse colour and colour attributes. Use when the prompt asks for colours, paint, materials, two-tone parts, gradients, dirt or wear.
---

# Flat colours and vertex colours

Whittle's self-check renders are Workbench renders in MATERIAL colour mode, which show each material's **viewport display colour** (`material.diffuse_color`). Set it on every material you make, as well as the Principled BSDF base colour so the look survives in EEVEE and Cycles.

Per-face flat colours with material slots, the default because every render shows them:

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]


def flat_material(name, rgb, roughness=0.8):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    mat.roughness = roughness
    if mat.node_tree is not None:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
            bsdf.inputs["Roughness"].default_value = roughness
    return mat


wood = flat_material("Wood_Light", (0.55, 0.36, 0.18))
metal = flat_material("Metal_Dark", (0.12, 0.12, 0.13), roughness=0.4)
mesh = target.data
for mat in (wood, metal):
    if mat.name not in [m.name for m in mesh.materials if m]:
        mesh.materials.append(mat)
slot = {m.name: i for i, m in enumerate(mesh.materials) if m}
# Example rule: faces pointing up get the metal trim colour.
for poly in mesh.polygons:
    poly.material_index = slot["Metal_Dark"] if poly.normal.z > 0.9 else slot["Wood_Light"]
print({m.name: sum(p.material_index == i for p in mesh.polygons) for i, m in enumerate(mesh.materials) if m})
```

Vertex colours (for gradients, dirt or wear; Workbench shows them only with the VERTEX colour type, so describe them rather than relying on the self-check render):

```python
target = bpy.data.objects.get("Crate") or whittle.targets()[0]
mesh = target.data
colours = mesh.color_attributes.get("Col") or mesh.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
mesh.color_attributes.active_color = colours
low, high = Vector((0.35, 0.22, 0.1)), Vector((0.6, 0.42, 0.22))
z_min = min(v.co.z for v in mesh.vertices)
z_max = max(v.co.z for v in mesh.vertices)
for loop in mesh.loops:
    t = (mesh.vertices[loop.vertex_index].co.z - z_min) / max(z_max - z_min, 1e-6)
    c = low.lerp(high, t)
    colours.data[loop.index].color = (c.x, c.y, c.z, 1.0)
print(colours.name, len(colours.data))
```

To use vertex colours in a material, add a Color Attribute node (`ShaderNodeVertexColor`, `layer_name = "Col"`) feeding the Principled Base Color.

Notes:
- Reuse materials across objects of one prop; name them by look (`Wood_Dark`, `Iron`, `Paint_Red`).
- No image textures: Whittle props use flat colours and vertex colours.
