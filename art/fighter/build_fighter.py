"""Builds the basic fighter: a jointed mannequin, its armature, and one action per
pose name the sim reports (`Fighter::anim()`), then saves `fighter.blend` next to
this script and exports `godot/models/fighter.glb`.

    blender --background --factory-startup --python art/fighter/build_fighter.py

Conventions (see README.md):
- Meters, feet at the origin, facing +X, character's left = +Y. 1.2 m tall,
  matching the sim hurtbox (height 12 units, SCALE 0.1).
- 60 fps. Attack actions are keyed on the sim's 1-based move frames, so Blender
  frame 5 of `ftilt` is sim frame 5 of FTilt.
- Pose angles are degrees, counter-clockwise as seen by the game camera with the
  fighter facing right: + swings a hanging limb forward, tips an upright bone
  back, and raises the toes. Child angles are relative to the parent.
"""

import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "fighter.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "fighter.glb")

FPS = 60
UP, DOWN, FWD = (1, 0, 0), (-1, 0, 0), (0, 0, -1)  # roll targets: every bone's local X ends up = world +Y

# name, parent, head, tail, roll target. Arms and legs are mirrored below.
BONES = [
    ("hips", None, (0, 0, 0.55), (0, 0, 0.68), UP),
    ("spine", "hips", (0, 0, 0.68), (0, 0, 0.88), UP),
    ("head", "spine", (0, 0, 0.90), (0, 0, 1.18), UP),
]
SHOULDER, ELBOW, WRIST = (0.18, 0.85), (0.18, 0.64), (0.18, 0.45)  # (|y|, z)
HIP, KNEE, ANKLE = (0.09, 0.53), (0.09, 0.30), (0.09, 0.07)
THIGH_LEN, SHIN_LEN = HIP[1] - KNEE[1], KNEE[1] - ANKLE[1]
for side, s in (("L", 1), ("R", -1)):
    BONES += [
        (f"upper_arm.{side}", "spine", (0, s * SHOULDER[0], SHOULDER[1]), (0, s * ELBOW[0], ELBOW[1]), DOWN),
        (f"forearm.{side}", f"upper_arm.{side}", (0, s * ELBOW[0], ELBOW[1]), (0, s * WRIST[0], WRIST[1]), DOWN),
        (f"thigh.{side}", "hips", (0, s * HIP[0], HIP[1]), (0, s * KNEE[0], KNEE[1]), DOWN),
        (f"shin.{side}", f"thigh.{side}", (0, s * KNEE[0], KNEE[1]), (0, s * ANKLE[0], ANKLE[1]), DOWN),
        (f"foot.{side}", f"shin.{side}", (0, s * HIP[0], ANKLE[1]), (0.13, s * HIP[0], ANKLE[1]), FWD),
    ]
BONE_NAMES = [b[0] for b in BONES]

# Material name -> base color. Godot replaces "Body" with the player's color.
MATERIALS = {
    "Body": (0.55, 0.55, 0.6, 1),
    "Skin": (0.93, 0.78, 0.65, 1),
    "Accent": (0.95, 0.95, 0.95, 1),
    "Eye": (0.05, 0.05, 0.08, 1),
}


# --- Mesh -------------------------------------------------------------------


def ellipsoid(bm, deform, bone, mat, center, radii, axis=(0, 0, 1)):
    """Adds a smooth ellipsoid whose local Z (radius radii[2]) points along `axis`,
    weighted fully to `bone`: rigid parts, like a wooden mannequin."""
    rot = Vector(axis).normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
    matrix = Matrix.Translation(center) @ rot @ Matrix.Diagonal((*radii, 1))
    verts = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=1.0, matrix=matrix)["verts"]
    group = BONE_NAMES.index(bone)
    for v in verts:
        v[deform][group] = 1.0
    for f in {f for v in verts for f in v.link_faces}:
        f.material_index = list(MATERIALS).index(mat)
        f.smooth = True


def segment(bm, deform, bone, mat, a, b, radius, overlap=0.025):
    a, b = Vector(a), Vector(b)
    ellipsoid(bm, deform, bone, mat, (a + b) / 2, (radius, radius, (b - a).length / 2 + overlap), b - a)


def build_mesh():
    bm = bmesh.new()
    deform = bm.verts.layers.deform.verify()
    e = lambda *args, **kw: ellipsoid(bm, deform, *args, **kw)
    seg = lambda *args, **kw: segment(bm, deform, *args, **kw)

    e("hips", "Body", (0, 0, 0.57), (0.11, 0.14, 0.08))
    e("spine", "Body", (0, 0, 0.69), (0.10, 0.12, 0.09))
    e("spine", "Body", (0, 0, 0.80), (0.12, 0.17, 0.11))
    seg("head", "Skin", (0, 0, 0.88), (0, 0, 0.95), 0.045)
    e("head", "Skin", (0, 0, 1.05), (0.14, 0.14, 0.14))
    for y in (0.05, -0.05):
        e("head", "Eye", (0.122, y, 1.075), (0.025, 0.022, 0.035))
    for side, s in (("L", 1), ("R", -1)):
        sh, el, wr = ((0, s * y, z) for y, z in (SHOULDER, ELBOW, WRIST))
        hp, kn, an = ((0, s * y, z) for y, z in (HIP, KNEE, ANKLE))
        e(f"upper_arm.{side}", "Body", sh, (0.06, 0.06, 0.06))
        seg(f"upper_arm.{side}", "Body", sh, el, 0.05)
        seg(f"forearm.{side}", "Skin", el, wr, 0.042)
        e(f"forearm.{side}", "Accent", (0, s * WRIST[0], WRIST[1] - 0.04), (0.06, 0.055, 0.06))
        seg(f"thigh.{side}", "Body", hp, kn, 0.065)
        seg(f"shin.{side}", "Body", kn, an, 0.055)
        e(f"foot.{side}", "Accent", (0.045, s * ANKLE[0], 0.045), (0.055, 0.045, 0.095), (1, 0, 0))

    mesh = bpy.data.meshes.new("FighterMesh")
    bm.to_mesh(mesh)
    bm.free()
    for name, color in MATERIALS.items():
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
        if bsdf is None:
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.6
        mesh.materials.append(mat)
    return mesh


# --- Rig --------------------------------------------------------------------


def build_rig(mesh):
    rig = bpy.data.objects.new("Fighter", bpy.data.armatures.new("FighterRig"))
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

    body = bpy.data.objects.new("Body", mesh)
    bpy.context.scene.collection.objects.link(body)
    body.parent = rig
    for name in BONE_NAMES:
        body.vertex_groups.new(name=name)
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    return rig


# --- Poses ------------------------------------------------------------------
# A pose is {bone: degrees or (pitch, twist, spread)} plus "hips_loc": (forward, up)
# in meters. Missing bones are at rest.


def leg_ik(pose, side, foot_x, lift=0.0):
    """Plants the ankle at (foot_x, rest ankle height + lift), knee bending forward,
    with the foot kept level. Accounts for the hips' pitch and offset in `pose`."""
    fwd, up = pose.get("hips_loc", (0, 0))
    hips_pitch = pose.get("hips", 0)
    dx, dz = foot_x - fwd, (ANKLE[1] + lift) - (HIP[1] + up)
    dist = min(math.hypot(dx, dz), THIGH_LEN + SHIN_LEN - 1e-3)
    aim = math.degrees(math.atan2(dx, -dz))  # 0 = straight down, + = forward
    at_hip = math.degrees(math.acos((THIGH_LEN**2 + dist**2 - SHIN_LEN**2) / (2 * THIGH_LEN * dist)))
    at_ankle = math.degrees(math.acos((SHIN_LEN**2 + dist**2 - THIGH_LEN**2) / (2 * SHIN_LEN * dist)))
    thigh, shin = aim + at_hip, aim - at_ankle
    pose[f"thigh.{side}"] = thigh - hips_pitch
    pose[f"shin.{side}"] = shin - thigh
    pose[f"foot.{side}"] = -shin
    return pose


def guard(drop=0.04, lean=-8, front=0.11, back=-0.11):
    """Fighting stance: knees bent, fists up. The near (camera-side, .R) leg leads."""
    pose = {
        "hips_loc": (0, -drop),
        "spine": lean,
        "head": -lean,
        "upper_arm.R": 35 - lean,
        "forearm.R": 105,
        "upper_arm.L": 20 - lean,
        "forearm.L": 115,
    }
    leg_ik(pose, "R", front)
    return leg_ik(pose, "L", back)


def crouch(drop=0.15):
    pose = guard(drop=drop, lean=-22)
    pose.update({"upper_arm.R": -10, "forearm.R": 60, "upper_arm.L": -20, "forearm.L": 60})
    return pose


def with_(pose, **changes):
    """Copy of `pose` with bones overridden; `upper_arm_R=10` sets "upper_arm.R"."""
    pose = dict(pose)
    pose.update({k.replace("_L", ".L").replace("_R", ".R"): v for k, v in changes.items()})
    return pose


def planted(pose, front=0.11, back=-0.11):
    """Re-solves both legs for the pose's hips, so the feet stay on the ground."""
    pose = dict(pose)
    leg_ik(pose, "R", front)
    return leg_ik(pose, "L", back)


def walk_key(stride, lift, drop, arm, phase):
    """One of four walk/run keys. phase 0: right foot ahead; 1: right planted under,
    left passing (lifted); 2: left ahead; 3: left planted, right passing."""
    lean = -8 - arm / 4
    pose = {"hips_loc": (0, -drop), "spine": lean, "head": -lean}
    swing = (1, 0, -1, 0)[phase] * arm
    pose.update({"upper_arm.R": -swing - lean, "upper_arm.L": swing - lean, "forearm.R": 30 + arm, "forearm.L": 30 + arm})
    right, left = [(stride, 0, -stride, 0)[phase], (-stride, 0, stride, 0)[phase]]
    leg_ik(pose, "R", right, lift if phase == 3 else 0)
    return leg_ik(pose, "L", left, lift if phase == 1 else 0)


def cycle(length, keys):
    """Evenly spaced keys over a loop of `length` frames, closing back on the first."""
    step = length // len(keys)
    return [(1 + i * step, k) for i, k in enumerate(keys)] + [(1 + length, keys[0])]


AIR = {
    "spine": -5,
    "head": 5,
    "upper_arm.R": 45,
    "forearm.R": 70,
    "upper_arm.L": -25,
    "forearm.L": 80,
    "thigh.R": 55,
    "shin.R": -95,
    "foot.R": 20,
    "thigh.L": 15,
    "shin.L": -70,
    "foot.L": 30,
}
FLINCH = {
    "hips_loc": (-0.03, 0),
    "spine": 22,
    "head": 18,
    "upper_arm.R": 70,
    "forearm.R": 50,
    "upper_arm.L": -50,
    "forearm.L": 60,
    "thigh.R": 35,
    "shin.R": -60,
    "thigh.L": -15,
    "shin.L": -40,
}

g = guard()
# Attacks: keys on the sim's frames. Hitbox frames from sim/src/moves.rs in comments.
PUNCH = with_(g, hips_loc=(0.05, -0.05), spine=-16, head=12, upper_arm_R=88, forearm_R=0, upper_arm_L=-5, forearm_L=120)
CHAMBER = with_(g, spine=6, head=-6, thigh_R=80, shin_R=-115, foot_R=10, upper_arm_R=-10, upper_arm_L=50)
KICK = with_(CHAMBER, hips_loc=(0.05, -0.02), spine=22, head=-18, thigh_R=97, shin_R=-4, foot_R=-35, upper_arm_R=-45, upper_arm_L=60)
leg_ik(KICK, "L", -0.08)
SEX_KICK = with_(AIR, spine=18, head=-10, thigh_R=88, shin_R=-6, foot_R=-40, thigh_L=25, shin_L=-105, upper_arm_R=-50, upper_arm_L=-70, forearm_R=20, forearm_L=20)

PUNCH2 = with_(g, hips_loc=(0.04, -0.05), spine=-14, head=10, upper_arm_L=88, forearm_L=0, upper_arm_R=15, forearm_R=115)
CROUCH = crouch()
DTILT = planted(with_(CROUCH, hips_loc=(0.12, -0.2), spine=-30, head=25, upper_arm_R=-35, upper_arm_L=50, forearm_L=40), 0.62, -0.2)
DASH = planted(with_(guard(drop=0.06, lean=-35), hips_loc=(0.08, -0.06), upper_arm_R=60, forearm_R=100, upper_arm_L=-20), 0.22, -0.25)

# Smash attacks: the pose on the charge frame is held while charging.
FSMASH_WIND = planted(with_(g, hips_loc=(-0.05, -0.07), spine=14, head=-10, upper_arm_R=-55, forearm_R=110, upper_arm_L=45, forearm_L=90), 0.2, -0.2)
FSMASH_HIT = planted(with_(g, hips_loc=(0.12, -0.08), spine=-25, head=18, upper_arm_R=95, forearm_R=0, upper_arm_L=-30, forearm_L=60), 0.32, -0.22)
USMASH_WIND = with_(crouch(0.14), upper_arm_R=-15, forearm_R=40, upper_arm_L=-15, forearm_L=40)
USMASH_HIT = planted(with_(g, hips_loc=(0, 0.02), spine=4, head=-12, upper_arm_R=172, forearm_R=0, upper_arm_L=165, forearm_L=5), 0.06, -0.06)
DSMASH_HIT = planted(
    with_(g, hips_loc=(0, -0.2), spine=-10, head=10, upper_arm_R=95, forearm_R=0, upper_arm_L=-95, forearm_L=0), 0.36, -0.36
)

# Aerials
FAIR_WIND = with_(AIR, spine=10, head=-5, upper_arm_R=175, forearm_R=25)
FAIR_HIT = with_(AIR, spine=-22, head=18, upper_arm_R=55, forearm_R=0, upper_arm_L=-60)
BAIR = with_(AIR, spine=-25, head=25, thigh_L=-95, shin_L=-5, foot_L=40, thigh_R=60, shin_R=-100, upper_arm_R=60, upper_arm_L=40, forearm_L=60)
UAIR = with_(AIR, spine=35, head=-20, thigh_R=150, shin_R=-5, foot_R=-20, thigh_L=20, shin_L=-90, upper_arm_R=-60, upper_arm_L=-80)
DAIR_WIND = with_(AIR, thigh_R=95, shin_R=-135, thigh_L=85, shin_L=-125, upper_arm_R=120, upper_arm_L=110)
DAIR_HIT = with_(
    AIR, spine=-5, thigh_R=5, shin_R=0, foot_R=-40, thigh_L=-5, shin_L=0, foot_L=-40, upper_arm_R=140, upper_arm_L=130, forearm_R=20, forearm_L=20
)

# Specials
SHOT_WIND = with_(g, spine=10, upper_arm_R=15, forearm_R=115, upper_arm_L=10, forearm_L=120)
SHOT = planted(with_(g, hips_loc=(0.05, -0.05), spine=-12, head=8, upper_arm_R=90, forearm_R=5, upper_arm_L=85, forearm_L=10))
LUNGE_WIND = with_(crouch(0.1), spine=5, head=-10, upper_arm_R=-40, forearm_R=110, upper_arm_L=50, forearm_L=90)
# Superman punch. The whole body pitches 65 degrees forward, so the arm angles that
# point it level are offset by that.
LUNGE = {
    "hips_loc": (0.05, 0.12),
    "hips": -55,
    "spine": -10,
    "head": 45,
    "upper_arm.R": 155,
    "forearm.R": 0,
    "upper_arm.L": 35,
    "forearm.L": 20,
    "thigh.R": -50,
    "shin.R": -20,
    "foot.R": 30,
    "thigh.L": -60,
    "shin.L": -40,
    "foot.L": 30,
}
UPPERCUT = {
    "hips_loc": (0, 0.05),
    "spine": 8,
    "head": -15,
    "upper_arm.R": 175,
    "forearm.R": 0,
    "upper_arm.L": -20,
    "forearm.L": 60,
    "thigh.R": 80,
    "shin.R": -100,
    "thigh.L": -10,
    "shin.L": -10,
    "foot.L": -30,
}
HELPLESS = with_(AIR, spine=10, head=-10, upper_arm_R=150, forearm_R=30, upper_arm_L=140, forearm_L=40, thigh_R=20, shin_R=-40, thigh_L=5, shin_L=-30)
TUCK = with_(AIR, spine=-30, head=20, thigh_R=120, shin_R=-140, thigh_L=110, shin_L=-140, upper_arm_R=70, forearm_R=120, upper_arm_L=60, forearm_L=120)
PLUNGE = with_(
    AIR, spine=0, head=-5, thigh_R=0, shin_R=0, foot_R=-50, thigh_L=0, shin_L=0, foot_L=-50, upper_arm_R=165, upper_arm_L=160, forearm_R=0, forearm_L=0
)
IMPACT = planted(with_(crouch(0.2), upper_arm_R=100, forearm_R=0, upper_arm_L=-100, forearm_L=0), 0.2, -0.2)

# Grabs and throws
REACH = planted(with_(g, hips_loc=(0.06, -0.06), spine=-15, head=10, upper_arm_R=85, forearm_R=10, upper_arm_L=80, forearm_L=15))
DASH_REACH = planted(with_(guard(drop=0.08, lean=-28), hips_loc=(0.1, -0.08), upper_arm_R=95, forearm_R=5, upper_arm_L=90, forearm_L=10), 0.3, -0.25)
HOLD = with_(g, spine=-5, upper_arm_R=70, forearm_R=50, upper_arm_L=65, forearm_L=55)
PUSH = planted(with_(g, hips_loc=(0.08, -0.06), spine=-20, head=12, upper_arm_R=95, forearm_R=0, upper_arm_L=90, forearm_L=0), 0.25, -0.15)
LIFT = planted(with_(g, hips_loc=(0, 0), spine=10, head=-15, upper_arm_R=175, forearm_R=0, upper_arm_L=170, forearm_L=0), 0.08, -0.08)
SLAM_UP = with_(g, spine=10, upper_arm_R=160, upper_arm_L=155, forearm_R=20, forearm_L=20)
SLAM = with_(crouch(0.15), spine=-35, head=25, upper_arm_R=60, upper_arm_L=55, forearm_R=0, forearm_L=0)
STRUGGLE = with_(g, spine=15, head=10, upper_arm_R=40, forearm_R=90, upper_arm_L=-30, forearm_L=100)

# Shield and dodges
SHIELD = with_(guard(drop=0.06, lean=-5), upper_arm_R=60, forearm_R=110, upper_arm_L=55, forearm_L=115)
DIZZY = with_(g, spine=(-15, 0, 10), head=(-20, 0, 15), upper_arm_R=-5, forearm_R=10, upper_arm_L=-5, forearm_L=10)
SIDESTEP = with_(crouch(0.08), spine=(-10, 70, 0), head=(0, -40, 0))
BALL = with_(crouch(0.3), spine=-60, head=40, upper_arm_R=60, forearm_R=130, upper_arm_L=60, forearm_L=130)
AIRDODGE = with_(AIR, spine=-10, upper_arm_R=60, forearm_R=120, upper_arm_L=55, forearm_L=125, thigh_R=70, shin_R=-120, thigh_L=60, shin_L=-110)

ANIMATIONS = {
    "idle": cycle(60, [g, with_(guard(drop=0.055), upper_arm_R=37, upper_arm_L=22)]),
    "walk": cycle(40, [walk_key(0.12, 0.06, d, 22, i) for i, d in enumerate((0.04, 0.025, 0.04, 0.025))]),
    "run": cycle(24, [walk_key(0.2, 0.12, d, 45, i) for i, d in enumerate((0.06, 0.03, 0.06, 0.03))]),
    # JumpSquat lasts FighterParams::jump_squat (4) frames.
    "jumpsquat": [(1, guard(drop=0.07, lean=-12)), (4, crouch())],
    "air": cycle(40, [AIR, with_(AIR, thigh_R=60, shin_R=-100, thigh_L=10, upper_arm_R=50, upper_arm_L=-20)]),
    # Played backwards from the end as Landing counts down, so it always finishes on guard.
    "land": [(1, crouch(0.16)), (5, g)],
    # Jab: 17 frames, hitbox frames 2-3.
    "jab": [(1, g), (2, PUNCH), (6, PUNCH), (12, with_(g, upper_arm_R=60)), (17, g)],
    # FTilt: 26 frames, hitbox frames 5-7.
    "ftilt": [(1, g), (3, CHAMBER), (5, KICK), (8, KICK), (12, with_(KICK, thigh_R=88)), (18, CHAMBER), (26, g)],
    # UTilt: 30 frames, hitbox frames 5-12 (above the head).
    "utilt": [
        (1, g),
        (4, with_(crouch(0.08), upper_arm_R=70, forearm_R=20)),
        (5, with_(g, upper_arm_R=135, forearm_R=0, spine=-4)),
        (8, with_(g, hips_loc=(0, 0), upper_arm_R=185, forearm_R=0, spine=8, head=0)),
        (12, with_(g, hips_loc=(0, 0), upper_arm_R=230, forearm_R=10, spine=14, head=-10)),
        (20, with_(g, upper_arm_R=120, forearm_R=60)),
        (30, g),
    ],
    # Nair: 36 frames, strong hit 3-6, weak 7-30 ("sex kick").
    "nair": [(1, AIR), (3, SEX_KICK), (26, with_(SEX_KICK, thigh_R=80, shin_R=-15)), (33, with_(AIR, spine=5)), (36, AIR)],
    "hitstun": cycle(20, [FLINCH, with_(FLINCH, spine=26, upper_arm_R=78, upper_arm_L=-58)]),
    "crouch": cycle(60, [CROUCH, with_(crouch(0.155), upper_arm_R=-8)]),
    # Jab2: 18 frames, hitbox 3-4 (the other fist). Jab3: 30 frames, kick on 4-6.
    "jab2": [(1, PUNCH), (3, PUNCH2), (7, PUNCH2), (13, with_(g, upper_arm_L=55)), (18, g)],
    "jab3": [(1, PUNCH2), (3, CHAMBER), (4, KICK), (8, KICK), (16, CHAMBER), (30, g)],
    # DTilt: 22 frames, low sweep 5-7. Starts and ends crouched.
    "dtilt": [(1, CROUCH), (4, DTILT), (8, DTILT), (14, CROUCH), (22, CROUCH)],
    # Dash attack: 38 frames, 6-16.
    "dashattack": [(1, walk_key(0.2, 0.12, 0.06, 45, 0)), (5, DASH), (16, DASH), (26, with_(g, spine=-15)), (38, g)],
    # FSmash: charge frame 10, hit 14-16. USmash: charge 7, hit 11-15. DSmash: charge 5, hit 8-10.
    "fsmash": [(1, g), (6, FSMASH_WIND), (10, FSMASH_WIND), (13, with_(FSMASH_HIT, upper_arm_R=60, forearm_R=40)), (14, FSMASH_HIT), (22, FSMASH_HIT), (34, with_(g, spine=-10)), (48, g)],
    "usmash": [(1, g), (5, USMASH_WIND), (7, USMASH_WIND), (11, USMASH_HIT), (16, USMASH_HIT), (26, with_(USMASH_HIT, upper_arm_R=110, forearm_R=60, upper_arm_L=100, forearm_L=60)), (46, g)],
    "dsmash": [(1, g), (4, crouch(0.15)), (5, crouch(0.15)), (8, DSMASH_HIT), (12, DSMASH_HIT), (24, crouch(0.12)), (44, g)],
    # Aerials. Fair hit 8-11, bair 6-9, uair 5-9, dair 12-15.
    "fair": [(1, AIR), (6, FAIR_WIND), (8, with_(FAIR_HIT, upper_arm_R=120)), (9, FAIR_HIT), (14, with_(FAIR_HIT, upper_arm_R=30)), (28, with_(AIR, spine=-5)), (40, AIR)],
    "bair": [(1, AIR), (4, with_(AIR, thigh_L=10, shin_L=-120)), (6, BAIR), (10, BAIR), (20, with_(BAIR, thigh_L=-60, shin_L=-50)), (34, AIR)],
    "uair": [(1, AIR), (3, with_(AIR, thigh_R=70, shin_R=-110)), (5, UAIR), (9, UAIR), (18, with_(AIR, spine=10)), (32, AIR)],
    "dair": [(1, AIR), (8, DAIR_WIND), (12, DAIR_HIT), (16, DAIR_HIT), (28, with_(AIR, spine=0)), (44, AIR)],
    # Specials. Neutral: projectile on 12. Side: lunge 8-16. Up: rise 4-18. Down: plunge from 15.
    "special_n": [(1, g), (8, SHOT_WIND), (12, SHOT), (20, SHOT), (36, g)],
    "special_s": [(1, g), (4, LUNGE_WIND), (7, LUNGE_WIND), (9, LUNGE), (16, LUNGE), (24, with_(AIR, spine=-10)), (40, AIR)],
    "special_u": [(1, g), (3, with_(crouch(0.12), upper_arm_R=-20, forearm_R=90)), (4, with_(UPPERCUT, upper_arm_R=120)), (6, UPPERCUT), (16, UPPERCUT), (26, with_(UPPERCUT, upper_arm_R=150, thigh_R=50)), (40, HELPLESS)],
    "special_d": [(1, CROUCH), (5, TUCK), (14, TUCK), (16, PLUNGE), (70, PLUNGE)],
    "special_d_land": [(1, IMPACT), (8, IMPACT), (30, g)],
    "specialfall": cycle(30, [HELPLESS, with_(HELPLESS, upper_arm_R=165, upper_arm_L=125)]),
    # Grab: 30 frames, grab box 7-8. Dash grab: 40 frames, 9-10.
    "grab": [(1, g), (6, REACH), (9, REACH), (18, with_(g, upper_arm_R=50, upper_arm_L=45)), (30, g)],
    "dashgrab": [(1, walk_key(0.2, 0.12, 0.06, 45, 0)), (8, DASH_REACH), (11, DASH_REACH), (25, with_(g, spine=-12)), (40, g)],
    "grab_hold": cycle(40, [HOLD, with_(HOLD, upper_arm_R=73, upper_arm_L=68, spine=-7)]),
    "grabbed": cycle(16, [STRUGGLE, with_(STRUGGLE, spine=20, head=15, upper_arm_R=60, forearm_R=70, upper_arm_L=-10, forearm_L=110)]),
    # Pummel hits on 3; throws release on 12 (f), 15 (b), 14 (u), 13 (d).
    "pummel": [(1, HOLD), (3, with_(HOLD, spine=-12, thigh_R=85, shin_R=-95)), (6, with_(HOLD, spine=-12, thigh_R=85, shin_R=-95)), (16, HOLD)],
    "fthrow": [(1, HOLD), (8, with_(HOLD, spine=8, upper_arm_R=40, upper_arm_L=35, forearm_R=110, forearm_L=110)), (12, PUSH), (18, PUSH), (30, g)],
    "bthrow": [(1, HOLD), (8, with_(HOLD, spine=(0, 60, 0))), (13, with_(HOLD, spine=(0, 120, 0), upper_arm_R=60)), (15, with_(g, spine=(10, 150, 0), upper_arm_R=100, upper_arm_L=95, forearm_R=0, forearm_L=0)), (22, with_(g, spine=(5, 60, 0))), (36, g)],
    "uthrow": [(1, HOLD), (6, with_(crouch(0.1), upper_arm_R=60, upper_arm_L=60, forearm_R=60, forearm_L=60)), (14, LIFT), (20, LIFT), (34, g)],
    "dthrow": [(1, HOLD), (6, SLAM_UP), (13, SLAM), (20, SLAM), (32, g)],
    "shield": cycle(40, [SHIELD, with_(SHIELD, upper_arm_R=62, upper_arm_L=57)]),
    "dizzy": cycle(60, [DIZZY, with_(DIZZY, spine=(-15, 0, -10), head=(-20, 0, -15))]),
    # Dodges: spot 26 frames (invincible 3-17), rolls 32 (4-15), air dodge 34-40 (3-18 / 3-25).
    "spotdodge": [(1, g), (3, SIDESTEP), (17, SIDESTEP), (26, g)],
    "roll_f": [(1, g), (4, BALL), (20, BALL), (28, CROUCH), (32, g)],
    "roll_b": [(1, g), (4, BALL), (20, BALL), (28, CROUCH), (32, g)],
    "airdodge": [(1, AIR), (4, AIRDODGE), (25, AIRDODGE), (34, AIR), (40, AIR)],
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
    apply_pose(rig, guard())


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    rig = build_rig(build_mesh())
    build_actions(rig)

    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)


def export(path):
    """Shared with export_fighter.py, so hand edits to the .blend export the same way."""
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_yup=True,
        export_apply=False,
        export_skins=True,
        export_def_bones=True,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_frame_step=1,
        # Frame 1 -> time 0, so sim frame n of a move is at (n - 1) / 60 s.
        export_anim_slide_to_zero=True,
        export_optimize_animation_size=False,
        export_cameras=False,
        export_lights=False,
    )


if __name__ == "__main__":
    main()
