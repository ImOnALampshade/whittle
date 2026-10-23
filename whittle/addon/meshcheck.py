# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh health numbers and a weld, exposed to agent code as whittle.mesh_report
and whittle.weld. They describe what was built; deciding what to do about the
numbers is the agent's job (the mesh-check skill explains them)."""

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

# Object types that evaluate to a mesh, so to_mesh works on them.
GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META"}


def _shells(bm) -> int:
    seen, shells = set(), 0
    for face in bm.faces:
        if face.index in seen:
            continue
        shells += 1
        seen.add(face.index)
        stack = [face]
        while stack:
            for edge in stack.pop().edges:
                for other in edge.link_faces:
                    if other.index not in seen:
                        seen.add(other.index)
                        stack.append(other)
    return shells


def _self_intersections(bm) -> int:
    """Face pairs that cross each other. Neighbours that share a vertex touch by
    construction, so they do not count."""
    if not bm.faces:
        return 0
    face_verts = [{v.index for v in f.verts} for f in bm.faces]
    bvh = BVHTree.FromBMesh(bm, epsilon=0.0)
    return sum(1 for a, b in bvh.overlap(bvh) if a < b and not face_verts[a] & face_verts[b])


def mesh_report(obj, evaluated: bool = True, dist: float = 1e-5) -> dict:
    """Health of obj's mesh in world space. evaluated=True measures the result of
    the live modifiers; evaluated=False measures obj.data alone."""
    if obj is None:
        raise TypeError("mesh_report needs an object, got None; whittle.targets() lists the targets")
    bm = bmesh.new()
    try:
        if evaluated:
            if obj.type not in GEOMETRY_TYPES:
                raise TypeError(f"{obj.name} is a {obj.type} and has no mesh geometry")
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = ev.to_mesh()
            bm.from_mesh(mesh)
            ev.to_mesh_clear()
        elif obj.type == "MESH":
            bm.from_mesh(obj.data)
        else:
            raise TypeError(f"{obj.name} is a {obj.type}, not a mesh; use evaluated=True")
        bm.transform(obj.matrix_world)
        bm.verts.index_update()
        bm.faces.index_update()
        report = {
            "verts": len(bm.verts),
            "faces": len(bm.faces),
            "tris": sum(len(f.verts) - 2 for f in bm.faces),
            "quads": sum(1 for f in bm.faces if len(f.verts) == 4),
            "ngons": sum(1 for f in bm.faces if len(f.verts) > 4),
            "shells": _shells(bm),
            # Edges without exactly two faces: holes, open seams, fins, wire edges.
            "open_edges": sum(1 for e in bm.edges if len(e.link_faces) != 2),
            "bad_verts": sum(1 for v in bm.verts if not v.link_faces or not v.is_manifold),
            # Manifold edges whose two faces wind opposite ways.
            "flipped_edges": sum(1 for e in bm.edges if e.is_manifold and not e.is_contiguous),
            "duplicate_verts": len(bmesh.ops.find_doubles(bm, verts=bm.verts[:], dist=dist)["targetmap"]),
            "tiny_faces": sum(1 for f in bm.faces if f.calc_area() < dist * dist),
            "self_intersections": _self_intersections(bm),
            "volume": round(bm.calc_volume(signed=True), 6),
        }
    finally:
        bm.free()
    # Watertight: closed, consistently wound, outward. Says nothing about shells
    # buried inside each other; shells and self_intersections show that.
    report["watertight"] = (bool(report["faces"]) and not report["open_edges"] and not report["bad_verts"]
                            and not report["flipped_edges"] and report["volume"] > 0)
    return report


def weld(obj, dist: float = 1e-4) -> dict:
    """Merges near-duplicate vertices, dissolves degenerate geometry, deletes
    loose vertices and recalculates normals outward on obj's own mesh. It does
    not fuse overlapping parts; only a union or growing the part does that."""
    if obj is None:
        raise TypeError("weld needs a mesh object, got None")
    if obj.type != "MESH":
        raise TypeError(f"weld works on mesh objects; {obj.name} is a {obj.type}. Convert it to a "
                        "mesh first (bpy.data.meshes.new_from_object)")
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        verts_before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
        bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=bm.edges[:])
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        removed = verts_before - len(bm.verts)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return {"removed_verts": removed}
