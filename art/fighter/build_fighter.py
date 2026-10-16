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
