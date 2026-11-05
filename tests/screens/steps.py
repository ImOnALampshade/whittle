# SPDX-License-Identifier: GPL-3.0-or-later
"""What the screenshot scenarios are written with that needs no Blender: the
waits and the popup a scenario yields or returns, the fake agent's steps,
and the code its turns run. tests/screens/scenarios.py and the docs site's
shot specs (tests/docshots/spec.py) share it. Stdlib only."""

LID = ("mesh = bpy.data.meshes.new('Crate_Lid')\nbm = bmesh.new()\nbmesh.ops.create_cube(bm, size=1.0)\n"
       "bm.to_mesh(mesh)\nbm.free()\nlid = bpy.data.objects.new('Crate_Lid', mesh)\n"
       "lid.scale = (0.54, 0.54, 0.04)\nlid.location = (0, 0, 0.52)\n"
       "bpy.context.scene.collection.objects.link(lid)\nprint('lid', lid.name)")

# What the fake turns build, so each render shows what its reply says.

# A handle slot carved into the crate's front, below the lid: still one
# closed mesh of quads.
SLOT = """crate = bpy.data.objects['Crate']
bm = bmesh.new()
bm.from_mesh(crate.data)
# Cut the faces into a grid whose middle cell on the front is the slot,
# then push that cell in.
for co, no in (((-0.13, 0, 0), (1, 0, 0)), ((0.13, 0, 0), (1, 0, 0)),
               ((0, 0, 0.065), (0, 0, 1)), ((0, 0, 0.155), (0, 0, 1))):
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=no)
bm.normal_update()
front = [f for f in bm.faces if f.normal.y < -0.9]
cell = min(front, key=lambda f: (f.calc_center_median() - Vector((0, -0.25, 0.11))).length)
slot = bmesh.ops.extrude_discrete_faces(bm, faces=[cell])['faces'][0]
bmesh.ops.translate(bm, verts=slot.verts, vec=(0, 0.12, 0))
bm.normal_update()
bm.to_mesh(crate.data)
bm.free()
print(whittle.mesh_report(crate))"""

DARKER_WOOD_LIGHTER_LID = """bpy.data.materials['Wood'].diffuse_color = (0.3, 0.18, 0.08, 1)
paint = bpy.data.materials.new('Lid')
paint.diffuse_color = (0.85, 0.7, 0.5, 1)
bpy.data.objects['Crate_Lid'].data.materials.append(paint)"""

# Two horns grown out of the crate's top, so it stays one closed mesh: a
# square of a 3 x 3 grid on each side of the top, extruded into 5 rings
# that taper and lean outwards, then merged to a point.
HORNS = """crate = bpy.data.objects['Crate']
bm = bmesh.new()
bm.from_mesh(crate.data)
top = max(bm.faces, key=lambda f: f.calc_center_median().z)
bmesh.ops.subdivide_edges(bm, edges=top.edges[:], cuts=2, use_grid_fill=True)
for side in (-1, 1):
    face = min((f for f in bm.faces if f.normal.z > 0.9),
               key=lambda f: (f.calc_center_median() - Vector((side * 0.17, 0, 0.25))).length)
    for ring in range(1, 6):
        lean = side * math.radians(14 * ring)
        face = bmesh.ops.extrude_discrete_faces(bm, faces=[face])['faces'][0]
        centre = face.calc_center_median()
        moved = centre + Vector((math.sin(lean), 0, math.cos(lean))) * 0.07
        tilt = Matrix.Rotation(side * math.radians(14), 3, 'Y')
        for v in face.verts:
            v.co = moved + tilt @ (v.co - centre) * 0.78
    tip = face.calc_center_median() + Vector((math.sin(lean), 0, math.cos(lean))) * 0.05
    bmesh.ops.pointmerge(bm, verts=face.verts[:], merge_co=tip)
bm.normal_update()
bm.to_mesh(crate.data)
bm.free()
print(whittle.mesh_report(crate))"""

ROPE_HANDLES = """import math
rope = bpy.data.materials.new('Rope')
rope.diffuse_color = (0.78, 0.66, 0.42, 1)
for side in (-1, 1):
    ring, tube, rings, sides = 0.08, 0.014, 32, 10
    verts, faces = [], []
    for i in range(rings):
        a = 2 * math.pi * i / rings
        for j in range(sides):
            b = 2 * math.pi * j / sides
            r = ring + tube * math.cos(b)
            verts.append((side * (0.25 + tube * math.sin(b)), r * math.cos(a), 0.3 + r * math.sin(a)))
            n = (i + 1) % rings
            faces.append((i * sides + j, i * sides + (j + 1) % sides,
                          n * sides + (j + 1) % sides, n * sides + j))
    mesh = bpy.data.meshes.new('Handle')
    mesh.from_pydata(verts, [], faces)
    mesh.shade_smooth()
    mesh.materials.append(rope)
    handle = bpy.data.objects.new('Handle', mesh)
    bpy.context.scene.collection.objects.link(handle)"""

# Boxes, each (size, centre), joined into one object.
_BOXES = """def boxes(name, parts, material):
    bm = bmesh.new()
    for size, centre in parts:
        verts = bmesh.ops.create_cube(bm, size=1.0)['verts']
        bmesh.ops.scale(bm, vec=size, verts=verts)
        bmesh.ops.translate(bm, vec=centre, verts=verts)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
metal = bpy.data.materials.new('Metal')
metal.diffuse_color = (0.5, 0.52, 0.55, 1)
metal.metallic = 1.0
"""

# A bar standing off each side on two posts.
METAL_HANDLES = _BOXES + """for side in (-1, 1):
    boxes('Handle', [((0.03, 0.2, 0.03), (side * 0.3, 0, 0.32)),
                     ((0.07, 0.03, 0.03), (side * 0.27, -0.085, 0.32)),
                     ((0.07, 0.03, 0.03), (side * 0.27, 0.085, 0.32))], metal)"""

# A band around the crate near each end.
METAL_BANDS = _BOXES + """for x in (-0.17, 0.17):
    boxes('Band', [((0.04, 0.52, 0.52), (x, 0, 0.25))], metal)"""

BEVEL_AND_LID = """crate = bpy.data.objects['Crate']
bevel = crate.modifiers.new('Bevel', 'BEVEL')
bevel.width, bevel.segments = 0.02, 3
mesh = bpy.data.meshes.new('Crate_Lid')
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bm.to_mesh(mesh)
bm.free()
lid = bpy.data.objects.new('Crate_Lid', mesh)
lid.scale = (0.56, 0.56, 0.05)
lid.location = (0, 0, 0.525)
bpy.context.scene.collection.objects.link(lid)
lid.modifiers.new('Bevel', 'BEVEL').segments = 3
lid.modifiers['Bevel'].width = 0.012
paint = bpy.data.materials.new('Lid')
paint.diffuse_color = (0.62, 0.45, 0.26, 1)
mesh.materials.append(paint)"""

DARKEN = "bpy.data.materials['Wood'].diffuse_color = (0.32, 0.19, 0.09, 1)"


class Until:
    def __init__(self, check, what: str):
        self.check = check
        self.what = what


class Popup:
    """Returned by a scenario to shoot a popover or a menu opened over the
    sidebar instead of the sidebar alone: ("panel", panel id) opens a panel
    as a popup, ("operator", op id, {props}) invokes an operator that opens
    one."""

    def __init__(self, kind: str, name: str, props: dict | None = None):
        self.kind = kind
        self.name = name
        self.props = props or {}


# -- fake agent steps ---------------------------------------------------------

def say(text: str) -> dict:
    return {"say": text}


def exec_(label: str, code: str, **extra) -> dict:
    return {"call": "exec", "params": {"label": label, "code": code}, **extra}


def render(location, mode: str = "shaded", look_at=(0.0, 0.0, 0.3), **extra) -> dict:
    return {"call": "render", "params": {"camera": {"location": list(location), "look_at": list(look_at)},
                                         "mode": mode, "size": 128}, **extra}


def done(result: str) -> dict:
    return {"subtype": "success", "is_error": False, "result": result}
