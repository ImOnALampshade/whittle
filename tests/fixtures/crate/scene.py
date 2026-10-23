# SPDX-License-Identifier: GPL-3.0-or-later
"""The scene the crate bundle was drawn over: a 0.5 m cube "Crate" resting on
the ground at the origin. Run inside Blender."""

import bmesh
import bpy

CRATE = "Crate"
SIZE = 0.5


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for collection in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights,
                       bpy.data.grease_pencils, bpy.data.images):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


def build_scene():
    clear_scene()
    scene = bpy.context.scene
    mesh = bpy.data.meshes.new(CRATE)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=SIZE)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(CRATE, mesh)
    obj.location = (0.0, 0.0, SIZE / 2)
    scene.collection.objects.link(obj)
    mat = bpy.data.materials.get("Wood") or bpy.data.materials.new("Wood")
    mat.diffuse_color = (0.45, 0.28, 0.12, 1.0)
    mesh.materials.append(mat)
    scene.frame_set(1)
    return obj


if __name__ == "__main__":
    build_scene()
