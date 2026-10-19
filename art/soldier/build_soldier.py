"""Builds the soldier: a heavy infantryman in a helmet, webbing and baggy fatigues,
with a two-handed rifle that ends in a bayonet. Then his armature and one action per
pose name the sim reports (`Fighter::anim()`). Saves `soldier.blend` next to this
script, exports `godot/models/soldier.glb`, and builds the lobbed grenade as
`godot/models/grenade.glb` (his side special's projectile).

    blender --background --factory-startup --python art/soldier/build_soldier.py

He stands on the chef's skeleton (same joints, same 1.2 m), so the shapes, pose
helpers and conventions come from `art/fighter/build_fighter.py` (see its README).
On top of it is one bone, `rifle`, held in the right (near) fist, plus the left arm
posed to support the barrel. Each pose says where the rifle points with `aim`:
degrees as seen by the game camera with the fighter facing right, 0 = forward,
90 = up, 180 = backward.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "soldier.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "soldier.glb")
GRENADE_GLB_PATH = os.path.join(ROOT, "godot", "models", "grenade.glb")

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

# The chef's bones, minus the pie, plus the rifle: it lies along +X through the
# right fist (the trigger grip between the curled fingers), barrel forward.
GRIP = Vector((0.0, -0.166, 0.388))
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONES.append(("rifle", "forearm.R", tuple(GRIP), tuple(GRIP + Vector((0.55, 0, 0))), FWD))
BONE_NAMES = [b[0] for b in BONES]

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the
# armband and chest patch) with the player's color; "Camo" (the fatigues) is swapped
# for a procedural camo shader on import; the rest keep their own.
MATERIALS = {
    "Body": ((0.70, 0.12, 0.12, 1), 0.7, 0.0),
    "Camo": ((0.33, 0.38, 0.22, 1), 0.9, 0.0),
    "Skin": ((0.82, 0.62, 0.48, 1), 0.55, 0.0),
    "Lip": ((0.62, 0.38, 0.33, 1), 0.45, 0.0),
    "Hair": ((0.16, 0.12, 0.09, 1), 0.6, 0.0),
    "Eye": ((0.93, 0.91, 0.87, 1), 0.12, 0.0),
    "Iris": ((0.20, 0.16, 0.09, 1), 0.15, 0.0),
    "Pupil": ((0.01, 0.01, 0.01, 1), 0.1, 0.0),
    "Helmet": ((0.30, 0.33, 0.20, 1), 0.5, 0.0),
    "HelmetBand": ((0.22, 0.24, 0.15, 1), 0.7, 0.0),
    "Boot": ((0.09, 0.08, 0.07, 1), 0.35, 0.0),
    "Glove": ((0.20, 0.22, 0.16, 1), 0.7, 0.0),
    "Web": ((0.24, 0.27, 0.16, 1), 0.8, 0.0),
    "Seam": ((0.20, 0.22, 0.14, 1), 0.9, 0.0),
    "Wood": ((0.42, 0.30, 0.18, 1), 0.5, 0.0),
    "Gunmetal": ((0.20, 0.21, 0.23, 1), 0.3, 0.8),
    "Barrel": ((0.12, 0.12, 0.13, 1), 0.35, 0.7),
    "Steel": ((0.72, 0.74, 0.77, 1), 0.15, 0.9),
    "Polymer": ((0.14, 0.15, 0.13, 1), 0.6, 0.0),
    "Grenade": ((0.26, 0.30, 0.16, 1), 0.55, 0.0),
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
    """A lean, hard face: square jaw and chin, a straight nose."""
    b = Blob(resolution=0.0035)
    b.ell((-0.005, 0, 1.085), (0.088, 0.075, 0.09))  # cranium
    b.ell((0.022, 0, 1.03), (0.072, 0.063, 0.074))  # face and jaw
    b.ell((0.054, 0, 0.98), (0.04, 0.043, 0.024), stiffness=3)  # square chin
    b.cap((-0.012, 0, 0.84), (0.0, 0, 0.99), 0.05)  # neck
    for s in (1, -1):
        b.ell((0.062, s * 0.042, 1.045), (0.022, 0.024, 0.018), stiffness=3)  # cheekbones
        b.cap((-0.02, s * 0.056, 1.015), (0.06, s * 0.032, 0.968), 0.016, stiffness=3)  # jawline
        b.cap((0.082, s * 0.012, 1.097), (0.076, s * 0.05, 1.103), 0.012, stiffness=3)  # brow ridge
        b.ball((0.075, s * 0.031, 1.072), 0.013, stiffness=4, negative=True)  # eye socket
        b.ell((-0.012, s * 0.078, 1.06), (0.017, 0.01, 0.028), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-10 * s)))  # ears
        b.ell((-0.006, s * 0.086, 1.062), (0.008, 0.007, 0.015), stiffness=5, negative=True)
    b.cap((0.086, 0, 1.092), (0.103, 0, 1.048), 0.009, stiffness=3)  # nose bridge
    b.ell((0.101, 0, 1.044), (0.012, 0.014, 0.01), stiffness=3)  # tip
    b.cap((0.09, -0.019, 1.006), (0.09, 0.019, 1.006), 0.0035, stiffness=6, negative=True)  # mouth
    b.ell((0.087, 0, 0.998), (0.009, 0.018, 0.006), stiffness=4)  # lower lip
    return b


def hair_blob():
    """Short back-and-sides hair, cropped where the helmet covers the top."""
    b = Blob(resolution=0.004)
    b.ell((-0.03, 0, 1.09), (0.09, 0.085, 0.075))
    for s in (1, -1):
        b.ell((0.03, s * 0.077, 1.07), (0.014, 0.008, 0.03), stiffness=4)  # sideburns
        b.ell((-0.01, s * 0.09, 1.06), (0.028, 0.02, 0.036), stiffness=4, negative=True)  # room for the ears
    b.ell((0.05, 0, 1.06), (0.05, 0.08, 0.06), stiffness=4, negative=True)  # clear of the face
    b.ell((0.0, 0, 1.18), (0.09, 0.09, 0.07), stiffness=5, negative=True)  # the helmet covers the crown
    return b


def fatigues_blob():
    """The fatigue shirt: a lean chest and narrow waist with soft folds at the hem."""
    b = Blob(resolution=0.006)
    b.ell((0.005, 0, 0.775), (0.1, 0.14, 0.11))  # chest
    b.ell((0.0, 0, 0.62), (0.09, 0.12, 0.1))  # waist
    for s in (1, -1):
        b.ell((-0.005, s * 0.09, 0.845), (0.055, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.15, 0.83), (0.052, 0.045, 0.045))  # shoulder seam
        b.ell((-0.055, s * 0.06, 0.77), (0.04, 0.06, 0.07))  # shoulder blades
    b.ell((0.0, 0, 0.46), (0.12, 0.14, 0.02), stiffness=4)  # hem
    return b


def sleeve_blob(s):
    """A baggy fatigue sleeve, with the cloth bunched a little above the cuff."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.005)
    b.ell((0.0, y - s * 0.005, 0.825), (0.055, 0.055, 0.06))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.046)
    b.ell((0.012, y, 0.73), (0.035, 0.038, 0.06), stiffness=3)  # biceps
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.06), 0.043)
    b.ell((-0.008, y, 0.6), (0.036, 0.038, 0.05), stiffness=3)  # forearm
    b.ell((-0.012, y, WRIST[1] + 0.03), (0.032, 0.034, 0.03), stiffness=3)  # bunched cuff
    return b


def hand_blob(s):
    """A gloved hand with separate fingers, curled to grip the rifle's fore-end."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0025)
    b.cap((0, y, WRIST[1] + 0.03), (0, y, WRIST[1] - 0.01), 0.021)  # wrist
    b.ell((0.0, y - s * 0.002, WRIST[1] - 0.03), (0.034, 0.02, 0.036), stiffness=3)  # palm
    # Four separate fingers, each curled over toward the palm.
    for i, x in enumerate((0.03, 0.014, -0.002, -0.018)):
        knuckle = Vector((x, y, WRIST[1] - 0.065))
        b.cap(knuckle + Vector((0, 0, 0.015)), knuckle, 0.0085, stiffness=4)
        b.cap(knuckle, knuckle + Vector((0, -s * 0.03, -0.002)), 0.008, stiffness=4)
        b.cap(knuckle + Vector((0, -s * 0.03, -0.002)), knuckle + Vector((0, -s * 0.032, 0.02)), 0.0075, stiffness=4)
    # Thumb, wrapped over the curled fingers.
    b.cap((0.028, y - s * 0.004, WRIST[1] - 0.02), (0.038, y - s * 0.016, WRIST[1] - 0.045), 0.01, stiffness=4)
    b.cap((0.038, y - s * 0.016, WRIST[1] - 0.045), (0.02, y - s * 0.03, WRIST[1] - 0.055), 0.0085, stiffness=4)
    return b


def leg_blob(s):
    """One leg of the fatigue trousers, bloused into the boot."""
    y = s * HIP[0]
    b = Blob(resolution=0.006)
    b.ell((-0.025, s * 0.05, 0.48), (0.09, 0.07, 0.07))  # seat
    b.cap((0, y, HIP[1] - 0.05), (0, y, KNEE[1]), 0.062)
    b.ell((0.01, y + s * 0.004, 0.43), (0.07, 0.066, 0.1), stiffness=3)  # thigh
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.02), 0.052)
    b.ell((-0.012, y, 0.21), (0.052, 0.054, 0.08), stiffness=3)  # calf
    b.ell((0.0, y, 0.09), (0.06, 0.058, 0.02), stiffness=4)  # bloused cuff
    return b


def boot_blob(s):
    """A lace-up combat boot, its shaft rising over the trouser cuff."""
    y = s * HIP[0]
    b = Blob(resolution=0.004)
    b.ell((0.04, y, 0.05), (0.09, 0.046, 0.045), stiffness=3)  # foot
    b.ell((0.115, y, 0.04), (0.05, 0.045, 0.035), stiffness=3)  # toe box
    b.ell((-0.025, y, 0.05), (0.042, 0.042, 0.05), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.17), 0.044)  # shaft
    b.ell((0.05, y, -0.1), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat sole
    return b


def face(m):
    """Eyes, brows and lips on the modeled face."""
    def on_skin(y, z, lift):
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.031, 1.072, 0)
        eye = socket - Vector((0.012 - 0.004, 0, 0))
        m.part(uv_ellipsoid(m.bm, eye, (0.012,) * 3, segments=(16, 10)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.011, 0, -0.001)), (0.0024, 0.007, 0.007), segments=(14, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.013, 0, -0.001)), (0.0012, 0.0034, 0.0034), segments=(10, 6)), "head", "Pupil")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0005, 0, 0.0035)), (0.0128, 0.0138, 0.0098), segments=(16, 10)), "head", "Skin")
        m.part(uv_ellipsoid(m.bm, eye + Vector((-0.001, 0, -0.0105)), (0.0128, 0.0136, 0.006), segments=(16, 8)), "head", "Skin")
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.012, 1.098), (0.03, 1.099), (0.05, 1.096))]
        m.part(tube(m.bm, brow, [0.0045, 0.006, 0.0038], sides=8), "head", "Hair")
    m.part(uv_ellipsoid(m.bm, on_skin(0, 1.0095, -0.004), (0.009, 0.019, 0.005), segments=(14, 8)), "head", "Lip")


def helmet(m):
    """A steel-pot helmet from parts: a fitted dome, a brim band and a chinstrap."""
    center = lambda z: Vector((-0.012, 0, z))  # noqa: E731
    fit = [m.fit(("head",), center(1.13), 2 * math.pi * j / 48) + 0.006 for j in range(48)]

    def dome_r(a, z):
        t = (z - 1.13) / 0.13
        return fit[round(a / (2 * math.pi) * 48) % 48] * (1 - 0.18 * t) + 0.004

    m.part(ring_band(m.bm, center, dome_r, 1.11, 1.25, rows=7, sides=48), "head", "Helmet")
    top = uv_ellipsoid(m.bm, (0, 0, 0), (1, 1, 1), segments=(48, 16))
    for v in top:
        x, y, z = v.co
        a = math.atan2(y, x)
        r = dome_r(a, 1.25) * 1.04
        v.co = center(1.25) + Vector((x * r, y * r, z * (0.045 if z > 0 else 0.028)))
    m.part(top, "head", "Helmet")
    # The brim: a fitted band flaring out a touch.
    rim = ring_band(m.bm, center, lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48] + 0.016, 1.09, 1.13, rows=2, sides=48)
    m.part(rim, "head", "HelmetBand")
    # Chinstrap: a band under the jaw, hugging the face.
    strap = [m.hit("head", (0.5, s * 0.05, 1.01), (-1, 0, 0))[0] for s in (1, -1)]
    strap = [strap[0] + Vector((0, 0, 0.004)), Vector((-0.005, 0, 0.94)), strap[1] + Vector((0, 0, 0.004))]
    m.part(tube(m.bm, strap, [0.006, 0.007, 0.006], sides=8), "head", "Web")


def webbing(m, on_fatigues):
    """A simple chest webbing: a band across the chest with two pouches."""
    center = lambda z: Vector((0.005, 0, z))  # noqa: E731
    fit = [m.fit(("fatigues",), center(0.775), 2 * math.pi * j / 48) + 0.008 for j in range(48)]
    band = ring_band(m.bm, center, lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48], 0.71, 0.79, rows=2, sides=48)
    m.weigh(band, on_fatigues)
    m.paint(band, "Web")
    for s in (1, -1):
        loc, normal = m.hit("fatigues", (0.5, s * 0.08, 0.75), (-1, 0, 0))
        pouch = uv_ellipsoid(m.bm, loc + normal * 0.02, (0.03, 0.045, 0.05), segments=(12, 8))
        m.weigh(pouch, on_fatigues)
        m.paint(pouch, "Web")


def armband(m, on_sleeve):
    """The `Body` armband on the near (right) sleeve, so the player color shows."""
    y = -SHOULDER[0]  # the near side
    ring = []
    for i in range(24):
        a = 2 * math.pi * i / 24
        ring.append(Vector((0.0, y + 0.055 * math.sin(a), 0.80 + 0.055 * math.cos(a))))
    band = tube(m.bm, ring, [0.006] * len(ring), sides=8)
    m.weigh(band, on_sleeve)
    m.paint(band, "Body")


def seams(m, on_sleeve, on_leg, side):
    """A couple of stitching seams along one sleeve and one leg (the cloth is sewn)."""
    y = side * SHOULDER[0]
    line = [Vector((0.004, y, z)) for z in (0.80, 0.70, 0.58, 0.46)]
    m.weigh(tube(m.bm, line, [0.0022] * len(line), sides=6), on_sleeve)
    m.paint(tube(m.bm, line, [0.0022] * len(line), sides=6), "Seam")
    y = side * HIP[0]
    line = [Vector((0.004, y, z)) for z in (0.48, 0.40, 0.30, 0.20)]
    verts = tube(m.bm, line, [0.0022] * len(line), sides=6)
    m.weigh(verts, on_leg)
    m.paint(verts, "Seam")


def rifle(m):
    """The rifle as a multi-part prop along +X from the grip: wooden stock, metal
    receiver, dark barrel, polymer fore-end and grip, a curved magazine, sights and
    a steel bayonet at the muzzle."""
    bm = m.bm

    def at(x, y=0.0, z=0.0):
        return GRIP + Vector((x, y, z))

    def rod(x0, x1, r, mat, sides=12):
        m.part(tube(bm, [at(x0), at(x1)], [r, r], sides=sides), "rifle", mat)

    # Wooden stock, sloping down behind the grip.
    stock = [at(-0.04), at(-0.16, 0, -0.03), at(-0.26, 0, -0.08)]
    m.part(tube(bm, stock, [0.026, 0.032, 0.03], sides=10), "rifle", "Wood")
    # Receiver: the metal body around the trigger.
    rod(0.0, 0.16, 0.022, "Gunmetal")
    # Barrel, forward from the receiver.
    rod(0.16, 0.48, 0.011, "Barrel")
    # Polymer fore-end around the barrel.
    rod(0.15, 0.32, 0.018, "Polymer")
    # Curved magazine below the receiver.
    mag = [at(0.05, 0, -0.02), at(0.07, 0, -0.08), at(0.04, 0, -0.13)]
    m.part(tube(bm, mag, [0.015, 0.017, 0.012], sides=10), "rifle", "Gunmetal")
    # Pistol grip behind the trigger.
    grip = [at(0.0, 0, 0.0), at(-0.02, 0, -0.06), at(-0.01, 0, -0.09)]
    m.part(tube(bm, grip, [0.014, 0.013, 0.012], sides=8), "rifle", "Polymer")
    # Front sight post.
    rod(0.46, 0.5, 0.006, "Gunmetal")
    # Bayonet: a socket at the muzzle, then a flattened steel blade.
    rod(0.47, 0.52, 0.013, "Gunmetal")
    base, length, width, thick, steps = 0.52, 0.20, 0.024, 0.007, 12
    rings = []
    for i in range(steps + 1):
        t = i / steps
        x = base + length * t
        w, th = width * (1 - t), thick * (1 - t)
        if i == steps:
            rings.append([bm.verts.new(at(x + 0.012))])
        else:
            rings.append([bm.verts.new(at(x, w * a, th * b)) for a, b in ((0, 0.5), (-0.5, 0.15), (0, -0.5), (0.5, 0.15))])
    faces = []
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(4):
            quad = (r0[j], r0[(j + 1) % 4], r1[0]) if len(r1) == 1 else (r0[j], r0[(j + 1) % 4], r1[(j + 1) % 4], r1[j])
            faces.append((bm.faces.new(quad), j))
    faces.append((bm.faces.new(list(reversed(rings[0]))), 0))
    m.weigh([v for r in rings for v in r], "rifle")
    for f, j in faces:
        f.material_index = MAT["Steel"]
        f.smooth = False


def soldier_mesh():
    m = Model()
    m.blob("head", head_blob(), 0.5, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    fatigues = m.blob("fatigues", fatigues_blob(), 0.25, "Camo", by_distance("hips", "spine"))
    sleeves = {}
    legs = {}
    for side, s in (("L", 1), ("R", -1)):
        sleeve = m.blob(f"sleeve.{side}", sleeve_blob(s), 0.25, "Camo", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", hand_blob(s), 0.3, "Glove", f"forearm.{side}")
        leg = m.blob(f"leg.{side}", leg_blob(s), 0.25, "Camo", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"boot.{side}", boot_blob(s), 0.3, "Boot", f"foot.{side}")
        sleeves[side] = sleeve
        legs[side] = leg
    face(m)
    helmet(m)
    webbing(m, m.weights_near(fatigues))
    armband(m, m.weights_near(sleeves["R"]))
    seams(m, m.weights_near(sleeves["R"]), m.weights_near(legs["R"]), -1)
    rifle(m)

    mesh = bpy.data.meshes.new("SoldierMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    return mesh


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
    rig = bpy.data.objects.new("Fighter", bpy.data.armatures.new("SoldierRig"))
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

    body = bpy.data.objects.new("Soldier", mesh)
    bpy.context.scene.collection.objects.link(body)
    body.parent = rig
    for name in BONE_NAMES:
        body.vertex_groups.new(name=name)
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    return rig


# --- Poses ------------------------------------------------------------------
# The chef's pose format ({bone: degrees or (pitch, twist, spread)}, "hips_loc"),
# plus "aim": where the rifle points (see the module docstring).


def stance(drop=0.05, lean=-6, aim=12):
    """Two-handed ready stance: the rifle held across the body, barrel up slightly."""
    pose = guard(drop=drop, lean=lean)
    pose.update({"upper_arm.R": 26 - lean, "forearm.R": 82, "upper_arm.L": 38 - lean, "forearm.L": 66, "aim": aim})
    return pose


def lunge(pose, fwd, drop, front, back=-0.2):
    """`pose` with the hips moved forward and down, feet re-planted wide."""
    return planted(with_(pose, hips_loc=(fwd, -drop)), front, back)


def pitch(value):
    return value[0] if isinstance(value, tuple) else value


def turned(pose, twist):
    """`pose` turned about the vertical by `twist` degrees (spins go past 360)."""
    return with_(pose, hips=(pitch(pose.get("hips", 0)), twist, 0))


def holding_rifle(pose, facing):
    """Keeps the rifle pointed at `facing` no matter where the arms are."""
    chain = sum(pitch(pose.get(b, 0)) for b in ("hips", "spine", "upper_arm.R", "forearm.R"))
    return with_(pose, aim=facing, rifle=facing - chain)


S = stance()
CROUCH = with_(crouch(0.16), upper_arm_R=16, forearm_R=72, upper_arm_L=26, forearm_L=60, aim=4)
AIR_S = with_(AIR, aim=24)
FLINCH_S = with_(FLINCH, aim=90)
HELPLESS = with_(AIR_S, spine=10, head=-10, upper_arm_R=150, forearm_R=30, upper_arm_L=140, forearm_L=40, aim=150,
                 thigh_R=20, shin_R=-40, thigh_L=5, shin_L=-30)
HOLD = with_(S, spine=-6, upper_arm_R=8, forearm_R=72, upper_arm_L=70, forearm_L=40, aim=-110)
STRUGGLE = with_(S, spine=15, head=10, upper_arm_R=30, forearm_R=80, upper_arm_L=-30, forearm_L=100, aim=80)
SHIELD = with_(stance(drop=0.07, lean=-4), upper_arm_R=20, forearm_R=96, upper_arm_L=46, forearm_L=110, aim=96)
DIZZY = with_(S, spine=(-15, 0, 10), head=(-20, 0, 15), upper_arm_R=-5, forearm_R=60, upper_arm_L=-5, forearm_L=60, aim=-60)
SIDESTEP = with_(crouch(0.08), spine=-10, head=10, upper_arm_R=6, forearm_R=70, upper_arm_L=16, forearm_L=60, aim=-90)
BALL = with_(crouch(0.3), spine=-60, head=40, upper_arm_R=60, forearm_R=130, upper_arm_L=60, forearm_L=130, aim=-100)
AIRDODGE = with_(AIR_S, spine=-10, upper_arm_R=60, forearm_R=120, upper_arm_L=55, forearm_L=125, thigh_R=70, shin_R=-120, thigh_L=60, shin_L=-110, aim=-120)

# Ground attacks. Comments give the sim frames (sim/src/moves.rs).
BUTT_WIND = lunge(with_(S, spine=8, head=-6, upper_arm_R=40, forearm_R=90, aim=120, upper_arm_L=40, forearm_L=60), -0.02, 0.05, 0.18)
BUTT = lunge(with_(S, spine=-12, head=10, upper_arm_R=20, forearm_R=30, aim=-20, upper_arm_L=30, forearm_L=50), 0.04, 0.07, 0.24)
BUTT2_WIND = lunge(with_(S, spine=8, head=-8, upper_arm_R=60, forearm_R=100, aim=150, upper_arm_L=20, forearm_L=60), -0.03, 0.06, 0.18)
BUTT2 = lunge(with_(S, spine=-16, head=12, upper_arm_R=30, forearm_R=10, aim=-40, upper_arm_L=20, forearm_L=50), 0.06, 0.09, 0.3)
BAY_WIND = lunge(with_(S, spine=8, head=-8, upper_arm_R=140, forearm_R=40, aim=90, upper_arm_L=40, forearm_L=60), -0.03, 0.06, 0.18)
BAY = lunge(with_(S, spine=-24, head=16, upper_arm_R=120, forearm_R=0, aim=0, upper_arm_L=40, forearm_L=20), 0.14, 0.1, 0.44, -0.22)
BAY_THROUGH = with_(BAY, upper_arm_R=96, aim=-20)
RUP_LOW = with_(crouch(0.1), upper_arm_R=40, forearm_R=50, aim=-40)
RUP_FRONT = with_(S, spine=-4, upper_arm_R=110, forearm_R=0, aim=20, upper_arm_L=30)
RUP_TOP = with_(S, hips_loc=(0, -0.01), spine=8, head=-10, upper_arm_R=176, forearm_R=0, aim=100, upper_arm_L=40)
SWEEP_WIND = planted(with_(crouch(0.22), spine=-10, upper_arm_R=-20, forearm_R=50, aim=150, upper_arm_L=40), 0.26, -0.26)
SWEEP = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=90, forearm_R=0, aim=-20, upper_arm_L=-50), 0.34, -0.3)
CHARGE_WIND = planted(with_(guard(drop=0.07, lean=-30), hips_loc=(0.06, -0.07), upper_arm_R=-40, forearm_R=60, aim=-150, upper_arm_L=40, forearm_L=60), 0.2, -0.26)
CHARGE = planted(with_(guard(drop=0.08, lean=-24), hips_loc=(0.12, -0.08), upper_arm_R=90, forearm_R=0, aim=10, upper_arm_L=-40, forearm_L=20), 0.36, -0.26)

# Smash attacks: the charge pose is held while charging.
STOCK_WIND = lunge(with_(S, spine=12, head=-12, upper_arm_R=170, forearm_R=30, aim=160, upper_arm_L=160, forearm_L=30), -0.04, 0.05, 0.2)
STOCK = lunge(with_(S, spine=-26, head=20, upper_arm_R=116, forearm_R=0, aim=4, upper_arm_L=110, forearm_L=8), 0.14, 0.12, 0.42, -0.24)
STOCK_DOWN = with_(STOCK, upper_arm_R=80, upper_arm_L=76, aim=-30)
BUP_LOW = with_(crouch(0.14), upper_arm_R=44, forearm_R=30, aim=-40)
BUP_FRONT = with_(S, upper_arm_R=110, forearm_R=0, aim=30, spine=0)
BUP_TOP = planted(with_(S, hips_loc=(0, 0.02), spine=6, head=-14, upper_arm_R=178, forearm_R=0, aim=100, upper_arm_L=-20), 0.08, -0.08)
SSWEEP_WIND = planted(with_(crouch(0.2), spine=-10, upper_arm_R=-30, forearm_R=50, aim=175, upper_arm_L=40), 0.28, -0.28)
SSWEEP_FRONT = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=94, forearm_R=0, aim=-15, upper_arm_L=-60), 0.36, -0.3)
SSWEEP_BACK = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=-82, forearm_R=0, aim=190, upper_arm_L=60), 0.3, -0.36)

# Aerials
AIR_TUCK = with_(AIR_S, thigh_R=80, shin_R=-120, thigh_L=60, shin_L=-110)
SPIN_FRONT = with_(AIR_TUCK, spine=-10, upper_arm_R=110, forearm_R=0, aim=30)
SPIN_BACK = with_(AIR_TUCK, spine=10, upper_arm_R=230, forearm_R=0, aim=200)
SPIN_LOW = with_(AIR_TUCK, spine=10, upper_arm_R=270, forearm_R=0, aim=230)
ABAY_HIGH = with_(AIR_S, spine=10, head=-6, upper_arm_R=172, forearm_R=20, aim=125)
ABAY = with_(AIR_S, spine=-20, head=14, upper_arm_R=100, forearm_R=0, aim=2)
ABAY_LOW = with_(ABAY, upper_arm_R=64, aim=-50)
ELBOW_WIND = with_(AIR_S, upper_arm_R=25, forearm_R=90, aim=80)
ELBOW_HIT = with_(AIR_S, spine=-22, head=30, upper_arm_R=-70, forearm_R=40, aim=160, upper_arm_L=70, forearm_L=30,
              thigh_R=70, shin_R=-100, thigh_L=30, shin_L=-90)
AUP_LOW = with_(AIR_S, upper_arm_R=110, forearm_R=20, aim=40)
AUP = with_(AIR_S, spine=10, head=-18, upper_arm_R=172, forearm_R=0, aim=95)
STOMP_WIND = with_(AIR_S, spine=6, upper_arm_R=165, forearm_R=20, aim=95, thigh_R=90, shin_R=-130, thigh_L=80, shin_L=-120)
STOMP = with_(AIR_S, spine=-8, head=8, upper_arm_R=22, forearm_R=0, aim=-88, upper_arm_L=-30,
              thigh_R=60, shin_R=-20, foot_R=-30, thigh_L=-30, shin_L=-30, foot_L=-30)

# Specials
AIM = planted(with_(S, hips_loc=(-0.02, -0.06), spine=2, head=-4, upper_arm_R=30, forearm_R=88, aim=2, upper_arm_L=34, forearm_L=70), 0.2, -0.2)
SHOT = planted(with_(S, hips_loc=(0.02, -0.06), spine=-8, head=2, upper_arm_R=30, forearm_R=88, aim=2, upper_arm_L=34, forearm_L=70), 0.22, -0.2)
GRENADE_WIND = planted(with_(S, hips_loc=(-0.04, -0.06), spine=10, head=-10, upper_arm_R=140, forearm_R=40, aim=130, upper_arm_L=60, forearm_L=30), 0.17, -0.2)
GRENADE_READY = planted(with_(S, hips_loc=(-0.02, -0.07), spine=-2, head=-2, upper_arm_R=160, forearm_R=10, aim=150, upper_arm_L=20, forearm_L=60), 0.18, -0.2)
GRENADE_THROW = planted(with_(S, hips_loc=(0.06, -0.07), spine=-16, head=10, upper_arm_R=70, forearm_R=0, aim=-10, upper_arm_L=-30, forearm_L=40), 0.26, -0.2)
BLAST_CROUCH = with_(crouch(0.24), spine=-20, head=18, upper_arm_R=-20, forearm_R=50, aim=-150, upper_arm_L=30, forearm_L=60)
BLAST_UP = with_(AIR_S, spine=-10, head=6, upper_arm_R=-30, forearm_R=30, aim=-140, thigh_R=20, shin_R=-20, thigh_L=-30, shin_L=-30)
SHIELD_STANCE = planted(with_(S, hips_loc=(-0.02, -0.07), spine=4, head=-4, upper_arm_R=46, forearm_R=96, aim=96, upper_arm_L=56, forearm_L=92), 0.16, -0.18)
BASH_WIND = with_(SHIELD_STANCE, upper_arm_R=150, forearm_R=20, aim=130)
BASH = lunge(with_(S, spine=-20, head=16, upper_arm_R=104, forearm_R=0, aim=8, upper_arm_L=-36, forearm_L=20), 0.12, 0.1, 0.4)
BASH_THROUGH = with_(BASH, upper_arm_R=70, aim=-30)

# Grabs and throws: the left (far) hand does the grabbing; the rifle stays slung.
REACH = lunge(with_(S, spine=-14, head=10, upper_arm_L=88, forearm_L=6, upper_arm_R=-6, forearm_R=70, aim=-130), 0.06, 0.06, 0.26)
DASH_REACH = planted(with_(guard(drop=0.08, lean=-26), hips_loc=(0.1, -0.08), upper_arm_L=96, forearm_L=4, upper_arm_R=-30, forearm_R=60, aim=-150), 0.32, -0.26)
PUMMEL = with_(HOLD, spine=-14, head=10, upper_arm_R=88, forearm_R=30, aim=176)
FTHROW_WIND = lunge(with_(HOLD, spine=10, upper_arm_L=40, forearm_L=90), -0.04, 0.12, 0.18)
FTHROW = lunge(with_(HOLD, spine=-26, head=18, upper_arm_L=100, forearm_L=0, upper_arm_R=60, forearm_R=40, aim=-20), 0.1, 0.12, 0.36)
BTHROW_WIND = lunge(with_(HOLD, spine=-16, upper_arm_L=168, forearm_L=30), 0.02, 0.18, 0.2)
BTHROW = lunge(with_(HOLD, spine=18, head=-10, upper_arm_L=232, forearm_L=0, upper_arm_R=-30, aim=-150), -0.04, 0.08, 0.16, -0.3)
UTHROW_WIND = with_(crouch(0.14), upper_arm_L=60, forearm_L=60, upper_arm_R=10, forearm_R=70, aim=-120)
UTHROW = planted(with_(HOLD, hips_loc=(0, 0.01), spine=8, head=-14, upper_arm_L=178, forearm_L=0), 0.08, -0.08)
DTHROW_WIND = with_(HOLD, spine=-10, thigh_R=88, shin_R=-100, foot_R=-10)
DTHROW = planted(with_(crouch(0.26), spine=-30, head=20, upper_arm_L=60, forearm_L=10, upper_arm_R=60, forearm_R=40, aim=176), 0.3, -0.22)


def walk(stride, lift, drop, swing, phase, run):
    """A walk/run key holding the rifle across the chest."""
    pose = walk_key(stride, lift, drop, swing, phase)
    if run:
        return with_(pose, upper_arm_R=20, forearm_R=80, upper_arm_L=30, forearm_L=60, aim=-16)
    return with_(pose, upper_arm_R=24, forearm_R=90, upper_arm_L=34, forearm_L=70, aim=10)


ANIMATIONS = {
    "idle": cycle(60, [S, with_(stance(drop=0.056), upper_arm_R=27, aim=11)]),
    "walk": cycle(40, [walk(0.12, 0.06, d, 22, i, False) for i, d in enumerate((0.04, 0.025, 0.04, 0.025))]),
    "run": cycle(24, [walk(0.2, 0.12, d, 45, i, True) for i, d in enumerate((0.06, 0.03, 0.06, 0.03))]),
    # JumpSquat lasts FighterParams::jump_squat (5) frames.
    "jumpsquat": [(1, stance(drop=0.07, lean=-12)), (5, CROUCH)],
    "air": cycle(40, [AIR_S, with_(AIR_S, thigh_R=60, shin_R=-100, thigh_L=10, upper_arm_R=30, aim=20)]),
    # Played backwards from the end as Landing counts down, so it always finishes on guard.
    "land": [(1, CROUCH), (5, S)],
    "crouch": cycle(60, [CROUCH, with_(CROUCH, hips_loc=(0, -0.165), aim=3)]),
    "hitstun": cycle(20, [FLINCH_S, with_(FLINCH_S, spine=26, upper_arm_R=78, upper_arm_L=-58, aim=100)]),
    "shield": cycle(40, [SHIELD, with_(SHIELD, upper_arm_R=48, aim=95)]),
    "dizzy": cycle(60, [DIZZY, with_(DIZZY, spine=(-15, 0, -10), head=(-20, 0, -15))]),
    "specialfall": cycle(30, [HELPLESS, with_(HELPLESS, upper_arm_R=165, upper_arm_L=125, aim=160)]),
    "grab_hold": cycle(40, [HOLD, with_(HOLD, upper_arm_L=75, spine=-8)]),
    "grabbed": cycle(16, [STRUGGLE, with_(STRUGGLE, spine=20, head=15, upper_arm_R=60, forearm_R=70, upper_arm_L=-10, aim=80)]),
    # Butt strike: 20 frames, hit 4-5. Butt strike 2: 24, hit 4-6.
    "soldier_butt_strike": [(1, S), (3, BUTT_WIND), (4, BUTT), (6, BUTT), (12, BUTT), (20, S)],
    "soldier_butt_strike_2": [(1, BUTT), (3, BUTT2_WIND), (4, BUTT2), (7, BUTT2), (14, BUTT2), (24, S)],
    # Bayonet: 32 frames, hit 7-9 (the tip at x 12).
    "soldier_bayonet": [(1, S), (5, BAY_WIND), (7, BAY), (9, BAY_THROUGH), (18, BAY_THROUGH), (32, S)],
    # Rifle up: 32 frames, in front 7-9, overhead 10-13.
    "soldier_rifle_up": [(1, S), (5, RUP_LOW), (7, RUP_FRONT), (10, RUP_TOP), (13, with_(RUP_TOP, upper_arm_R=160, aim=105)), (22, with_(S, upper_arm_R=60, aim=30)), (32, S)],
    # Leg sweep: 26 frames, hit 7-9 along the floor. Starts and ends crouched.
    "soldier_leg_sweep": [(1, CROUCH), (5, SWEEP_WIND), (7, SWEEP), (10, SWEEP), (16, SWEEP), (26, CROUCH)],
    # Shoulder charge: 42 frames, hit 7-11 then 12-18.
    "soldier_shoulder_charge": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (5, CHARGE_WIND), (7, CHARGE), (14, CHARGE), (26, with_(S, spine=-14)), (42, S)],
    # Stock smash: charge frame 12, hit 16-18. Bayonet upper: charge 8, hit 11-16. Stock sweep: charge 6, front 9-11, back 15-17.
    "soldier_stock_smash": [(1, S), (8, STOCK_WIND), (12, STOCK_WIND), (15, with_(STOCK, upper_arm_R=140, upper_arm_L=130, aim=70)), (16, STOCK), (20, STOCK_DOWN), (36, STOCK_DOWN), (52, S)],
    "soldier_bayonet_upper": [(1, S), (5, BUP_LOW), (8, BUP_LOW), (11, BUP_FRONT), (12, with_(BUP_TOP, upper_arm_R=160, aim=88)), (16, BUP_TOP), (28, with_(BUP_TOP, upper_arm_R=150, aim=100)), (48, S)],
    "soldier_stock_sweep": [(1, S), (4, SSWEEP_WIND), (6, SSWEEP_WIND), (9, SSWEEP_FRONT), (12, with_(SSWEEP_FRONT, upper_arm_R=20, aim=-90)), (15, SSWEEP_BACK), (18, SSWEEP_BACK), (30, CROUCH), (46, S)],
    # Air spin: 38 frames, strong 5-8, weak 9-20. Air bayonet: hit 9-12. Back elbow: 7-10.
    # Air up: 6-10. Air stomp: 13-16.
    "soldier_air_spin": [(1, AIR_S), (3, with_(AIR_TUCK, upper_arm_R=60, aim=0)), (5, SPIN_FRONT), (8, with_(SPIN_FRONT, upper_arm_R=150, aim=75)), (9, SPIN_BACK), (12, SPIN_LOW), (22, with_(AIR_TUCK, upper_arm_R=290, aim=250)), (32, with_(AIR_S, upper_arm_R=380, aim=400)), (38, with_(AIR_S, upper_arm_R=405, aim=405))],
    "soldier_air_bayonet": [(1, AIR_S), (6, ABAY_HIGH), (8, with_(ABAY, upper_arm_R=120)), (9, ABAY), (12, ABAY_LOW), (22, ABAY_LOW), (40, AIR_S)],
    "soldier_back_elbow": [(1, AIR_S), (5, ELBOW_WIND), (7, ELBOW_HIT), (11, with_(ELBOW_HIT, upper_arm_R=-55, aim=185)), (24, with_(ELBOW_HIT, upper_arm_R=-55, aim=185)), (36, AIR_S)],
    "soldier_air_up": [(1, AIR_S), (4, AUP_LOW), (6, AUP), (10, with_(AUP, upper_arm_R=188, aim=104)), (20, with_(AUP, upper_arm_R=188, aim=104)), (34, AIR_S)],
    "soldier_air_stomp": [(1, AIR_S), (9, STOMP_WIND), (12, with_(STOMP, upper_arm_R=90, aim=-40)), (13, STOMP), (18, STOMP), (30, STOMP), (46, AIR_S)],
    # Specials. Rifle shot: fires on 10. Grenade: thrown on 14. Blast jump: rises 4-18.
    "soldier_rifle_shot": [(1, S), (5, AIM), (9, AIM), (10, SHOT), (16, SHOT), (30, S)],
    "soldier_grenade": [(1, S), (6, GRENADE_WIND), (12, GRENADE_READY), (13, with_(GRENADE_READY, upper_arm_R=130, aim=120)), (14, GRENADE_THROW), (22, GRENADE_THROW), (40, S)],
    "soldier_blast_jump": [(1, S), (3, BLAST_CROUCH), (4, BLAST_UP), (18, with_(BLAST_UP, upper_arm_R=-10, aim=-150)), (28, HELPLESS), (46, HELPLESS)],
    # Riot shield: counters hits on 6-26. Shield bash: 34 frames, hit 5-8.
    "soldier_riot_shield": [(1, S), (4, SHIELD_STANCE), (26, SHIELD_STANCE), (34, with_(SHIELD_STANCE, upper_arm_R=40, aim=80)), (48, S)],
    "soldier_shield_bash": [(1, SHIELD_STANCE), (4, BASH_WIND), (5, BASH), (8, BASH_THROUGH), (16, BASH_THROUGH), (34, S)],
    # Grab: 32 frames, grab box 7-8. Dash grab: 42, 9-10. Pummel hits on 3.
    "soldier_grab": [(1, S), (6, REACH), (9, REACH), (18, HOLD), (32, S)],
    "soldier_dash_grab": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (8, DASH_REACH), (11, DASH_REACH), (25, with_(HOLD, spine=-12)), (42, S)],
    "soldier_pummel": [(1, HOLD), (3, PUMMEL), (6, PUMMEL), (18, HOLD)],
    # Throws release on 13 (forward), 16 (back), 14 (up), 15 (down).
    "soldier_throw_forward": [(1, HOLD), (8, FTHROW_WIND), (13, FTHROW), (19, FTHROW), (32, S)],
    "soldier_throw_back": [(1, HOLD), (9, BTHROW_WIND), (16, BTHROW), (22, BTHROW), (38, S)],
    "soldier_throw_up": [(1, HOLD), (7, UTHROW_WIND), (14, UTHROW), (20, UTHROW), (34, S)],
    "soldier_throw_down": [(1, HOLD), (8, DTHROW_WIND), (15, DTHROW), (22, DTHROW), (34, S)],
    # Dodges: spot 26 frames (invincible 3-17), rolls 32 (4-15), air dodge 34-40 (3-18 / 3-25).
    "spotdodge": [(1, S), (3, SIDESTEP), (17, SIDESTEP), (26, S)],
    "roll_f": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "roll_b": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "airdodge": [(1, AIR_S), (4, AIRDODGE), (25, AIRDODGE), (34, AIR_S), (40, AIR_S)],
}


def apply_pose(rig, pose):
    # The rifle's own angle is whatever is left of `aim` after the arm's chain.
    chain = sum(pitch(pose.get(b, 0)) for b in ("hips", "spine", "upper_arm.R", "forearm.R"))
    angles = dict(pose, rifle=pose.get("aim", 12) - chain)
    for pb in rig.pose.bones:
        p, twist, spread = (lambda v: v if isinstance(v, tuple) else (v, 0, 0))(angles.get(pb.name, 0))
        # Local X = world +Y, so counter-clockwise from the camera (-Y) is -X.
        pb.rotation_euler = (math.radians(-p), math.radians(twist), math.radians(spread))
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


def build_grenade():
    """The flying grenade (for the side special): a pineapple body, a fuze, a pin ring
    and a spoon along the side."""
    bm = bmesh.new()
    body = uv_ellipsoid(bm, (0, 0, 0.03), (0.042, 0.042, 0.05), segments=(20, 14))
    neck = tube(bm, [(0, 0, 0.075), (0, 0, 0.095)], [0.014, 0.012], sides=10)
    lever = tube(bm, [(0.004, 0, 0.092), (0.004, 0.05, 0.06), (0.004, 0.055, 0.03)], [0.003, 0.0035, 0.003], sides=6)
    ring = ring_band(bm, lambda z: Vector((0, 0, z)), lambda a, z: 0.016, 0.088, 0.092, rows=1, sides=16)
    parts = {"Grenade": body + neck, "Steel": lever + ring}
    mesh = bpy.data.meshes.new("GrenadeMesh")
    for mat, verts in parts.items():
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = MAT[mat]
            f.smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    obj = bpy.data.objects.new("Grenade", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    rig = build_rig(soldier_mesh())
    build_actions(rig)
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)

    # The grenade goes in a file of its own; it isn't saved in soldier.blend.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_grenade()
    bpy.ops.export_scene.gltf(filepath=GRENADE_GLB_PATH, export_format="GLB", export_yup=True, export_animations=False, export_cameras=False, export_lights=False)


if __name__ == "__main__":
    main()
