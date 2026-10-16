"""Builds the pug: a black pug on four legs, its armature, and one action per pose
name the sim reports (`Fighter::anim()`), then saves `pug.blend` next to this script
and exports `godot/models/pug.glb`.

    blender --background --factory-startup --python art/pug/build_pug.py

Conventions (see README.md, and art/fighter/README.md for the shared rules):
- Meters, paws on the ground at the origin, facing +X, the dog's left = +Y.
- 60 fps. Attack actions are keyed on the sim's 1-based move frames.
- Pose angles are degrees, counter-clockwise as seen by the game camera with the
  dog facing right: + tips a forward-pointing bone (head, chest) up, swings a
  hanging leg forward, and swings a backward-pointing bone (pelvis) down.
  Child angles are relative to the parent.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "pug.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "pug.glb")

sys.path.insert(0, os.path.join(ROOT, "art", "fighter"))
from build_fighter import export  # noqa: E402  (same glTF settings for every model)

FPS = 60

# --- Skeleton ---------------------------------------------------------------
# Joint positions (x forward, z up) for the dog's left side; the right mirrors y.
SHOULDER, ELBOW, WRIST, FTOE = (0.17, 0.12, 0.38), (0.13, 0.12, 0.22), (0.15, 0.12, 0.065), (0.215, 0.12, 0.03)
HIP, STIFLE, HOCK, ANKLE, HTOE = (-0.17, 0.105, 0.40), (-0.075, 0.105, 0.25), (-0.20, 0.105, 0.13), (-0.18, 0.105, 0.05), (-0.10, 0.105, 0.03)


def ear_frame(s):
    """Root, tip, and the direction away from the skull of one ear (s=1 left)."""
    root = Vector((0.375, s * 0.125, 0.785))
    tip = Vector((0.445, s * 0.175, 0.705))
    down = (tip - root).normalized()
    out = Vector((0.1, s * 1.0, 0.55))
    return root, tip, (out - down * out.dot(down)).normalized()


# name, parent, head, tail. Every bone except the ears lies in the side (x-z) plane
# and is rolled so its local X = world +Y: one angle per bone poses it as seen by
# the camera.
BONES = [
    ("body", None, (0, 0, 0.42), (0, 0, 0.52)),
    ("pelvis", "body", (0, 0, 0.42), (-0.22, 0, 0.45)),
    ("chest", "body", (0, 0, 0.42), (0.20, 0, 0.45)),
    ("neck", "chest", (0.20, 0, 0.47), (0.32, 0, 0.58)),
    ("head", "neck", (0.32, 0, 0.62), (0.54, 0, 0.62)),
    ("jaw", "head", (0.40, 0, 0.56), (0.55, 0, 0.535)),
    ("tail", "pelvis", (-0.23, 0, 0.50), (-0.21, 0, 0.60)),
]
EAR_OUT = {}  # ear bone -> direction away from the skull (its roll target)
for side, s in (("L", 1), ("R", -1)):
    m = lambda p: (p[0], s * p[1], p[2])  # noqa: E731
    ear_root, ear_tip, EAR_OUT[f"ear.{side}"] = ear_frame(s)
    BONES += [
        (f"ear.{side}", "head", tuple(ear_root), tuple(ear_tip)),
        (f"upper_arm.{side}", "chest", m(SHOULDER), m(ELBOW)),
        (f"forearm.{side}", f"upper_arm.{side}", m(ELBOW), m(WRIST)),
        (f"hand.{side}", f"forearm.{side}", m(WRIST), m(FTOE)),
        (f"thigh.{side}", "pelvis", m(HIP), m(STIFLE)),
        (f"shin.{side}", f"thigh.{side}", m(STIFLE), m(HOCK)),
        (f"hock.{side}", f"shin.{side}", m(HOCK), m(ANKLE)),
        (f"foot.{side}", f"hock.{side}", m(ANKLE), m(HTOE)),
    ]
BONE_NAMES = [b[0] for b in BONES]
PLANAR = [b[0] for b in BONES if not b[0].startswith("ear")]

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the
# collar) with the player's color; the rest keep their own.
MATERIALS = {
    "Fur": ((0.03, 0.028, 0.028, 1), 0.72, 0.0),
    "Body": ((0.8, 0.15, 0.15, 1), 0.45, 0.0),
    "Accent": ((1.0, 0.72, 0.28, 1), 0.25, 1.0),
    "Nose": ((0.012, 0.010, 0.010, 1), 0.28, 0.0),
    "Eye": ((0.018, 0.008, 0.004, 1), 0.03, 0.0),
    "Catchlight": ((1, 1, 1, 1), 0.3, 0.0),
    "Tongue": ((0.85, 0.30, 0.36, 1), 0.32, 0.0),
    "Mouth": ((0.16, 0.025, 0.035, 1), 0.5, 0.0),
}


# --- Mesh -------------------------------------------------------------------
# The fur is one smooth surface made of metaballs (so the body, legs and head blend
# like flesh), converted to a mesh and skinned with automatic weights. Small parts
# (eyes, nose, ears, tail, collar) are separate rigid pieces on one bone each.


def stiff_k(stiffness, threshold=0.6):
    """Fraction of a metaball's radius where its surface sits (alone)."""
    return math.sqrt(1 - (threshold / stiffness) ** (1 / 3))


def quat_x_to(direction):
    return Vector(direction).normalized().to_track_quat("X", "Z")


class Blob:
    def __init__(self, resolution):
        self.mb = bpy.data.metaballs.new("PugBlob")
        self.mb.resolution = resolution
        self.mb.render_resolution = resolution
        self.mb.threshold = 0.6

    def ell(self, center, semi, stiffness=2.5, rot=None, negative=False):
        """Ellipsoid with visible semi-axes `semi` (when alone)."""
        k = stiff_k(stiffness)
        r = max(semi) / k
        e = self.mb.elements.new(type="ELLIPSOID")
        e.co, e.radius, e.stiffness, e.use_negative = center, r, stiffness, negative
        e.size_x, e.size_y, e.size_z = (a / max(semi) for a in semi)
        if rot is not None:
            e.rotation = rot
        return e

    def ball(self, center, radius, stiffness=2.5, negative=False):
        return self.ell(center, (radius,) * 3, stiffness, negative=negative)

    def cap(self, a, b, radius, stiffness=2.5, negative=False):
        """Capsule from a to b."""
        a, b = Vector(a), Vector(b)
        e = self.mb.elements.new(type="CAPSULE")
        e.co = (a + b) / 2
        e.radius = radius / stiff_k(stiffness)
        e.size_x = (b - a).length / 2
        e.rotation = quat_x_to(b - a)
        e.stiffness, e.use_negative = stiffness, negative
        return e


def fur_blob():
    b = Blob(resolution=0.005)
    # Torso: broad barrel chest, round rump.
    b.ell((0.12, 0, 0.405), (0.165, 0.172, 0.165))
    b.ell((-0.02, 0, 0.415), (0.16, 0.16, 0.15))
    b.ell((-0.155, 0, 0.425), (0.12, 0.15, 0.14))
    # Neck, thick and short, and a dewlap fold under it.
    b.cap((0.19, 0, 0.47), (0.31, 0, 0.585), 0.11)
    b.ell((0.27, 0, 0.455), (0.07, 0.085, 0.05), stiffness=3)
    # Head: big round skull, flat face, cheeks, a very short muzzle.
    b.ell((0.375, 0, 0.665), (0.145, 0.155, 0.138))
    b.ell((0.455, 0, 0.625), (0.09, 0.135, 0.108))
    for s in (1, -1):
        b.ell((0.478, s * 0.072, 0.585), (0.07, 0.058, 0.045), stiffness=2.5)  # jowls
        b.ell((0.41, s * 0.125, 0.63), (0.07, 0.04, 0.07), stiffness=3)  # cheekbones
        # Brows: soft, the inner ends raised (the worried pug look).
        b.ell((0.478, s * 0.07, 0.74), (0.026, 0.038, 0.012), stiffness=3, rot=Quaternion((1, 0, 0), math.radians(-18 * s)))
        # Eye sockets, so the eyes sit in the face rather than on it.
        b.ball((0.5, s * 0.08, 0.675), 0.03, stiffness=4, negative=True)
    b.ell((0.522, 0, 0.608), (0.04, 0.07, 0.044), stiffness=3)  # muzzle
    b.ell((0.515, 0, 0.572), (0.04, 0.065, 0.03), stiffness=3)  # upper lip
    # The nose roll: a fold of skin arching over the nose, with a deep crease under it.
    for y in (-0.05, -0.03, -0.01, 0.01, 0.03, 0.05):
        b.ball((0.548 - abs(y) * 0.35, y, 0.66 - 4 * y * y), 0.019, stiffness=5)
    b.cap((0.552, -0.055, 0.637), (0.552, 0.055, 0.637), 0.009, stiffness=6, negative=True)
    # Forehead wrinkles: a V of grooves between the brows and a line across.
    b.cap((0.495, -0.03, 0.79), (0.522, -0.004, 0.74), 0.008, stiffness=6, negative=True)
    b.cap((0.495, 0.03, 0.79), (0.522, 0.004, 0.74), 0.008, stiffness=6, negative=True)
    b.cap((0.47, -0.06, 0.785), (0.485, 0, 0.795), 0.007, stiffness=6, negative=True)
    b.cap((0.485, 0, 0.795), (0.47, 0.06, 0.785), 0.007, stiffness=6, negative=True)
    for side, s in (("L", 1), ("R", -1)):
        m = lambda p: (p[0], s * p[1], p[2])  # noqa: E731
        # Front leg: shoulder muscle, upper arm, forearm, paw with toes.
        b.ell(m((0.15, 0.1, 0.37)), (0.085, 0.065, 0.1), stiffness=3)
        b.cap(m(SHOULDER), m(ELBOW), 0.055)
        b.cap(m(ELBOW), m(WRIST), 0.042, stiffness=3)
        b.ell(m((WRIST[0] + 0.03, WRIST[1], 0.034)), (0.05, 0.042, 0.032), stiffness=3)
        for dy in (-0.025, -0.009, 0.009, 0.025):
            b.ball(m((WRIST[0] + 0.065, WRIST[1] + dy, 0.022)), 0.014, stiffness=5)
        # Hind leg: big thigh, shin, hock, paw with toes.
        b.ell(m((-0.14, 0.095, 0.36)), (0.1, 0.07, 0.115), stiffness=3)
        b.cap(m(HIP), m(STIFLE), 0.065)
        b.cap(m(STIFLE), m(HOCK), 0.042, stiffness=3)
        b.cap(m(HOCK), m(ANKLE), 0.03, stiffness=3)
        b.ell(m((ANKLE[0] + 0.035, ANKLE[1], 0.032)), (0.048, 0.038, 0.03), stiffness=3)
        for dy in (-0.022, -0.008, 0.008, 0.022):
            b.ball(m((ANKLE[0] + 0.07, ANKLE[1] + dy, 0.02)), 0.013, stiffness=5)
    return b.mb


def chin_blob():
    """The lower jaw, a separate piece so the mouth can open: tucked under the
    jowls, with a slight underbite."""
    b = Blob(resolution=0.005)
    b.ell((0.49, 0, 0.532), (0.062, 0.075, 0.03), stiffness=3)
    b.ell((0.43, 0, 0.535), (0.06, 0.08, 0.035), stiffness=3)
    return b.mb


def blob_mesh(mb, ratio):
    blob = bpy.data.objects.new("Blob", mb)
    bpy.context.scene.collection.objects.link(blob)
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(blob.evaluated_get(dg))
    bpy.data.objects.remove(blob)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    bm.to_mesh(mesh)
    bm.free()
    if ratio < 1:
        obj = bpy.data.objects.new("Blob", mesh)
        bpy.context.scene.collection.objects.link(obj)
        dec = obj.modifiers.new("Decimate", "DECIMATE")
        dec.ratio = ratio
        dg = bpy.context.evaluated_depsgraph_get()
        out = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        mesh = out
    for p in mesh.polygons:
        p.use_smooth = True
    return mesh


def uv_ellipsoid(bm, center, semi, rot=Quaternion(), segments=(24, 14)):
    matrix = Matrix.Translation(center) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal((*semi, 1))
    return bmesh.ops.create_uvsphere(bm, u_segments=segments[0], v_segments=segments[1], radius=1.0, matrix=matrix)["verts"]


def tube(bm, points, radii, sides=12):
    """A closed tube along `points` (rounded caps), returns its verts."""
    rings = []
    for i, p in enumerate(points):
        p = Vector(p)
        a = Vector(points[max(i - 1, 0)])
        c = Vector(points[min(i + 1, len(points) - 1)])
        t = (c - a).normalized()
        n = t.orthogonal().normalized() if i == 0 else (n - t * n.dot(t)).normalized()
        bn = t.cross(n)
        ring = [bm.verts.new(p + radii[i] * (math.cos(2 * math.pi * j / sides) * n + math.sin(2 * math.pi * j / sides) * bn)) for j in range(sides)]
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(sides):
            bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    verts = [v for r in rings for v in r]
    for ring, tip in ((rings[0], points[0]), (rings[-1], points[-1])):
        center = bm.verts.new(Vector(tip))
        verts.append(center)
        for j in range(sides):
            bm.faces.new((ring[(j + 1) % sides], ring[j], center))
    bm.normal_update()
    return verts


class Parts:
    """Rigid pieces, each vertex fully weighted to one bone."""

    def __init__(self):
        self.bm = bmesh.new()
        self.deform = self.bm.verts.layers.deform.verify()

    def assign(self, verts, bone, mat, smooth=True):
        group = BONE_NAMES.index(bone)
        for v in verts:
            v[self.deform][group] = 1.0
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = list(MATERIALS).index(mat)
            f.smooth = smooth


def ear(parts, s):
    """A button ear: a thin triangular flap on the top of the skull, folded forward
    so its tip points at the outer corner of the eye."""
    root, tip, out = ear_frame(s)
    down = (tip - root).normalized()
    across = down.cross(out)
    length, half_width = (tip - root).length, 0.042
    verts = uv_ellipsoid(parts.bm, (0, 0, 0), (1, 1, 1), segments=(20, 12))
    for v in verts:
        a, t, d = v.co  # across, thickness, along (-1 root .. 1 tip)
        along = (1 - d) / 2  # 0 at the tip
        u = 1 - along  # 0 at the root, 1 at the tip
        w = half_width * (1 - 0.8 * u) * a
        bow = 0.014 * math.sin(math.pi * u) + 0.008 * (1 - a * a)
        v.co = root + down * (length * (u * 1.05 - 0.1)) + across * w + out * (bow + 0.0055 * t)
    parts.assign(verts, f"ear.{'L' if s > 0 else 'R'}", "Fur")


def curled_tail(parts):
    """Rises off the rump and curls tight over the hip."""
    pts, radii = [], []
    n = 60
    center = Vector((-0.195, 0.035, 0.6))
    normal = Vector((0.1, 1, 0.3)).normalized()  # the coil faces the camera side and up
    u_axis = Vector((-1, 0, 0))
    v_axis = normal.cross(u_axis)
    for i in range(n):
        t = i / (n - 1)
        if t < 0.12:  # root, going up out of the rump
            p = Vector((-0.235, 0, 0.5)).lerp(center + u_axis * 0.062, t / 0.12)
        else:
            u = (t - 0.12) / 0.88
            ang = -2 * math.pi * 1.5 * u
            r = 0.062 * (1 - 0.6 * u)
            p = center + r * (math.cos(ang) * u_axis + math.sin(ang) * v_axis) + normal * (0.012 * u)
        pts.append(p)
        radii.append(0.034 - 0.018 * t)
    parts.assign(tube(parts.bm, pts, radii, sides=14), "tail", "Fur")


def collar(parts):
    axis = Vector((0.12, 0, 0.11)).normalized()
    center = Vector((0.255, 0, 0.525))
    rot = axis.to_track_quat("Z", "X")
    sides, ring = 16, 40
    verts = []
    grid = []
    for i in range(ring):
        a = 2 * math.pi * i / ring
        row = []
        for j in range(sides):
            b = 2 * math.pi * j / sides
            r = 0.118 + 0.011 * math.cos(b)
            z = 0.022 * math.sin(b)
            # Hangs a little lower at the front, the way a collar sits on a pug.
            local = Vector((r * math.cos(a), r * math.sin(a), z))
            p = center + rot @ local
            v = parts.bm.verts.new(p)
            row.append(v)
        grid.append(row)
        verts += row
    for i in range(ring):
        for j in range(sides):
            a, b = grid[i][j], grid[i][(j + 1) % sides]
            c, d = grid[(i + 1) % ring][(j + 1) % sides], grid[(i + 1) % ring][j]
            parts.bm.faces.new((a, b, c, d))
    parts.assign(verts, "neck", "Body")
    # Tag: a little gold disc hanging from the front of the collar.
    down_front = Vector((0.5, 0, -1))
    down_front = (down_front - axis * axis.dot(down_front)).normalized()
    ring_front = center + down_front * 0.13
    facing = Vector((1, 0, -0.25)).normalized()
    tag = bmesh.ops.create_cone(
        parts.bm, cap_ends=True, segments=20, radius1=0.026, radius2=0.026, depth=0.006,
        matrix=Matrix.Translation(ring_front + Vector((0.004, 0, -0.026))) @ facing.to_track_quat("Z", "Y").to_matrix().to_4x4(),
    )["verts"]
    parts.assign(tag, "neck", "Accent")


def face_parts(parts):
    for s in (1, -1):
        eye_c = Vector((0.488, s * 0.08, 0.675))
        parts.assign(uv_ellipsoid(parts.bm, eye_c, (0.041, 0.041, 0.041)), "head", "Eye")
        glint = eye_c + Vector((0.65, s * 0.05, 0.5)).normalized() * 0.039
        parts.assign(uv_ellipsoid(parts.bm, glint, (0.008, 0.008, 0.008), segments=(10, 6)), "head", "Catchlight")
    # Nose: flat and wide, a little wider at the top, with comma-shaped nostrils.
    nose = uv_ellipsoid(parts.bm, (0.556, 0, 0.622), (0.018, 0.04, 0.025), segments=(32, 16))
    for v in nose:
        x, y, z = v.co - Vector((0.556, 0, 0.622))
        v.co.y = y * (1 + 0.25 * z / 0.025)
        for s in (1, -1):
            d = ((y - s * 0.02) / 0.011) ** 2 + ((z + 0.003) / 0.006) ** 2
            if x > 0 and d < 1:
                v.co.x -= 0.016 * (1 - d)
    parts.assign(nose, "head", "Nose")
    # Inside of the mouth, seen when the jaw drops.
    parts.assign(uv_ellipsoid(parts.bm, (0.475, 0, 0.553), (0.065, 0.058, 0.016)), "head", "Mouth")
    parts.assign(uv_ellipsoid(parts.bm, (0.47, 0, 0.545), (0.06, 0.055, 0.012)), "jaw", "Mouth")
    tongue = uv_ellipsoid(parts.bm, (0.515, 0.004, 0.547), (0.05, 0.034, 0.01), Quaternion((0, 1, 0), math.radians(12)))
    parts.assign(tongue, "jaw", "Tongue")
    # The lower jaw.
    chin = blob_mesh(chin_blob(), 0.3)
    verts = [parts.bm.verts.new(v.co) for v in chin.vertices]
    for poly in chin.polygons:
        parts.bm.faces.new([verts[i] for i in poly.vertices])
    parts.assign(verts, "jaw", "Fur")
    bpy.data.meshes.remove(chin)


def build_meshes(rig):
    mats = []
    for name, (color, rough, metal) in MATERIALS.items():
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        if mat.node_tree is None:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        if name == "Catchlight":
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = 1.5
        mats.append(mat)

    # Fur: metaballs -> mesh -> automatic weights.
    fur_mesh = blob_mesh(fur_blob(), 0.15)
    fur = bpy.data.objects.new("Pug", fur_mesh)
    bpy.context.scene.collection.objects.link(fur)
    for m in mats:
        fur_mesh.materials.append(m)

    # Ears and tail are rigid pieces of their own: keep them out of the heat weights.
    rigid = ("ear.L", "ear.R", "tail")
    for name in rigid:
        rig.data.bones[name].use_deform = False
    bpy.ops.object.select_all(action="DESELECT")
    fur.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    for name in rigid:
        rig.data.bones[name].use_deform = True
    # Heat weighting can leave weights slightly over 1.
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = fur
    fur.select_set(True)
    # Vertices near the ear and tail roots can come out with no weights at all;
    # give them to the nearest bone's segment so nothing stays behind at rest.
    segments = [(fur.vertex_groups[n].index, Vector(rig.data.bones[n].head_local), Vector(rig.data.bones[n].tail_local))
                for n in BONE_NAMES if n not in rigid and n in fur.vertex_groups]
    for v in fur_mesh.vertices:
        if sum(g.weight for g in v.groups) > 1e-4:
            continue
        def dist(seg):
            _, a, b = seg
            t = max(0.0, min(1.0, (v.co - a).dot(b - a) / (b - a).length_squared))
            return (a + (b - a) * t - v.co).length
        fur.vertex_groups[min(segments, key=dist)[0]].add([v.index], 1.0, "REPLACE")
    bpy.ops.object.vertex_group_normalize_all(lock_active=False)
    fur_mesh.validate()

    # Rigid parts.
    parts = Parts()
    face_parts(parts)
    ear(parts, 1)
    ear(parts, -1)
    curled_tail(parts)
    collar(parts)
    parts_mesh = bpy.data.meshes.new("PugParts")
    parts.bm.to_mesh(parts_mesh)
    parts.bm.free()
    for m in mats:
        parts_mesh.materials.append(m)
    obj = bpy.data.objects.new("PugParts", parts_mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = rig
    for name in BONE_NAMES:
        obj.vertex_groups.new(name=name)
    obj.modifiers.new("Armature", "ARMATURE").object = rig
    return fur, obj


# --- Rig --------------------------------------------------------------------


def roll_target(head, tail):
    """Roll so the bone's local X is world +Y (for bones in the x-z plane)."""
    d = (Vector(tail) - Vector(head)).normalized()
    return Vector((0, 1, 0)).cross(d)


def build_rig():
    rig = bpy.data.objects.new("Pug", bpy.data.armatures.new("PugRig"))
    rig.name = "PugRig"
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = rig.data.edit_bones
    for name, parent, head, tail in BONES:
        bone = edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if name in PLANAR:
            bone.align_roll(roll_target(head, tail))
            assert (bone.x_axis - Vector((0, 1, 0))).length < 1e-4, name
        else:
            # Ears: local X along the fold at the root, so + X rotation (lift) swings
            # the flap out from the skull.
            bone.align_roll(EAR_OUT[name])
        if parent:
            bone.parent = edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    return rig


# --- Poses ------------------------------------------------------------------
# A pose is {bone: degrees or (pitch, twist, spread)} plus:
#   "loc": (forward, up) offset of the whole body in meters,
#   "feet": {leg: (dx, lift[, paw_tilt[, hock_tilt]])} legs to plant by IK: the paw
#           goes dx forward of its rest spot and `lift` above the ground. Legs are
#           "FR", "FL" (front) and "HR", "HL" (hind); R is the camera side.
# Missing bones are at rest relative to their parent. Ears take (lift, twist, spread)
# in their own axes: + lift raises the tip.

REST = {}  # planar bone -> ((x, z) head, angle, length, parent)
for _name, _parent, _head, _tail in BONES:
    if _name in PLANAR:
        _dx, _dz = _tail[0] - _head[0], _tail[2] - _head[2]
        REST[_name] = ((_head[0], _head[2]), math.degrees(math.atan2(_dz, _dx)), math.hypot(_dx, _dz), _parent)
FRONT_PAW, HIND_PAW = (WRIST[0], WRIST[2]), (ANKLE[0], ANKLE[2])


def pitch(value):
    return value[0] if isinstance(value, tuple) else value


def fk(pose):
    """Posed (head (x, z), rotation from rest) of every planar bone, side view."""
    out = {}
    for name in PLANAR:
        head, _, _, parent = REST[name]
        p = pitch(pose.get(name, 0))
        if parent is None:
            fwd, up = pose.get("loc", (0, 0))
            out[name] = ((head[0] + fwd, head[1] + up), p)
            continue
        (px, pz), turn = out[parent]
        ox, oz = head[0] - REST[parent][0][0], head[1] - REST[parent][0][1]
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        out[name] = ((px + ox * c - oz * s, pz + ox * s + oz * c), turn + p)
    return out


def two_bone(pose, upper, lower, target, bend):
    """Sets `upper` and `lower` so the end of `lower` reaches `target`. bend -1 puts
    the middle joint behind (elbow), +1 in front (stifle). Returns lower's turn."""
    w = fk(pose)
    (sx, sz), _ = w[upper]
    parent_turn = w[REST[upper][3]][1]
    l1, l2 = REST[upper][2], REST[lower][2]
    dx, dz = target[0] - sx, target[1] - sz
    d = min(max(math.hypot(dx, dz), abs(l1 - l2) + 1e-4), l1 + l2 - 1e-4)
    aim = math.degrees(math.atan2(dz, dx))
    inner = math.degrees(math.acos((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    up_w = aim + bend * inner
    kx, kz = sx + l1 * math.cos(math.radians(up_w)), sz + l1 * math.sin(math.radians(up_w))
    low_w = math.degrees(math.atan2(target[1] - kz, target[0] - kx))
    pose[upper] = up_w - REST[upper][1] - parent_turn
    pose[lower] = low_w - up_w - (REST[lower][1] - REST[upper][1])
    return low_w - REST[lower][1]


def plant(pose, leg, dx=0.0, lift=0.0, paw=0.0, hock=0.0):
    side = leg[1]
    if leg[0] == "F":
        target = (FRONT_PAW[0] + dx, FRONT_PAW[1] + lift)
        turn = two_bone(pose, f"upper_arm.{side}", f"forearm.{side}", target, -1)
        pose[f"hand.{side}"] = paw - turn
    else:
        hock_w = REST[f"hock.{side}"][1] + hock
        length = REST[f"hock.{side}"][2]
        target = (
            HIND_PAW[0] + dx - length * math.cos(math.radians(hock_w)),
            HIND_PAW[1] + lift - length * math.sin(math.radians(hock_w)),
        )
        turn = two_bone(pose, f"thigh.{side}", f"shin.{side}", target, 1)
        pose[f"hock.{side}"] = hock - turn
        pose[f"foot.{side}"] = paw - hock


LEG_BONES = {
    leg: [f"{b}.{leg[1]}" for b in (("upper_arm", "forearm", "hand") if leg[0] == "F" else ("thigh", "shin", "hock", "foot"))]
    for leg in ("FR", "FL", "HR", "HL")
}


def solve(pose):
    """Copy of `pose` with its "feet" planted by IK. A leg whose bones the pose sets
    by angle is left to those angles."""
    pose = dict(pose)
    for leg, spec in pose.pop("feet", {}).items():
        if not any(b in pose for b in LEG_BONES[leg]):
            plant(pose, leg, *spec)
    return pose


def P(base=None, **changes):
    """Copy of `base` with changes; `ear_L=10` sets "ear.L", `feet` entries merge."""
    pose = dict(base or {})
    for k, v in changes.items():
        if k == "feet":
            pose["feet"] = {**pose.get("feet", {}), **v}
        elif k == "ears":
            pose["ear.L"] = pose["ear.R"] = v
        else:
            pose[k.replace("_L", ".L").replace("_R", ".R")] = v
    return pose


def stand(drop=0.0, fwd=0.0, front=0.0, hind=0.0, **changes):
    """All four paws planted; `front`/`hind` move the paw pairs forward."""
    feet = {"FR": (front, 0), "FL": (front, 0), "HR": (hind, 0), "HL": (hind, 0)}
    return P(P(loc=(fwd, -drop), feet=feet), **changes)


def flying(tuck=0.0, **changes):
    """Legs loose in the air. tuck 1 pulls them up under the body."""
    t = tuck
    return P(P(
        upper_arm_R=20 + 50 * t, forearm_R=-10 - 70 * t, hand_R=-20 - 30 * t,
        upper_arm_L=10 + 50 * t, forearm_L=-5 - 70 * t, hand_L=-20 - 30 * t,
        thigh_R=-20 + 55 * t, shin_R=10 - 55 * t, hock_R=5 + 40 * t, foot_R=20,
        thigh_L=-30 + 55 * t, shin_L=15 - 55 * t, hock_L=5 + 40 * t, foot_L=20,
        ears=(25, 0, 0)), **changes,
    )


def splayed(**changes):
    """Starfish: front legs straight forward, hind legs straight back."""
    return P(P(
        upper_arm_R=95, forearm_R=-15, hand_R=-30, upper_arm_L=85, forearm_L=-10, hand_L=-30,
        thigh_R=-110, shin_R=40, hock_R=40, foot_R=40, thigh_L=-100, shin_L=35, hock_L=40, foot_L=40,
        ears=(35, 0, 0), tail=(-20, 0, 0)), **changes,
    )


def gait(length, stride, lift, duty, phases, bob, sway=0.0, flex=0.0, head=0.0, drop=0.0):
    """One key per frame of a looping gait. Each leg's paw sweeps back along the
    ground for `duty` of the cycle and swings forward through the air for the rest."""
    keys = []
    for f in range(length + 1):
        t = f / length
        feet = {}
        for leg, phase in phases.items():
            q = (t + phase) % 1.0
            if q < duty:
                dx, up = stride / 2 - stride * q / duty, 0.0
            else:
                u = (q - duty) / (1 - duty)
                dx, up = -stride / 2 + stride * (3 * u * u - 2 * u * u * u), lift * math.sin(math.pi * u)
            feet[leg] = (dx, up, 25 * up / max(lift, 1e-6) if leg[0] == "H" else -20 * up / max(lift, 1e-6))
        w = 2 * math.pi * t
        pose = P(
            loc=(0, -drop + bob * math.cos(2 * w)),
            body=sway * math.sin(w),
            chest=flex * math.sin(w),
            pelvis=flex * math.sin(w),
            neck=-sway * math.sin(w) + 5,
            head=head - 4 * math.cos(2 * w),
            tail=(0, 25 * math.sin(2 * w), 0),
            ears=(10 * math.cos(2 * w), 0, 0),
            feet=feet,
        )
        keys.append((1 + f, pose))
    return keys


def cycle(length, keys):
    """Evenly spaced keys over a loop of `length` frames, closing back on the first."""
    step = length // len(keys)
    return [(1 + i * step, k) for i, k in enumerate(keys)] + [(1 + length, keys[0])]


IDLE = stand(neck=4, head=-2, jaw=-3, tail=(0, 0, 0))
IDLE_B = P(IDLE, loc=(0, -0.006), chest=-1.5, jaw=-9, tail=(0, 30, 0), head=0)
IDLE_C = P(IDLE, jaw=-4, tail=(0, -30, 0), head=-3)
G = IDLE
LOW = stand(drop=0.07, chest=-4, pelvis=6, neck=-4, head=6, front=0.03, hind=-0.02, jaw=-3, ears=(-10, 0, 0))
CROUCH = stand(drop=0.17, front=0.14, hind=-0.06, chest=-6, pelvis=14, neck=6, head=-4, ears=(-15, 0, 0), jaw=-2)
CROUCH_B = P(CROUCH, loc=(0, -0.175), chest=-7)
AIR = flying(0.25, body=4, neck=6, head=-6, jaw=-6, tail=(0, 0, 0))
AIR_B = P(AIR, upper_arm_R=30, forearm_R=-30, upper_arm_L=20, thigh_R=-10, thigh_L=-25, ears=(35, 0, 0))
FLINCH = flying(0.4, body=18, chest=10, neck=20, head=25, jaw=-22, ears=(55, 0, 0), tail=(-30, 0, 0), loc=(-0.03, 0))
FLINCH_B = P(FLINCH, body=22, head=30, ears=(60, 0, 0))

# Attacks: keys on the sim's frames (the pug's moves in sim/src/moves.rs). Hitboxes
# in comments are sim units (x forward, y up from the feet; 10 units = 1 m).

# Bites and nibbles
BITE_WIND = stand(fwd=-0.02, chest=4, neck=12, head=12, jaw=-28, ears=(20, 0, 0))
BITE = stand(fwd=0.07, drop=0.03, front=0.05, chest=-8, neck=-10, head=0, jaw=-2, ears=(-10, 0, 0), tail=(0, 20, 0))
BITE2_WIND = P(BITE, head=(10, -15, 0), jaw=-28, ears=(15, 0, 0))
BITE2 = P(BITE, loc=(0.09, -0.03), head=(-2, 15, 0), jaw=0, tail=(0, -20, 0))
NIB_OPEN = P(BITE, loc=(0.08, -0.03), head=(6, 10, 0), jaw=-22, ears=(10, 0, 0))
NIB_SHUT = P(BITE, loc=(0.09, -0.03), head=(-4, -10, 0), jaw=0, ears=(-5, 0, 0))

# Tilts
SWIPE_WIND = stand(chest=8, neck=4, head=-4, feet={"FR": (0.04, 0.12, -40)}, ears=(15, 0, 0))
LOW_SWIPE = stand(fwd=0.05, drop=0.03, chest=2, neck=-6, head=-2, upper_arm_R=75, forearm_R=0, hand_R=-35, ears=(-10, 0, 0), tail=(0, 25, 0))
TOSS_WIND = stand(drop=0.08, chest=-10, neck=-15, head=-20, ears=(-10, 0, 0))
TOSS_UP = P(loc=(-0.05, 0.12), body=60, chest=10, neck=10, head=25, jaw=-25, upper_arm_R=40, forearm_R=-60, upper_arm_L=30, forearm_L=-70,
            ears=(50, 0, 0), feet={"HR": (0.1, 0, 0, -10), "HL": (0.06, 0, 0, -10)})
# Sitting: rump on the floor, hind legs out in front, front legs propping it up.
SIT = P(loc=(0, -0.14), body=28, pelvis=18, neck=-14, head=-12, jaw=-6, tail=(-30, 0, 0),
        thigh_R=75, shin_R=-20, hock_R=-40, foot_R=10, thigh_L=70, shin_L=-15, hock_L=-40, foot_L=10,
        feet={"FR": (0.04, 0), "FL": (0.04, 0)})
SCOOT_A = P(SIT, body=(26, 0, 6), head=(-12, 10, 0), jaw=-18, ears=(25, 0, 0), thigh_R=80, thigh_L=60, feet={"FR": (0.1, 0), "FL": (0.06, 0)})
SCOOT_B = P(SIT, body=(30, 0, -6), head=(-12, -10, 0), jaw=-4, ears=(10, 0, 0), thigh_R=62, thigh_L=80, feet={"FR": (0.06, 0), "FL": (0.1, 0)})
SLIDE = P(splayed(loc=(0.02, -0.15), neck=8, head=6, jaw=-22, ears=(70, 0, 0)), tail=(0, 30, 0))

# Smash attacks: the pose on the charge frame is held while charging.
RAM_WIND = stand(fwd=-0.08, drop=0.08, front=0.06, hind=-0.04, chest=8, pelvis=8, neck=15, head=10, jaw=-12, ears=(-25, 0, 0), tail=(0, 40, 0))
RAM = stand(fwd=0.16, drop=0.03, front=0.14, hind=-0.14, chest=-6, neck=-18, head=-22, jaw=-3, ears=(60, 0, 0), tail=(0, -20, 0))
HOWL_WIND = stand(drop=0.08, chest=-6, pelvis=10, neck=-10, head=-10, jaw=0, ears=(-20, 0, 0))
HOWL = P(loc=(-0.07, 0.14), body=58, chest=8, neck=18, head=45, jaw=-30, upper_arm_R=50, forearm_R=-70, upper_arm_L=40, forearm_L=-75,
         ears=(45, 0, 0), tail=(0, 0, 0), feet={"HR": (0.1, 0, 0, -10), "HL": (0.07, 0, 0, -10)})
HOWL_B = P(HOWL, head=50, jaw=-34, ears=(55, 0, 0))
SHAKE_WIND = stand(drop=0.06, chest=-4, neck=-6, head=-6, ears=(-20, 0, 0))
WET_A = stand(body=(0, 0, 14), chest=(0, 48, 0), pelvis=(0, -42, 0), head=(0, 40, 0), jaw=-10, ears=(80, 0, 40), tail=(0, 60, 0))
WET_B = stand(body=(0, 0, -14), chest=(0, -48, 0), pelvis=(0, 42, 0), head=(0, -40, 0), jaw=-10, ears=(80, 0, -40), tail=(0, -60, 0))

# Aerials
BALL = flying(1.0, loc=(0, -0.12), body=0, neck=-25, head=-30, ears=(-30, 0, 0), tail=(-20, 0, 0))
SPIN_BALL = P(BALL, loc=(0, 0), chest=-15, pelvis=20, jaw=-12)
FAIR_WIND = flying(0.6, body=25, neck=15, head=15, jaw=-20, ears=(-10, 0, 0))
FAIR_HIT = flying(0.3, body=-35, neck=-15, head=-10, jaw=-4, ears=(60, 0, 0), upper_arm_R=120, forearm_R=-10, upper_arm_L=110)
BUCK = flying(0.4, body=-8, chest=-6, neck=12, head=6, thigh_R=-120, shin_R=50, hock_R=40, foot_R=40, thigh_L=-115, shin_L=45, hock_L=40, foot_L=40,
              tail=(-30, 0, 0), ears=(30, 0, 0))
SNAP = flying(0.5, body=65, neck=20, head=30, jaw=-32, ears=(40, 0, 0))
SNAP_HIT = P(SNAP, jaw=0, head=40)
PANCAKE_WIND = flying(1.0, body=-5, neck=10, head=-5, ears=(50, 0, 0))
PANCAKE = splayed(body=-4, neck=8, head=8, jaw=-20, ears=(80, 0, 0))

# Specials. The neutral special is a sneeze: the cloud leaves the nose on frame 16.
SNIFF = stand(fwd=-0.01, chest=4, neck=10, head=14, jaw=-4, ears=(10, 0, 0))
AH = stand(fwd=-0.03, drop=0.01, chest=10, pelvis=-4, neck=16, head=30, jaw=-14, ears=(25, 0, 0), tail=(0, 0, 0))
AHH = stand(fwd=-0.045, drop=0.02, chest=14, pelvis=-6, neck=20, head=40, jaw=-20, ears=(35, 0, 0))
CHOO = stand(fwd=0.06, drop=0.05, front=0.05, chest=-8, pelvis=6, neck=-14, head=-18, jaw=-26, ears=(-60, 0, 0), tail=(-25, 0, 0))
RECOIL = stand(fwd=0.03, drop=0.03, front=0.05, chest=-5, neck=-8, head=-8, jaw=-6, ears=(-30, 0, 0))
HEAD_SHAKE = stand(neck=4, head=(0, 22, 0), jaw=-2, ears=(30, 0, 25))
HEAD_SHAKE_B = stand(neck=4, head=(0, -22, 0), jaw=-2, ears=(30, 0, -25))
TACKLE_WIND = stand(fwd=-0.06, drop=0.1, front=0.04, hind=-0.04, chest=-6, pelvis=10, neck=-6, head=-4, ears=(-30, 0, 0), tail=(0, 40, 0))
# Riding: clinging to the opponent's front (they're held 0.9 m ahead), paws wrapped round.
RIDE = flying(0.0, loc=(0.6, 0.5), body=38, neck=-12, head=-18, jaw=-6, upper_arm_R=135, forearm_R=-70, hand_R=-30, upper_arm_L=125, forearm_L=-75,
              hand_L=-30, thigh_R=55, shin_R=-85, hock_R=20, thigh_L=45, shin_L=-80, hock_L=20, ears=(20, 0, 0), tail=(0, 30, 0))
RIDE_OPEN = P(RIDE, head=0, neck=-4, jaw=-32, ears=(40, 0, 0), tail=(0, -30, 0))
RIDE_BITE = P(RIDE, head=(-26, 12, 0), neck=-16, jaw=0, ears=(-10, 0, 0))
KICK_OFF = flying(0.0, loc=(0.32, 0.42), body=-15, neck=10, head=10, jaw=-14, upper_arm_R=60, forearm_R=-20, upper_arm_L=50, forearm_L=-20,
                  thigh_R=-20, shin_R=10, thigh_L=-10, shin_L=5, hock_R=-20, hock_L=-20, ears=(70, 0, 0))
# Ear copter: the ears beat up and down while the legs dangle.
COPTER_UP = flying(0.1, body=8, neck=12, head=15, jaw=-14, ears=(85, 0, 0), tail=(0, 30, 0))
COPTER_DOWN = P(COPTER_UP, ears=(-10, 0, 0), tail=(0, -30, 0), upper_arm_R=10, upper_arm_L=25)
HELPLESS = flying(0.1, body=-15, neck=15, head=20, jaw=-25, upper_arm_R=60, forearm_R=-30, upper_arm_L=-10, forearm_L=-20,
                  thigh_R=10, shin_R=-20, thigh_L=-50, shin_L=20, ears=(70, 0, 0))
HELPLESS_B = P(HELPLESS, upper_arm_R=-5, upper_arm_L=60, thigh_R=-45, thigh_L=5, ears=(60, 0, 0))
# Play dead: rolled onto its back (a half turn about the spine), legs in the air.
FLOP = P(flying(0.6), loc=(0, -0.12), body=(0, 0, 90), neck=-10, head=-6, jaw=-10, ears=(30, 0, 0))
DEAD = P(flying(0.5), loc=(0, -0.24), body=(0, 0, 180), neck=-14, head=(-10, 20, 0), jaw=-22, ears=(60, 0, 0), tail=(-20, 0, 0),
         upper_arm_R=40, forearm_R=-60, upper_arm_L=30, forearm_L=-70, thigh_R=20, shin_R=-40, thigh_L=10, shin_L=-30)
DEAD_TWITCH = P(DEAD, upper_arm_R=55, forearm_R=-40, thigh_L=25, head=(-10, 26, 0))
POUNCE = flying(0.0, loc=(0.04, 0.08), body=-10, neck=-6, head=-4, jaw=-34, upper_arm_R=115, forearm_R=-10, upper_arm_L=105, forearm_L=-10,
                hand_R=-40, hand_L=-40, thigh_R=-95, shin_R=30, thigh_L=-85, shin_L=25, ears=(70, 0, 0), tail=(-25, 0, 0))

# Grabs and throws: the pug grabs with its mouth.
REACH = stand(fwd=0.08, drop=0.05, front=0.07, chest=-10, neck=-8, head=-2, jaw=-30, ears=(-15, 0, 0))
CHOMP = P(REACH, jaw=0, head=-4)
DASH_REACH = stand(fwd=0.14, drop=0.06, front=0.13, hind=-0.08, chest=-12, neck=-10, head=-2, jaw=-30, ears=(40, 0, 0))
HOLD = stand(fwd=0.04, drop=0.03, front=0.06, chest=-6, neck=-6, head=-6, jaw=-6, tail=(0, 30, 0))
HOLD_B = P(HOLD, tail=(0, -30, 0), head=(-6, 8, 0))
NOM = P(HOLD, jaw=-20, head=6)
SHAKE_TOY = P(HOLD, neck=(-6, 0, 0), head=(-6, 30, 0), jaw=-4, ears=(40, 0, 30))
SHAKE_TOY_B = P(HOLD, head=(-6, -30, 0), jaw=-4, ears=(40, 0, -30))
FLING_F = stand(fwd=0.1, drop=0.02, front=0.1, chest=4, neck=12, head=30, jaw=-30, ears=(50, 0, 0))
TUG = stand(fwd=-0.06, drop=0.06, front=0.1, hind=-0.04, chest=6, pelvis=10, neck=4, head=-4, jaw=-4, ears=(20, 0, 0), tail=(0, 40, 0))
TUG_FLING = stand(fwd=0.02, chest=6, neck=16, head=30, jaw=-30, ears=(60, 0, 0))
LIFT_WIND = stand(drop=0.1, chest=-10, neck=-14, head=-14, jaw=-6)
LIFT = P(TOSS_UP, jaw=-30, head=40)
HOP_UP = flying(0.6, loc=(0.2, 0.18), body=10, neck=10, head=10, jaw=-10, ears=(50, 0, 0))
SIT_ON = P(SIT, loc=(0.42, -0.02), jaw=-20, ears=(40, 0, 0), feet={"FR": (0.46, 0.0), "FL": (0.46, 0.0)})
STRUGGLE = flying(0.3, body=10, neck=15, head=20, jaw=-25, ears=(40, 0, 0), upper_arm_R=60, upper_arm_L=0, thigh_R=-50, thigh_L=10)
STRUGGLE_B = P(STRUGGLE, upper_arm_R=0, upper_arm_L=60, thigh_R=10, thigh_L=-50, head=12)

# Shield and dodges
SHIELD = stand(drop=0.11, front=0.06, hind=-0.04, chest=-8, pelvis=10, neck=-10, head=-4, ears=(-35, 0, 0), jaw=0, tail=(0, 0, 0))
SHIELD_B = P(SHIELD, loc=(0, -0.115))
DIZZY = stand(body=(0, 8, 0), neck=(-12, 0, 15), head=(-10, 20, 0), jaw=-24, ears=(40, 0, 20))
DIZZY_B = stand(body=(0, -8, 0), neck=(-12, 0, -15), head=(-10, -20, 0), jaw=-24, ears=(40, 0, -20))
FLAT = splayed(loc=(0, -0.17), neck=-12, head=10, ears=(-30, 0, 0), jaw=0)
AIRDODGE = P(BALL, loc=(0, 0))

RUN_POSES = [pose for _, pose in gait(8, 0.26, 0.09, 0.4, {"FL": 0.0, "FR": 0.12, "HL": 0.5, "HR": 0.62}, 0.03, sway=7, flex=8, head=-4, drop=0.02)]


def roll(direction):
    """Somersault: curled up, the body turns a full circle on frames 4-20."""
    keys = [(1, G), (4, P(BALL, body=0))]
    for i in range(1, 5):
        keys.append((4 + 4 * i, P(BALL, body=-direction * 90 * i)))
    return keys + [(26, CROUCH), (32, G)]


def spin(pose, first, last, turns=1.0, step=4):
    """Keys `pose` turning about the vertical (a yaw spin) from `first` to `last`."""
    n = max(1, (last - first) // step)
    return [(first + (last - first) * i // n, P(pose, body=(pitch(pose.get("body", 0)), -360 * turns * i / n, 0))) for i in range(n + 1)]


def tackle_ride():
    """Bites on 10, 20 and 30, kicks off on 40 and hops back to its own spot."""
    keys = [(1, P(POUNCE, loc=(0.35, 0.3))), (4, RIDE)]
    for bite in (10, 20, 30):
        keys += [(bite - 3, RIDE_OPEN), (bite, RIDE_BITE), (bite + 3, RIDE)]
    return keys + [(37, RIDE), (40, KICK_OFF), (44, P(AIR, loc=(0.2, 0.2))), (48, P(AIR, loc=(0, 0))), (54, AIR)]


def ear_copter():
    """Ears beat every two frames during the climb (frames 6-50)."""
    keys = [(1, G), (4, CROUCH)]
    for f in range(6, 51, 2):
        keys.append((f, COPTER_UP if (f // 2) % 2 else COPTER_DOWN))
    return keys + [(56, HELPLESS)]


ANIMATIONS = {
    "idle": cycle(60, [IDLE, IDLE_B, IDLE_C, IDLE_B]),
    # Quick little legs: the pug scurries. Lateral walk; rotary gallop for the run.
    "walk": gait(20, 0.16, 0.06, 0.6, {"HL": 0.0, "FL": 0.25, "HR": 0.5, "FR": 0.75}, 0.008, sway=2, flex=2, head=2),
    "run": gait(12, 0.26, 0.09, 0.4, {"FL": 0.0, "FR": 0.12, "HL": 0.5, "HR": 0.62}, 0.03, sway=7, flex=8, head=-4, drop=0.02),
    # JumpSquat lasts FighterParams::PUG.jump_squat (3) frames.
    "jumpsquat": [(1, LOW), (3, CROUCH)],
    "air": cycle(40, [AIR, AIR_B]),
    # Played backwards from the end as Landing counts down, so it always finishes on idle.
    "land": [(1, CROUCH), (5, G)],
    "crouch": cycle(60, [CROUCH, CROUCH_B]),
    "hitstun": cycle(20, [FLINCH, FLINCH_B]),
    # Bite: 14 frames, (6, 6) on 3-4. Bite2: 16 frames, (6.5, 6) on 3-4.
    "bite": [(1, BITE_WIND), (3, BITE), (6, BITE), (10, P(BITE, jaw=-8)), (14, G)],
    "bite2": [(1, BITE), (2, BITE2_WIND), (3, BITE2), (7, BITE2), (16, G)],
    # Nibbles: 12 frames, (6, 5) on 2-3, chaining into itself from frame 5.
    "nibbles": [(1, NIB_OPEN), (2, NIB_SHUT), (4, P(NIB_SHUT, jaw=-6)), (6, NIB_OPEN), (8, NIB_SHUT), (12, P(BITE, jaw=-8))],
    # Paw swipe: 24 frames, low (7, 4) on 5-7.
    "paw_swipe": [(1, G), (3, SWIPE_WIND), (5, LOW_SWIPE), (8, LOW_SWIPE), (14, P(LOW_SWIPE, upper_arm_R=40, forearm_R=-30)), (24, G)],
    # Head toss: 26 frames, (3, 10) on 6-10.
    "head_toss": [(1, G), (4, TOSS_WIND), (6, TOSS_UP), (10, TOSS_UP), (18, P(TOSS_UP, body=30, loc=(0, 0.04))), (26, G)],
    # Scoot: 30 frames, sliding forward on its rump on 4-16, (4, 1.5) on 4-16.
    "scoot": [(1, G), (3, SIT), (5, SCOOT_A), (8, SCOOT_B), (11, SCOOT_A), (14, SCOOT_B), (17, SIT), (24, SIT), (30, G)],
    # Belly slide: 36 frames, sliding on 4-18; (5, 3) on 5-10, weaker to 18.
    "belly_slide": [(1, RUN_POSES[0]), (4, SLIDE), (18, P(SLIDE, loc=(0.02, -0.16), ears=(40, 0, 0))), (26, CROUCH), (36, G)],
    # Ram: charge frame 9, lunging 12-15, (8, 5) on 13-15.
    "ram": [(1, G), (6, RAM_WIND), (9, RAM_WIND), (12, P(RAM, loc=(0.08, -0.04))), (13, RAM), (20, RAM), (32, P(G, chest=-6)), (46, G)],
    # Howl: charge frame 6, (2, 12) on 10-16.
    "howl": [(1, G), (4, HOWL_WIND), (6, HOWL_WIND), (10, HOWL), (12, HOWL_B), (14, HOWL), (16, HOWL_B), (28, P(HOWL, body=25, jaw=-5)), (44, G)],
    # Shake: charge frame 4, both sides (+-6, 3) on 8-10.
    "shake": [(1, G), (3, SHAKE_WIND), (4, SHAKE_WIND), (6, WET_A), (8, WET_B), (10, WET_A), (12, WET_B), (15, P(WET_A, chest=(0, 15, 0), pelvis=(0, -12, 0))),
              (19, P(WET_B, chest=(0, -6, 0), pelvis=(0, 5, 0))), (30, G), (42, G)],
    # Tail spin: (0, 5) on 4-8 strong, to 20 weak; one full turn over 4-20.
    "tail_spin": [(1, AIR)] + spin(SPIN_BALL, 4, 20) + [(26, P(AIR, body=(0, -360, 0))), (32, P(AIR, body=(0, -360, 0)))],
    # Air headbutt: (6, 4) on 7-9.
    "air_headbutt": [(1, AIR), (5, FAIR_WIND), (7, FAIR_HIT), (10, FAIR_HIT), (22, P(AIR, body=-5)), (36, AIR)],
    # Buck: (-6, 4) on 6-8.
    "buck": [(1, AIR), (4, flying(0.9, body=10)), (6, BUCK), (9, BUCK), (18, P(BUCK, thigh_R=-60, thigh_L=-55)), (32, AIR)],
    # Snap: (1, 11) on 5-8.
    "snap": [(1, AIR), (3, P(SNAP, body=30)), (5, SNAP), (6, SNAP_HIT), (9, SNAP_HIT), (16, P(AIR, body=15)), (30, AIR)],
    # Pancake: belly flop, (0, 0) on 10-14.
    "pancake": [(1, AIR), (6, PANCAKE_WIND), (10, PANCAKE), (15, PANCAKE), (28, P(AIR, body=0)), (40, AIR)],
    # Sneeze: Ah... ah... CHOO on 16 (the cloud leaves the nose), then a head shake.
    # Sneeze: holding special freezes the "ah..." on frame 13 to charge it.
    "sneeze": [(1, G), (5, SNIFF), (10, AH), (13, AHH), (15, P(AHH, head=44, jaw=-22)), (16, CHOO), (19, CHOO), (22, RECOIL),
               (25, HEAD_SHAKE), (28, HEAD_SHAKE_B), (31, P(HEAD_SHAKE, head=(0, 10, 0), ears=(20, 0, 10))), (34, P(HEAD_SHAKE_B, head=(0, -5, 0))), (42, G)],
    # Tackle: leaps on 7-18, catching on 8-18. Caught opponents get the ride.
    "tackle": [(1, G), (3, TACKLE_WIND), (6, TACKLE_WIND), (8, P(POUNCE, jaw=-36)), (18, POUNCE), (26, P(AIR, body=-6)), (40, AIR)],
    "tackle_ride": tackle_ride(),
    "ear_copter": ear_copter(),
    "specialfall": cycle(30, [HELPLESS, HELPLESS_B]),
    # Play dead: 44 frames, counters on 6-26. Pounce: lunging 2-8, (6, 4) on 4-8.
    "play_dead": [(1, G), (3, FLOP), (6, DEAD), (14, DEAD_TWITCH), (18, DEAD), (26, DEAD), (34, FLOP), (44, G)],
    "pounce": [(1, DEAD), (3, P(POUNCE, loc=(0, 0.02))), (4, POUNCE), (8, POUNCE), (16, CROUCH), (30, G)],
    # Bite grab: (6, 5) on 6-7. Dash bite grab: (8, 5) on 8-9.
    "bite_grab": [(1, G), (4, REACH), (6, REACH), (8, CHOMP), (16, P(HOLD, jaw=0)), (28, G)],
    "dash_bite_grab": [(1, RUN_POSES[0]), (6, DASH_REACH), (8, DASH_REACH), (10, P(DASH_REACH, jaw=0)), (24, P(CROUCH, chest=-10)), (38, G)],
    "grab_hold": cycle(40, [HOLD, HOLD_B]),
    "grabbed": cycle(16, [STRUGGLE, STRUGGLE_B]),
    # Nom: the pummel, hits on 3. Throws release on 14 (toss), 20 (tug spin), 12 (fling up), 16 (sit).
    "nom": [(1, HOLD), (2, NOM), (3, P(HOLD, jaw=0, head=-10)), (7, HOLD), (14, HOLD)],
    "toss": [(1, HOLD), (4, SHAKE_TOY), (7, SHAKE_TOY_B), (10, SHAKE_TOY), (12, SHAKE_TOY_B), (14, FLING_F), (20, FLING_F), (30, G)],
    # Tug spin: a half turn to fling them out behind on 20, then turns back.
    "tug_spin": [(1, HOLD), (5, TUG)] + spin(TUG, 6, 18, 0.45)[1:] + [(20, P(TUG_FLING, body=(0, -180, 0))), (24, P(TUG_FLING, body=(0, -180, 0))),
                                                                   (34, P(G, body=(0, -360, 0))), (40, P(G, body=(0, -360, 0)))],
    "fling_up": [(1, HOLD), (6, LIFT_WIND), (12, LIFT), (18, LIFT), (32, G)],
    # Sit: hops onto them and sits down on 16, then hops back.
    "sit": [(1, HOLD), (6, LIFT_WIND), (10, HOP_UP), (14, P(SIT_ON, loc=(0.42, 0.04))), (16, SIT_ON), (22, SIT_ON), (28, P(HOP_UP, loc=(0.15, 0.1))), (34, G)],
    "shield": cycle(40, [SHIELD, SHIELD_B]),
    "dizzy": cycle(60, [DIZZY, DIZZY_B]),
    # Dodges: spot 26 frames (invincible 3-17), rolls 32 (4-15), air dodge 34-40 (3-18 / 3-25).
    "spotdodge": [(1, G), (3, FLAT), (17, FLAT), (26, G)],
    "roll_f": roll(1),
    "roll_b": roll(-1),
    "airdodge": [(1, AIR), (4, AIRDODGE), (25, AIRDODGE), (34, AIR), (40, AIR)],
}


def apply_pose(rig, pose):
    pose = solve(pose)
    for pb in rig.pose.bones:
        value = pose.get(pb.name, 0)
        a, b, c = value if isinstance(value, tuple) else (value, 0, 0)
        if pb.name in PLANAR:
            # Local X = world +Y, so counter-clockwise from the camera (-Y) is -X.
            pb.rotation_euler = (math.radians(-a), math.radians(b), math.radians(c))
        else:
            pb.rotation_euler = (math.radians(a), math.radians(b), math.radians(c))
        pb.location = (0, 0, 0)
    fwd, up = pose.get("loc", (0, 0))
    rig.pose.bones["body"].location = (0, up, fwd)  # body bone local axes: Y = up, Z = forward


def build_actions(rig):
    rig.animation_data_create()
    for name, keys in ANIMATIONS.items():
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        rig.animation_data.action = action
        for frame, pose in keys:
            apply_pose(rig, pose)
            for pb in rig.pose.bones:
                pb.keyframe_insert("rotation_euler", frame=frame, group=pb.name)
            rig.pose.bones["body"].keyframe_insert("location", frame=frame, group="body")
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, keys[0][0], action)
        track.mute = True
    rig.animation_data.action = None
    apply_pose(rig, G)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    rig = build_rig()
    build_meshes(rig)
    build_actions(rig)
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)


if __name__ == "__main__":
    main()
