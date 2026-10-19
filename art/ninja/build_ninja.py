"""Builds the ninja: the lightest, fastest fighter, a lean figure in a dark gi with a
face wrap, headband, shuriken pouch and open knife-hands (separate fingers). Then his
armature and one action per pose name the sim reports (`Fighter::anim()`). Saves
`ninja.blend` next to this script and exports `godot/models/ninja.glb`.

    blender --background --factory-startup --python art/ninja/build_ninja.py

He stands on the chef's skeleton (same joints, 1.2 m), so the shapes, pose helpers
and conventions come from `art/fighter/build_fighter.py` (see its README). Unlike the
samurai there is no extra bone: his shuriken is drawn as a projectile orb, and his
specials are a shadow dash, a smoke bomb and a substitution counter, so the hands
stay free. The headband is the `Body` material that the game recolors per player.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "ninja.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "ninja.glb")

sys.path.insert(0, os.path.join(ROOT, "art", "fighter"))
import build_fighter as chef  # noqa: E402
from build_fighter import (  # noqa: E402
    AIR,
    ANKLE,
    ELBOW,
    FLINCH,
    FWD,
    HIP,
    KNEE,
    SHOULDER,
    WRIST,
    Blob,
    by_distance,
    crouch,
    cycle,
    export,
    guard,
    leg_ik,
    planted,
    ring_band,
    tube,
    uv_ellipsoid,
    walk_key,
    with_,
)

FPS = 60

# The chef's bones, minus the pie (the ninja throws shuriken drawn as a projectile,
# so he carries nothing in his hands).
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONE_NAMES = [b[0] for b in BONES]

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the
# headband and belt) with the player's color; the rest keep their own.
MATERIALS = {
    "Body": ((0.72, 0.14, 0.14, 1), 0.7, 0.0),
    "Gi": ((0.07, 0.08, 0.14, 1), 0.85, 0.0),
    "Wrap": ((0.15, 0.16, 0.20, 1), 0.8, 0.0),
    "Skin": ((0.83, 0.64, 0.49, 1), 0.55, 0.0),
    "Lip": ((0.62, 0.38, 0.33, 1), 0.45, 0.0),
    "Hair": ((0.02, 0.02, 0.03, 1), 0.45, 0.0),
    "Eye": ((0.93, 0.91, 0.87, 1), 0.12, 0.0),
    "Iris": ((0.11, 0.07, 0.05, 1), 0.15, 0.0),
    "Pupil": ((0.01, 0.01, 0.01, 1), 0.1, 0.0),
    "Steel": ((0.66, 0.70, 0.75, 1), 0.25, 0.85),
    "Sole": ((0.05, 0.05, 0.06, 1), 0.6, 0.0),
}
MAT = {name: i for i, name in enumerate(MATERIALS)}


class Model(chef.Model):
    """The chef's `Model`, on this skeleton and these materials."""

    def weigh(self, verts, weights):
        for v in verts:
            ws = {weights: 1.0} if isinstance(weights, str) else weights(v.co)
            for bone, w in ws.items():
                v[self.deform][BONE_NAMES.index(bone)] = w

    def paint(self, verts, mat, smooth=True):
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = MAT[mat]
            f.smooth = smooth


# --- Shapes -----------------------------------------------------------------


def head_blob():
    """A lean face: high cheekbones, a square jaw, a straight nose and a full mouth."""
    b = Blob(resolution=0.0035)
    b.ell((-0.005, 0, 1.07), (0.086, 0.073, 0.088))  # cranium
    b.ell((0.022, 0, 1.015), (0.07, 0.062, 0.072))  # face and jaw
    b.ell((0.052, 0, 0.965), (0.04, 0.042, 0.024), stiffness=3)  # square chin
    b.cap((-0.012, 0, 0.825), (0.0, 0, 0.975), 0.047)  # neck
    for s in (1, -1):
        b.ell((0.06, s * 0.041, 1.03), (0.021, 0.023, 0.017), stiffness=3)  # cheekbones
        b.cap((-0.02, s * 0.054, 1.0), (0.058, s * 0.031, 0.952), 0.015, stiffness=3)  # jawline
        b.cap((0.08, s * 0.012, 1.08), (0.074, s * 0.048, 1.085), 0.011, stiffness=3)  # brow ridge
        b.ball((0.073, s * 0.03, 1.055), 0.0125, stiffness=4, negative=True)  # eye socket
        b.ell((-0.012, s * 0.076, 1.045), (0.016, 0.0095, 0.027), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-10 * s)))  # ears
        b.ell((-0.006, s * 0.084, 1.048), (0.008, 0.0065, 0.014), stiffness=5, negative=True)
    b.cap((0.084, 0, 1.075), (0.1, 0, 1.035), 0.008, stiffness=3)  # nose bridge
    b.ell((0.098, 0, 1.03), (0.011, 0.013, 0.0095), stiffness=3)  # nose tip
    b.cap((0.087, -0.018, 0.99), (0.087, 0.018, 0.99), 0.0032, stiffness=6, negative=True)  # mouth
    b.ell((0.085, 0, 0.983), (0.008, 0.017, 0.0055), stiffness=4)  # lower lip
    return b


def hair_blob():
    """Dark hair pulled back tight under the headband."""
    b = Blob(resolution=0.004)
    b.ell((-0.02, 0, 1.085), (0.09, 0.078, 0.082))
    for s in (1, -1):
        b.ell((-0.01, s * 0.085, 1.045), (0.025, 0.019, 0.032), stiffness=4, negative=True)  # ears
    b.ell((0.064, 0, 1.035), (0.05, 0.08, 0.06), stiffness=4, negative=True)  # clear of the face
    b.ell((-0.03, 0, 0.96), (0.078, 0.085, 0.048), stiffness=4, negative=True)  # nape
    return b


def gi_blob():
    """The gi's body: a lean chest, a narrow waist, cloth folds hinted in the shoulders."""
    b = Blob(resolution=0.006)
    b.ell((0.0, 0, 0.755), (0.09, 0.135, 0.105))  # chest
    b.ell((0.005, 0, 0.625), (0.085, 0.118, 0.105))  # waist
    for s in (1, -1):
        b.ell((-0.005, s * 0.087, 0.825), (0.052, 0.065, 0.034))  # trapezius
        b.ell((0.0, s * 0.145, 0.81), (0.05, 0.042, 0.042))  # shoulder seam
        b.ell((-0.055, s * 0.055, 0.755), (0.038, 0.056, 0.065))  # shoulder blades
    b.ell((0.0, 0, 0.44), (0.1, 0.13, 0.02), stiffness=4)  # hem
    return b


def sleeve_blob(s):
    """A close-fitting sleeve, full at the shoulder, snug to the wrist."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.005)
    b.ell((0.0, y - s * 0.005, 0.805), (0.05, 0.05, 0.055))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.042)
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.03), 0.036)
    return b


def pant_blob(s):
    """One leg of the gi pants: fitted through the thigh, snug on the shin."""
    y = s * HIP[0]
    b = Blob(resolution=0.006)
    b.ell((-0.02, s * 0.045, 0.48), (0.085, 0.065, 0.065))  # seat and hip
    b.cap((0, y, HIP[1] - 0.04), (0, y, KNEE[1]), 0.052)  # thigh
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.01), 0.04)  # shin
    return b


def tabi_blob(s):
    """A split-toe tabi sock: the big toe apart from the rest."""
    y = s * HIP[0]
    b = Blob(resolution=0.004)
    b.ell((0.035, y, 0.04), (0.085, 0.038, 0.035), stiffness=3)
    b.ell((0.11, y + s * 0.012, 0.03), (0.04, 0.026, 0.024), stiffness=3)  # toes
    b.ell((0.115, y - s * 0.022, 0.03), (0.038, 0.016, 0.024), stiffness=3)  # big toe
    b.ell((-0.025, y, 0.045), (0.04, 0.036, 0.042), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.13), 0.036)  # ankle
    b.ell((0.05, y, -0.088), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat sole
    return b


def ninja_mesh():
    m = Model()
    m.blob("head", head_blob(), 0.5, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    gi = m.blob("gi", gi_blob(), 0.25, "Gi", by_distance("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        m.blob(f"sleeve.{side}", sleeve_blob(s), 0.25, "Gi", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        ninja_hand(m, s, f"forearm.{side}")
        m.blob(f"leg.{side}", pant_blob(s), 0.25, "Gi", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"tabi.{side}", tabi_blob(s), 0.3, "Wrap", f"foot.{side}")
        sole(m, s, f"foot.{side}")
    face(m)
    face_wrap(m)
    headband(m)
    collar_and_seams(m, m.weights_near(gi))
    belt(m)
    shuriken_pouch(m)

    mesh = bpy.data.meshes.new("NinjaMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    return mesh


def ninja_hand(m, s, bone):
    """An open knife-hand: a palm and four separate fingers plus a thumb, all skinned
    to the forearm so the fingers read individually on every chop."""
    y = s * SHOULDER[0]
    bm = m.bm
    palm = uv_ellipsoid(bm, (0.02, y, WRIST[1] - 0.01), (0.028, 0.026, 0.02), segments=(16, 10))
    m.part(palm, bone, "Skin")
    # Four fingers, spread a little, extending forward and curling slightly down.
    for i, dy in enumerate((-0.022, -0.007, 0.008, 0.022)):
        length = 0.052 - 0.006 * abs(i - 1.5)
        root = Vector((0.048, y + dy, WRIST[1] - 0.005))
        tip = Vector((0.048 + length, y + dy, WRIST[1] - 0.022 - 0.004 * i))
        mid = Vector((0.048 + length * 0.5, y + dy, WRIST[1] - 0.008))
        verts = tube(bm, [root, mid, tip], [0.006, 0.0055, 0.0045], sides=8)
        m.part(verts, bone, "Skin")
    # Thumb, angled across the palm toward the body's midline.
    thumb = tube(
        bm,
        [Vector((0.01, y - s * 0.02, WRIST[1])), Vector((0.04, y - s * 0.036, WRIST[1] - 0.008)), Vector((0.06, y - s * 0.046, WRIST[1] - 0.016))],
        [0.0065, 0.006, 0.005],
        sides=8,
    )
    m.part(thumb, bone, "Skin")


def sole(m, s, bone):
    """A thin dark sole under the tabi."""
    y = s * HIP[0]
    sole = bmesh.ops.create_cube(m.bm, size=1.0, matrix=Matrix.Translation((0.04, y, 0.006)) @ Matrix.Diagonal((0.22, 0.08, 0.012, 1)))["verts"]
    m.part(sole, bone, "Sole", smooth=False)


def face(m):
    def on_skin(y, z, lift):
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.03, 1.055, 0)
        eye = socket - Vector((0.012 - 0.004, 0, 0))
        m.part(uv_ellipsoid(m.bm, eye, (0.0115,) * 3, segments=(16, 10)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0105, 0, -0.001)), (0.0023, 0.0065, 0.0065), segments=(14, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0124, 0, -0.001)), (0.0011, 0.0032, 0.0032), segments=(10, 6)), "head", "Pupil")
        # Narrowed lids, like a scowl.
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0004, 0, 0.0032)), (0.0122, 0.013, 0.0092), segments=(16, 10)), "head", "Skin")
        m.part(uv_ellipsoid(m.bm, eye + Vector((-0.001, 0, -0.0098)), (0.0122, 0.0128, 0.0056), segments=(16, 8)), "head", "Skin")
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.01, 1.078), (0.03, 1.086), (0.052, 1.09))]
        m.part(tube(m.bm, brow, [0.005, 0.0055, 0.0032], sides=8), "head", "Hair")
    m.part(uv_ellipsoid(m.bm, on_skin(0, 0.9925, -0.003), (0.0075, 0.016, 0.004), segments=(14, 8)), "head", "Lip")


def face_wrap(m):
    """The lower-face wrap: a fitted band over nose, mouth and chin, with a seam down
    the back and a knot tying it at the side. Built from several parts."""
    center = lambda z: Vector((-0.01, 0, z))  # noqa: E731
    grid = []
    rows, sides = 4, 48
    for i in range(rows + 1):
        z = 0.9 + (1.04 - 0.9) * i / rows
        fit = [m.fit(("head", "hair"), center(z), 2 * math.pi * j / sides) + 0.004 for j in range(sides)]
        grid.append([m.bm.verts.new(center(z) + Vector((math.cos(a), math.sin(a), 0)) * fit[round(a / (2 * math.pi) * sides) % sides])
                     for a in (2 * math.pi * j / sides for j in range(sides))])
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(sides):
            m.bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    wrap = [v for r in grid for v in r]
    m.part(wrap, "head", "Wrap")
    # A raised seam down the back of the wrap.
    back = [center(z) + Vector((-m.fit(("head", "hair"), center(z), math.pi) - 0.006, 0, 0)) for z in (1.045, 1.0, 0.95, 0.9)]
    m.part(tube(m.bm, back, [0.006, 0.006, 0.005, 0.004], sides=6), "head", "Wrap")
    # A knot at the side of the neck, tying the wrap.
    knot = m.hit("head", (0.0, 0.42, 0.95), (0, -1, 0))[0]
    m.part(uv_ellipsoid(m.bm, knot, (0.012, 0.014, 0.011)), "head", "Wrap")


def headband(m):
    """A cloth headband (`Body`) across the brow, knotted at the back with two tails
    hanging behind."""
    center = lambda z: Vector((-0.012, 0, z))  # noqa: E731
    fit = [m.fit(("head", "hair"), center(1.10), 2 * math.pi * j / 48) + 0.004 for j in range(48)]
    band = ring_band(m.bm, center, lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48], 1.08, 1.12, rows=2, sides=48)
    m.part(band, "head", "Body")
    back = center(1.10) + Vector((-fit[24] - 0.006, 0, 0))
    m.part(uv_ellipsoid(m.bm, back, (0.012, 0.016, 0.014)), "head", "Body")
    for s in (1, -1):
        tail = [back + Vector(d) for d in ((-0.004, s * 0.006, -0.004), (-0.02, s * 0.014, -0.03), (-0.03, s * 0.018, -0.07), (-0.034, s * 0.016, -0.1))]
        verts = tube(m.bm, tail, [0.009, 0.011, 0.011, 0.009], sides=8)
        for v in verts:  # flatten into cloth, edge-on to the side
            v.co.y = tail[1].y + (v.co.y - tail[1].y) * 0.35
        m.part(verts, "head", "Body")


def collar_and_seams(m, on_gi):
    """The gi's crossed front with a visible seam, and two side seams down the torso."""
    for s, depth in ((1, 0.006), (-1, 0.003)):
        line = []
        for i in range(10):
            t = i / 9
            y = s * (0.06 - 0.09 * t)
            z = 0.84 - 0.21 * t
            loc, normal = m.hit("gi", (0.5, y, z), (-1, 0, 0))
            line.append(loc + normal * depth)
        verts = tube(m.bm, line, [0.011] * len(line), sides=8)
        m.weigh(verts, on_gi)
        m.paint(verts, "Wrap" if s == -1 else "Gi")
    # Side seams, one under each arm, tracing the torso's fold.
    for s in (1, -1):
        seam = []
        for i in range(8):
            z = 0.8 - 0.3 * i / 7
            loc, normal = m.hit("gi", (0.0, s * 0.5, z), (0, -s, 0))
            if loc is not None:
                seam.append(loc + normal * 0.002)
        if seam:
            m.part(tube(m.bm, seam, [0.0035] * len(seam), sides=6), on_gi, "Wrap")


def belt(m):
    """A cloth sash (`Body`) wrapped at the waist and knotted at the back."""
    center = lambda z: Vector((0.005, 0, z))  # noqa: E731
    fit = [m.fit(("gi", "leg.L", "leg.R"), center(0.55), 2 * math.pi * j / 48) + 0.006 for j in range(48)]
    band = ring_band(m.bm, center, lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48], 0.52, 0.58, rows=2, sides=48)
    m.part(band, "hips", "Body")
    knot = center(0.55) + Vector((-fit[24] - 0.004, 0, 0))
    m.part(uv_ellipsoid(m.bm, knot, (0.011, 0.014, 0.012)), "hips", "Body")


def shuriken_pouch(m):
    """A small pouch on the back-right hip, its flap tied shut, a shuriken peeking out."""
    bm = m.bm
    body = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((-0.02, -0.12, 0.5)) @ Matrix.Diagonal((0.06, 0.09, 0.07, 1)))["verts"]
    m.part(body, "hips", "Wrap")
    flap = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((-0.02, -0.12, 0.54)) @ Matrix.Diagonal((0.062, 0.092, 0.02, 1)))["verts"]
    m.part(flap, "hips", "Gi")
    star = uv_ellipsoid(bm, (-0.02, -0.135, 0.545), (0.013, 0.013, 0.004), segments=(16, 6))
    m.part(star, "hips", "Steel")


def materials():
    mats = []
    for name, (color, rough, metal) in MATERIALS.items():
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.diffuse_color = color
        if mat.node_tree is None:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        mats.append(mat)
    return mats


# --- Rig --------------------------------------------------------------------


def build_rig(mesh):
    rig = bpy.data.objects.new("Fighter", bpy.data.armatures.new("NinjaRig"))
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = rig.data.edit_bones
    for name, parent, head, tail, roll_to in BONES:
        bone = edit_bones.new(name)
        bone.head, bone.tail = head, tail
        bone.align_roll(Vector(roll_to))
        if parent:
            bone.parent = edit_bones[parent]
        assert (bone.x_axis - Vector((0, 1, 0))).length < 1e-4, name
    bpy.ops.object.mode_set(mode="OBJECT")

    body = bpy.data.objects.new("Ninja", mesh)
    bpy.context.scene.collection.objects.link(body)
    body.parent = rig
    for name in BONE_NAMES:
        body.vertex_groups.new(name=name)
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    return rig


# --- Poses ------------------------------------------------------------------
# The chef's pose format: {bone: degrees or (pitch, twist, spread)}, plus "hips_loc".


def lunge(pose, fwd, drop, front, back=-0.2):
    """`pose` with the hips moved forward and down, feet re-planted wide."""
    return planted(with_(pose, hips_loc=(fwd, -drop)), front, back)


S = with_(guard(drop=0.05, lean=-6, front=0.13, back=-0.13), upper_arm_R=28, forearm_R=102, upper_arm_L=16, forearm_L=108)
CROUCH = with_(crouch(0.15), upper_arm_R=0, forearm_R=70, upper_arm_L=-10, forearm_L=70)
AIR_S = with_(AIR, upper_arm_R=55, forearm_R=70, upper_arm_L=-15, forearm_L=80)
FLINCH_S = FLINCH

# Knife-hand chops (jab chain): the near hand does the cutting.
CHOP_HIGH = with_(S, upper_arm_R=140, forearm_R=20)
CHOP = lunge(with_(S, spine=-14, head=10, upper_arm_R=96, forearm_R=0), 0.05, 0.06, 0.26)
CHOP_LOW = with_(CHOP, upper_arm_R=70, forearm_R=0)
BACKHAND = lunge(with_(S, spine=-10, head=8, upper_arm_L=88, forearm_L=0, upper_arm_R=10), 0.04, 0.06, 0.24)
FINISH = lunge(with_(S, spine=-18, head=12, upper_arm_R=92, forearm_R=0, upper_arm_L=-40), 0.1, 0.08, 0.34)
PALM_WIND = with_(S, spine=4, head=-4, upper_arm_R=-10, forearm_R=80)
PALM = lunge(with_(S, spine=-12, head=8, upper_arm_R=70, forearm_R=6, upper_arm_L=-20, forearm_L=70), 0.08, 0.06, 0.3)
RISE_LOW = with_(CROUCH, upper_arm_R=30, forearm_R=20)
RISE_FRONT = with_(S, spine=-4, upper_arm_R=100, forearm_R=0)
RISE_TOP = with_(S, hips_loc=(0, -0.01), spine=8, head=-10, upper_arm_R=170, forearm_R=0)
SWEEP = planted(with_(crouch(0.22), spine=-16, head=12, upper_arm_R=-60, upper_arm_L=50, forearm_L=40), 0.5, -0.22)
DASH_TRAIL = planted(with_(guard(drop=0.07, lean=-30), hips_loc=(0.06, -0.07), upper_arm_R=60, forearm_R=0, upper_arm_L=-20), 0.2, -0.26)
DASH_CUT = planted(with_(guard(drop=0.08, lean=-24), hips_loc=(0.12, -0.08), upper_arm_R=95, forearm_R=0, upper_arm_L=-40, forearm_L=20), 0.36, -0.26)

# Smash attacks: the pose on the charge frame is held while charging.
CHOP_WIND = lunge(with_(S, spine=12, head=-12, upper_arm_R=165, forearm_R=25, upper_arm_L=160, forearm_L=30), -0.04, 0.05, 0.2)
CHOP_MID = with_(CHOP_WIND, upper_arm_R=145, upper_arm_L=140, spine=0)
CHOP_HIT = lunge(with_(S, spine=-26, head=20, upper_arm_R=112, forearm_R=0, upper_arm_L=108, forearm_L=6), 0.14, 0.12, 0.42, -0.24)
CHOP_DOWN = with_(CHOP_HIT, upper_arm_R=78, upper_arm_L=74)
FLIP_LOW = with_(CROUCH, upper_arm_R=-20, forearm_R=40, upper_arm_L=-20, forearm_L=40)
FLIP_KICK = planted(with_(S, hips_loc=(0, 0.02), spine=-8, head=-14, upper_arm_R=-60, upper_arm_L=-80, thigh_R=130, shin_R=-10, foot_R=-20), 0.08, -0.08)
SPIN_WIND = planted(with_(crouch(0.2), spine=-10, upper_arm_R=-30, upper_arm_L=40), 0.28, -0.28)
SPIN_FRONT = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=80, upper_arm_L=-60, thigh_R=90, shin_R=-10), 0.36, -0.3)
SPIN_BACK = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=-60, upper_arm_L=60, thigh_L=90, shin_L=-10), 0.3, -0.36)

# Aerials
AIR_TUCK = with_(AIR_S, thigh_R=80, shin_R=-120, thigh_L=60, shin_L=-110)
SPIN_FRONT_A = with_(AIR_TUCK, spine=-10, upper_arm_R=110, forearm_R=0)
SPIN_BACK_A = with_(AIR_TUCK, spine=10, upper_arm_R=210, forearm_R=0)
FLY_WIND = with_(AIR_S, spine=10, head=-5, upper_arm_R=170, forearm_R=20, thigh_R=70, shin_R=-110)
FLY = with_(AIR_S, spine=-20, head=16, upper_arm_R=50, forearm_R=0, upper_arm_L=-60, thigh_R=95, shin_R=-6, foot_R=-40)
HOOK = with_(AIR_S, spine=-24, head=26, thigh_L=-95, shin_L=-5, foot_L=40, thigh_R=60, shin_R=-100, upper_arm_R=60, upper_arm_L=40, forearm_L=60)
UP_FLIP = with_(AIR_S, spine=30, head=-18, thigh_R=150, shin_R=-5, foot_R=-20, thigh_L=20, shin_L=-90, upper_arm_R=-60, upper_arm_L=-80)
AXE_WIND = with_(AIR_S, thigh_R=95, shin_R=-135, thigh_L=85, shin_L=-125, upper_arm_R=120, upper_arm_L=110)
AXE = with_(AIR_S, spine=-5, thigh_R=5, shin_R=0, foot_R=-40, thigh_L=-5, shin_L=0, foot_L=-40, upper_arm_R=140, upper_arm_L=130, forearm_R=20, forearm_L=20)

# Specials
SHURIKEN_SHOW = with_(S, spine=-4, upper_arm_R=20, forearm_R=100, upper_arm_L=10, forearm_L=110)
SHURIKEN_WIND = planted(with_(S, hips_loc=(-0.04, -0.05), spine=14, head=-12, upper_arm_R=-55, forearm_R=95, upper_arm_L=60, forearm_L=25), 0.17, -0.2)
SHURIKEN_RELEASE = planted(with_(S, hips_loc=(0.08, -0.07), spine=-18, head=12, upper_arm_R=95, forearm_R=5, upper_arm_L=-25, forearm_L=50), 0.28, -0.2)
DASH_CROUCH = with_(crouch(0.2), spine=-20, head=16, upper_arm_R=-30, upper_arm_L=30, forearm_L=60)
DASH_LEAN = planted(with_(guard(drop=0.06, lean=-40), hips_loc=(0.1, -0.06), upper_arm_R=70, forearm_R=0, upper_arm_L=-50, forearm_L=30), 0.3, -0.3)
SMOKE_CROUCH = with_(crouch(0.28), spine=-30, head=20, upper_arm_R=40, forearm_R=120, upper_arm_L=40, forearm_L=120)
SMOKE_RISE = with_(AIR_S, spine=8, head=-12, upper_arm_R=175, forearm_R=0, upper_arm_L=170, forearm_L=0, thigh_R=30, shin_R=-30, thigh_L=10, shin_L=-10)
SUB_STANCE = planted(with_(S, hips_loc=(-0.02, -0.07), spine=4, head=-4, upper_arm_R=60, forearm_R=110, upper_arm_L=50, forearm_L=115), 0.16, -0.18)
SUB_STRIKE = lunge(with_(S, spine=-20, head=16, upper_arm_R=104, forearm_R=0, upper_arm_L=-36, forearm_L=20), 0.12, 0.1, 0.4)
HELPLESS = with_(AIR_S, spine=10, head=-10, upper_arm_R=150, forearm_R=30, upper_arm_L=140, forearm_L=40, thigh_R=20, shin_R=-40, thigh_L=5, shin_L=-30)

# Grabs and throws
REACH = lunge(with_(S, spine=-14, head=10, upper_arm_R=88, forearm_R=6, upper_arm_L=80, forearm_L=10), 0.06, 0.06, 0.26)
DASH_REACH = planted(with_(guard(drop=0.08, lean=-26), hips_loc=(0.1, -0.08), upper_arm_R=95, forearm_R=5, upper_arm_L=90, forearm_L=10), 0.32, -0.26)
HOLD = with_(S, spine=-5, upper_arm_R=70, forearm_R=50, upper_arm_L=65, forearm_L=55)
POMEL = with_(HOLD, spine=-14, head=10, upper_arm_R=88, forearm_R=20)
THROW_F = lunge(with_(HOLD, spine=-26, head=18, upper_arm_R=100, forearm_R=0, upper_arm_L=60, forearm_L=20), 0.1, 0.12, 0.36)
THROW_B_LOAD = lunge(with_(HOLD, spine=-16, upper_arm_L=168, forearm_L=30), 0.02, 0.18, 0.2)
THROW_B = lunge(with_(HOLD, spine=18, head=-10, upper_arm_L=232, forearm_L=0, upper_arm_R=-30), -0.04, 0.08, 0.16, -0.3)
THROW_U = planted(with_(HOLD, hips_loc=(0, 0.01), spine=8, head=-14, upper_arm_R=178, forearm_R=0, upper_arm_L=170, forearm_L=0), 0.08, -0.08)
THROW_D = planted(with_(crouch(0.26), spine=-30, head=20, upper_arm_R=60, forearm_R=10, upper_arm_L=60, forearm_L=10), 0.3, -0.22)
STRUGGLE = with_(S, spine=15, head=10, upper_arm_R=40, forearm_R=70, upper_arm_L=-30, forearm_L=100)

# Shield and dodges
SHIELD = with_(guard(drop=0.06, lean=-5), upper_arm_R=60, forearm_R=110, upper_arm_L=55, forearm_L=115)
DIZZY = with_(S, spine=(-15, 0, 10), head=(-20, 0, 15), upper_arm_R=-5, forearm_R=10, upper_arm_L=-5, forearm_L=10)
SIDESTEP = with_(crouch(0.08), spine=-10, head=10, upper_arm_R=10, forearm_R=40, upper_arm_L=10, forearm_L=40)
BALL = with_(crouch(0.3), spine=-60, head=40, upper_arm_R=60, forearm_R=130, upper_arm_L=60, forearm_L=130)
AIRDODGE = with_(AIR_S, spine=-10, upper_arm_R=60, forearm_R=120, upper_arm_L=55, forearm_L=125, thigh_R=70, shin_R=-120, thigh_L=60, shin_L=-110)


def walk(stride, lift, drop, swing, phase, run):
    """A walk/run key with the knife-hands held ready."""
    pose = walk_key(stride, lift, drop, swing, phase)
    if run:
        return with_(pose, upper_arm_R=-20, forearm_R=60, upper_arm_L=-30, forearm_L=60)
    return with_(pose, upper_arm_R=30, forearm_R=95, upper_arm_L=16, forearm_L=100)


ANIMATIONS = {
    "idle": cycle(60, [S, with_(guard(drop=0.056), upper_arm_R=30, upper_arm_L=18)]),
    "walk": cycle(40, [walk(0.12, 0.06, d, 22, i, False) for i, d in enumerate((0.04, 0.025, 0.04, 0.025))]),
    "run": cycle(24, [walk(0.2, 0.12, d, 45, i, True) for i, d in enumerate((0.06, 0.03, 0.06, 0.03))]),
    "jumpsquat": [(1, guard(drop=0.07, lean=-12)), (3, CROUCH)],
    "air": cycle(40, [AIR_S, with_(AIR_S, thigh_R=60, shin_R=-100, thigh_L=10, upper_arm_R=50)]),
    "land": [(1, CROUCH), (3, S)],
    "crouch": cycle(60, [CROUCH, with_(crouch(0.155), upper_arm_R=2)]),
    "hitstun": cycle(20, [FLINCH_S, with_(FLINCH_S, spine=26, upper_arm_R=78, upper_arm_L=-58)]),
    "shield": cycle(40, [SHIELD, with_(SHIELD, upper_arm_R=62, upper_arm_L=57)]),
    "dizzy": cycle(60, [DIZZY, with_(DIZZY, spine=(-15, 0, -10), head=(-20, 0, -15))]),
    "specialfall": cycle(30, [HELPLESS, with_(HELPLESS, upper_arm_R=165, upper_arm_L=125)]),
    "grab_hold": cycle(40, [HOLD, with_(HOLD, upper_arm_R=73, upper_arm_L=68, spine=-7)]),
    "grabbed": cycle(16, [STRUGGLE, with_(STRUGGLE, spine=20, head=15, upper_arm_R=60, forearm_R=60, upper_arm_L=-10)]),
    # Kunai jab: 16 frames, hit 2-3. Kunai2: 16, hit 2-3. Kunai3: 28, hit 4-6.
    "ninja_kunai": [(1, S), (2, CHOP), (4, CHOP_LOW), (9, CHOP_LOW), (16, S)],
    "ninja_kunai2": [(1, CHOP_LOW), (2, BACKHAND), (4, with_(BACKHAND, upper_arm_L=100)), (9, BACKHAND), (16, S)],
    "ninja_kunai3": [(1, BACKHAND), (3, with_(S, upper_arm_R=140, forearm_R=20)), (4, FINISH), (6, with_(FINISH, upper_arm_R=70)), (16, with_(S, spine=-10)), (28, S)],
    # Palm thrust: 20 frames, hit 3-5. Rising chop: 24, hit 4-10. Sweep: 20, hit 4-6.
    "ninja_palm_thrust": [(1, S), (2, PALM_WIND), (3, PALM), (6, PALM), (12, with_(S, upper_arm_R=50, forearm_R=60)), (20, S)],
    "ninja_rising_chop": [(1, S), (3, RISE_LOW), (4, RISE_FRONT), (8, RISE_TOP), (11, with_(RISE_TOP, upper_arm_R=150)), (16, with_(S, upper_arm_R=120, forearm_R=60)), (24, S)],
    "ninja_sweep": [(1, CROUCH), (3, with_(crouch(0.2), upper_arm_R=-40)), (4, SWEEP), (7, SWEEP), (12, CROUCH), (20, CROUCH)],
    # Dash slice: 34 frames, hit 5-9.
    "ninja_dash_slice": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (4, DASH_TRAIL), (5, DASH_CUT), (9, with_(DASH_CUT, upper_arm_R=80)), (22, with_(S, spine=-14)), (34, S)],
    # Chop (fsmash): charge 8, hit 12-14. Flip kick: charge 6, hit 9-12. Spin kick: charge 5, hit 7-9.
    "ninja_chop": [(1, S), (6, CHOP_WIND), (8, CHOP_WIND), (11, CHOP_MID), (12, CHOP_HIT), (15, CHOP_DOWN), (28, CHOP_DOWN), (42, S)],
    "ninja_flip_kick": [(1, S), (4, FLIP_LOW), (6, FLIP_LOW), (8, with_(FLIP_KICK, thigh_R=90)), (9, FLIP_KICK), (13, FLIP_KICK), (26, with_(S, spine=-6)), (40, S)],
    "ninja_spin_kick": [(1, S), (4, SPIN_WIND), (5, SPIN_WIND), (7, SPIN_FRONT), (10, SPIN_FRONT), (12, SPIN_BACK), (16, SPIN_BACK), (28, CROUCH), (38, S)],
    # Aerials: air spin 30 (3-5, 6-20), flying kick 32 (5-8), back hook 30 (4-7),
    # up flip 28 (4-7), axe kick 38 (10-13).
    "ninja_air_spin": [(1, AIR_S), (3, SPIN_FRONT_A), (6, SPIN_BACK_A), (12, with_(SPIN_BACK_A, upper_arm_R=150)), (20, with_(AIR_TUCK, upper_arm_R=290)), (30, with_(AIR_S, upper_arm_R=380))],
    "ninja_flying_kick": [(1, AIR_S), (3, FLY_WIND), (5, with_(FLY, thigh_R=110)), (6, FLY), (10, FLY), (20, with_(AIR_S, spine=-5)), (32, AIR_S)],
    "ninja_back_hook": [(1, AIR_S), (3, with_(AIR_S, thigh_L=10, shin_L=-120)), (4, HOOK), (8, HOOK), (18, with_(HOOK, thigh_L=-60, shin_L=-50)), (30, AIR_S)],
    "ninja_up_flip": [(1, AIR_S), (3, with_(AIR_S, thigh_R=70, shin_R=-110)), (4, UP_FLIP), (7, UP_FLIP), (16, with_(AIR_S, spine=10)), (28, AIR_S)],
    "ninja_axe_kick": [(1, AIR_S), (6, AXE_WIND), (10, AXE), (14, AXE), (24, with_(AIR_S, spine=0)), (38, AIR_S)],
    # Specials. Shuriken leaves the hand on 10; shadow dash dashes 6-14; smoke bomb
    # teleports on 8; substitution counters 5-24.
    "ninja_shuriken": [(1, S), (3, SHURIKEN_SHOW), (6, SHURIKEN_SHOW), (8, SHURIKEN_WIND), (9, with_(SHURIKEN_WIND, upper_arm_R=55, forearm_R=55)), (10, SHURIKEN_RELEASE), (18, SHURIKEN_RELEASE), (26, S)],
    "ninja_shadow_dash": [(1, S), (3, DASH_CROUCH), (5, DASH_CROUCH), (6, DASH_LEAN), (14, DASH_LEAN), (20, with_(DASH_LEAN, upper_arm_R=40)), (28, with_(S, spine=-10)), (34, S)],
    "ninja_smoke_bomb": [(1, S), (3, SMOKE_CROUCH), (7, SMOKE_CROUCH), (8, SMOKE_RISE), (16, SMOKE_RISE), (26, with_(HELPLESS, upper_arm_R=120)), (40, HELPLESS)],
    "ninja_substitution": [(1, S), (4, SUB_STANCE), (24, SUB_STANCE), (32, with_(SUB_STANCE, upper_arm_R=40)), (40, S)],
    "ninja_substitution_strike": [(1, SUB_STANCE), (3, with_(SUB_STANCE, upper_arm_R=140, forearm_R=20)), (4, SUB_STRIKE), (8, SUB_STRIKE), (16, with_(SUB_STRIKE, upper_arm_R=70)), (28, S)],
    # Grab: 28 frames, 6-7. Dash grab: 36, 8-9. Pummel: 14, hit 3.
    "ninja_grab": [(1, S), (5, REACH), (8, REACH), (16, HOLD), (28, S)],
    "ninja_dash_grab": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (7, DASH_REACH), (10, DASH_REACH), (22, with_(HOLD, spine=-12)), (36, S)],
    "ninja_pummel": [(1, HOLD), (3, POMEL), (6, POMEL), (14, HOLD)],
    # Throws release on 11 (f), 14 (b), 11 (u), 12 (d).
    "ninja_throw_forward": [(1, HOLD), (7, with_(HOLD, spine=8, upper_arm_R=40, forearm_R=110)), (11, THROW_F), (17, THROW_F), (28, S)],
    "ninja_throw_back": [(1, HOLD), (8, THROW_B_LOAD), (14, THROW_B), (20, THROW_B), (34, S)],
    "ninja_throw_up": [(1, HOLD), (5, with_(crouch(0.1), upper_arm_R=60, upper_arm_L=60)), (11, THROW_U), (17, THROW_U), (30, S)],
    "ninja_throw_down": [(1, HOLD), (6, with_(HOLD, thigh_R=88, shin_R=-100)), (12, THROW_D), (18, THROW_D), (30, S)],
    # Dodges: spot 26 (3-17), rolls 32 (4-15), air dodge 34-40 (3-18 / 3-25).
    "spotdodge": [(1, S), (3, SIDESTEP), (17, SIDESTEP), (26, S)],
    "roll_f": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "roll_b": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "airdodge": [(1, AIR_S), (4, AIRDODGE), (25, AIRDODGE), (34, AIR_S), (40, AIR_S)],
}


def apply_pose(rig, pose):
    for pb in rig.pose.bones:
        value = pose.get(pb.name, 0)
        pitch, twist, spread = value if isinstance(value, tuple) else (value, 0, 0)
        # Local X = world +Y, so counter-clockwise from the camera (-Y) is -X.
        pb.rotation_euler = (math.radians(-pitch), math.radians(twist), math.radians(spread))
        pb.location = (0, 0, 0)
    fwd, up = pose.get("hips_loc", (0, 0))
    rig.pose.bones["hips"].location = (0, up, fwd)  # hips local axes: Y = up, Z = forward


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
            rig.pose.bones["hips"].keyframe_insert("location", frame=frame, group="hips")
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, keys[0][0], action)
        track.mute = True
    rig.animation_data.action = None
    apply_pose(rig, S)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    rig = build_rig(ninja_mesh())
    build_actions(rig)
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)


if __name__ == "__main__":
    main()
