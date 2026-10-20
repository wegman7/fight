"""Builds the soldier: a heavy infantryman in a combat helmet and tactical goggles,
his face covered by a balaclava, a plate carrier with magazine pouches over his
fatigues and pads on his shoulders, elbows and knees, with a two-handed rifle that
ends in a bayonet. Then his armature and one action per pose name the sim reports
(`Fighter::anim()`). Saves `soldier.blend` next to this script, exports
`godot/models/soldier.glb`, and builds the lobbed grenade as
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
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

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
# armband and shoulder patch) with the player's color; "Camo" (the fatigues) and
# "Vest"/"VestPouch" (the carrier and its pouches) are swapped for cloth shaders on
# import; the rest keep their own.
MATERIALS = {
    "Body": ((0.62, 0.10, 0.10, 1), 0.85, 0.0),
    "Camo": ((0.30, 0.33, 0.21, 1), 0.95, 0.0),
    "Vest": ((0.42, 0.38, 0.28, 1), 0.95, 0.0),
    "VestPouch": ((0.35, 0.31, 0.22, 1), 0.95, 0.0),
    "Strap": ((0.13, 0.125, 0.10, 1), 0.9, 0.0),
    "Buckle": ((0.34, 0.35, 0.36, 1), 0.5, 0.4),
    "Pad": ((0.095, 0.095, 0.09, 1), 0.6, 0.0),
    "Boot": ((0.17, 0.125, 0.085, 1), 0.55, 0.0),
    "Sole": ((0.045, 0.045, 0.045, 1), 0.85, 0.0),
    "Lace": ((0.30, 0.26, 0.20, 1), 0.9, 0.0),
    "Glove": ((0.095, 0.09, 0.085, 1), 0.8, 0.0),
    "Balaclava": ((0.055, 0.055, 0.062, 1), 0.95, 0.0),
    "Helmet": ((0.17, 0.18, 0.13, 1), 0.8, 0.0),
    "HelmetBand": ((0.10, 0.11, 0.08, 1), 0.85, 0.0),
    "GoggleFrame": ((0.035, 0.035, 0.04, 1), 0.55, 0.0),
    "GoggleGlass": ((0.028, 0.035, 0.045, 1), 0.14, 0.0),
    "Steel": ((0.52, 0.54, 0.57, 1), 0.38, 0.6),
    "Gunmetal": ((0.135, 0.142, 0.15, 1), 0.7, 0.25),
    "Barrel": ((0.10, 0.105, 0.11, 1), 0.72, 0.15),
    "Polymer": ((0.10, 0.105, 0.10, 1), 0.65, 0.0),
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
# Cloth is metaball surfaces, one family per piece so the limbs don't fuse to the
# torso; hard gear (plates, buckles, rails, the rifle) is modeled in bmesh and
# either weighted to a bone or given the weights of the surface it is sewn onto.
# Meters, feet at the origin, facing +X, the character's left = +Y.


def box(bm, center, size):
    """An axis-aligned box at `center` with full extents `size`, for hard gear."""
    matrix = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*size, 1))
    return bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)["verts"]


def slab(bm, a, b, wa, ha, wb, hb, up=Vector((0, 0, 1))):
    """A rectangular prism from `a` to `b`, `wa` x `ha` at `a` and `wb` x `hb` at `b`.
    The cross-section is square to the axis, `up` picking which way it is rotated."""
    a, b = Vector(a), Vector(b)
    t = (b - a).normalized()
    up = Vector(up)
    n = (up - t * up.dot(t)).normalized()
    s = t.cross(n)
    rings = []
    for p, w, h in ((a, wa, ha), (b, wb, hb)):
        rings.append([bm.verts.new(p + s * (w / 2) + n * (h / 2)),
                      bm.verts.new(p - s * (w / 2) + n * (h / 2)),
                      bm.verts.new(p - s * (w / 2) - n * (h / 2)),
                      bm.verts.new(p + s * (w / 2) - n * (h / 2))])
    for j in range(4):
        bm.faces.new((rings[0][j], rings[0][(j + 1) % 4], rings[1][(j + 1) % 4], rings[1][j]))
    bm.faces.new(tuple(reversed(rings[0])))
    bm.faces.new(tuple(rings[1]))
    return rings[0] + rings[1]


def register(m, name, verts):
    """Make a bmesh part a ray-castable surface, so later details can be laid on it."""
    faces = {f for v in verts for f in v.link_faces}
    index = {v: i for i, v in enumerate(verts)}
    polys = [[index[v] for v in f.verts] for f in faces if all(v in index for v in f.verts)]
    m.surfaces[name] = BVHTree.FromPolygons([v.co.copy() for v in verts], polys)


def hug_patch(m, piece, center_at, angles, zs, lift, thickness, mat, weights="head"):
    """A curved plate laid on `piece`: a ray-cast grid over `angles` x `zs`, pushed out
    by `lift` and closed with `thickness`, so it reads as gear sitting on the cloth."""
    outer, inner = [], []
    for z in zs:
        row_out, row_in = [], []
        for a in angles:
            c = center_at(z)
            d = Vector((math.cos(a), math.sin(a), 0.0))
            loc, normal = m.hit(piece, c, d)
            if loc is None:
                loc, normal = c + d * 0.12, d
            row_out.append(m.bm.verts.new(loc + normal * lift))
            row_in.append(m.bm.verts.new(loc + normal * (lift - thickness)))
        outer.append(row_out)
        inner.append(row_in)
    na, nz = len(angles), len(zs)
    for rows, flip in ((outer, False), (inner, True)):
        for r0, r1 in zip(rows, rows[1:]):
            for j in range(na - 1):
                quad = (r0[j], r0[j + 1], r1[j + 1], r1[j])
                m.bm.faces.new(tuple(reversed(quad)) if flip else quad)
    edge = ([(0, j) for j in range(na)] + [(i, na - 1) for i in range(1, nz)] +
            [(nz - 1, j) for j in range(na - 2, -1, -1)] + [(i, 0) for i in range(nz - 2, 0, -1)])
    for k, (i0, j0) in enumerate(edge):
        i1, j1 = edge[(k + 1) % len(edge)]
        m.bm.faces.new((outer[i0][j0], outer[i1][j1], inner[i1][j1], inner[i0][j0]))
    verts = [v for row in outer + inner for v in row]
    m.weigh(verts, weights)
    m.paint(verts, mat)
    return verts


# The rifle's working axis: the barrel runs a little above the fist, so the hand wraps
# the pistol grip the way it should. The `rifle` bone itself still starts at GRIP.
AXIS = GRIP + Vector((0.0, 0.0, 0.05))


def balaclava_blob():
    """A knit balaclava: the whole head and jaw covered, a gaiter bunched over the
    collar, and a soft ridge where the cloth tents over the nose."""
    b = Blob(resolution=0.0035)
    b.ell((-0.005, 0, 1.086), (0.096, 0.083, 0.098))  # crown
    b.ell((0.024, 0, 1.028), (0.079, 0.072, 0.081))  # face and jaw
    b.ell((0.044, 0, 0.981), (0.045, 0.052, 0.036), stiffness=3)  # chin, masked
    b.cap((-0.014, 0, 0.85), (0.0, 0, 1.0), 0.059)  # neck, down into the collar
    b.ell((0.0, 0, 0.932), (0.063, 0.063, 0.028), stiffness=3)  # gaiter bunched up
    b.cap((0.088, 0, 1.086), (0.098, 0, 1.054), 0.015, stiffness=3)  # nose ridge
    b.ell((0.099, 0, 1.05), (0.011, 0.016, 0.011), stiffness=3)
    for s in (1, -1):
        b.ell((0.062, s * 0.043, 1.048), (0.021, 0.024, 0.019), stiffness=3)  # cheekbone
        b.ell((-0.012, s * 0.078, 1.058), (0.016, 0.011, 0.026), stiffness=4)  # ear under cloth
        # Folds: a crease from the cheek to the jaw, and two around the gaiter.
        b.cap((0.07, s * 0.052, 1.018), (0.045, s * 0.068, 0.985), 0.007, stiffness=5, negative=True)
        b.cap((0.02, s * 0.06, 0.905), (0.02, s * 0.06, 0.945), 0.008, stiffness=5, negative=True)
        b.cap((0.03, s * 0.05, 0.968), (0.05, s * 0.03, 1.006), 0.006, stiffness=5, negative=True)
    return b


def fatigues_blob():
    """The field shirt: a thick chest and shoulders, tapering hard to the waist, with
    the cloth folded where the plate carrier and the belt ride."""
    b = Blob(resolution=0.0055)
    b.ell((0.005, 0, 0.78), (0.104, 0.146, 0.114))  # chest
    b.ell((0.0, 0, 0.625), (0.093, 0.124, 0.104))  # waist
    b.ell((0.0, 0, 0.545), (0.101, 0.121, 0.058))  # hips and hem
    for s in (1, -1):
        b.ell((-0.005, s * 0.094, 0.848), (0.056, 0.072, 0.038))  # trapezius
        b.ell((0.0, s * 0.152, 0.828), (0.053, 0.046, 0.05))  # shoulder
        b.ell((-0.058, s * 0.062, 0.775), (0.042, 0.062, 0.074))  # shoulder blade
        b.ell((-0.012, s * 0.10, 0.715), (0.038, 0.042, 0.058))  # lat
        # Cloth folds: creases at the waist, the armpit and over the shoulders.
        b.cap((0.085, s * 0.07, 0.615), (0.07, s * 0.11, 0.63), 0.006, stiffness=5, negative=True)
        b.cap((0.06, s * 0.03, 0.575), (0.08, s * 0.09, 0.585), 0.005, stiffness=5, negative=True)
        b.cap((-0.09, s * 0.05, 0.70), (-0.07, s * 0.10, 0.71), 0.005, stiffness=5, negative=True)
        b.cap((0.05, s * 0.12, 0.775), (0.01, s * 0.145, 0.79), 0.006, stiffness=5, negative=True)
        b.cap((-0.02, s * 0.02, 0.655), (0.03, s * 0.06, 0.665), 0.005, stiffness=5, negative=True)
    return b


def sleeve_blob(s):
    """A field-shirt sleeve: a padded deltoid, a bunched cuff at the wrist."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0045)
    b.ell((0.0, y - s * 0.004, 0.822), (0.058, 0.058, 0.062))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.049)
    b.ell((0.012, y, 0.73), (0.037, 0.041, 0.062), stiffness=3)  # biceps
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.05), 0.045)
    b.ell((-0.008, y, 0.60), (0.039, 0.041, 0.055), stiffness=3)  # forearm muscle
    b.ell((0.0, y, WRIST[1] + 0.045), (0.036, 0.039, 0.026), stiffness=3)  # cuff roll
    # Creases bunched at the inside of the elbow and above the cuff.
    b.cap((-0.035, y, 0.672), (0.0, y, 0.655), 0.006, stiffness=5, negative=True)
    b.cap((-0.03, y, 0.63), (0.01, y, 0.618), 0.005, stiffness=5, negative=True)
    b.cap((-0.036, y - s * 0.02, 0.70), (-0.02, y + s * 0.03, 0.69), 0.005, stiffness=5, negative=True)
    b.cap((0.02, y - s * 0.03, 0.55), (0.015, y + s * 0.03, 0.545), 0.004, stiffness=5, negative=True)
    return b


def hand_blob(s):
    """A gloved fist with a gauntlet cuff and four fingers plus a thumb, curled to
    grip the rifle."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0022)
    b.cap((0, y, WRIST[1] + 0.05), (0, y, WRIST[1] - 0.004), 0.027)  # gauntlet cuff
    b.ell((0.0, y - s * 0.002, WRIST[1] - 0.03), (0.036, 0.022, 0.038), stiffness=3)  # palm
    b.ell((0.012, y - s * 0.004, WRIST[1] - 0.045), (0.024, 0.019, 0.02), stiffness=4)  # knuckles
    for x in (0.031, 0.014, -0.003, -0.019):
        knuckle = Vector((x, y, WRIST[1] - 0.065))
        b.cap(knuckle + Vector((0, 0, 0.017)), knuckle, 0.0095, stiffness=4)
        b.cap(knuckle, knuckle + Vector((0, -s * 0.03, -0.002)), 0.009, stiffness=4)
        b.cap(knuckle + Vector((0, -s * 0.03, -0.002)), knuckle + Vector((0, -s * 0.03, 0.02)), 0.0085, stiffness=4)
    b.cap((0.03, y - s * 0.004, WRIST[1] - 0.018), (0.04, y - s * 0.018, WRIST[1] - 0.046), 0.011, stiffness=4)
    b.cap((0.04, y - s * 0.018, WRIST[1] - 0.046), (0.02, y - s * 0.032, WRIST[1] - 0.056), 0.0095, stiffness=4)
    return b


def leg_blob(s):
    """Fatigue trousers: a heavy thigh with a cargo pocket, a calf, and the cuff
    bloused over the boot."""
    y = s * HIP[0]
    b = Blob(resolution=0.0055)
    b.ell((-0.025, s * 0.05, 0.48), (0.095, 0.075, 0.075))  # seat
    b.cap((0, y, HIP[1] - 0.05), (0, y, KNEE[1]), 0.066)
    b.ell((0.012, y + s * 0.004, 0.43), (0.075, 0.07, 0.105), stiffness=3)  # thigh
    b.ell((0.004, y + s * 0.052, 0.415), (0.052, 0.024, 0.068), stiffness=3)  # cargo pocket
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.03), 0.055)
    b.ell((-0.012, y, 0.22), (0.055, 0.057, 0.085), stiffness=3)  # calf
    b.ell((0.0, y, 0.158), (0.065, 0.063, 0.029), stiffness=3)  # bloused over the boot
    # Cloth folds behind the knee, across the calf and where the cuff gathers.
    b.cap((-0.06, y, 0.325), (-0.03, y, 0.36), 0.006, stiffness=5, negative=True)
    b.cap((0.04, y, 0.185), (0.05, y, 0.2), 0.005, stiffness=5, negative=True)
    b.cap((-0.05, y - s * 0.03, 0.255), (-0.055, y + s * 0.035, 0.245), 0.005, stiffness=5, negative=True)
    b.cap((-0.03, y - s * 0.03, 0.19), (-0.035, y + s * 0.035, 0.18), 0.004, stiffness=5, negative=True)
    b.cap((0.03, y - s * 0.04, 0.4), (0.035, y + s * 0.04, 0.39), 0.005, stiffness=5, negative=True)
    return b


def boot_blob(s):
    """A lace-up combat boot: a wide foot, a lugged sole line, a padded collar."""
    y = s * HIP[0]
    b = Blob(resolution=0.0035)
    b.ell((0.04, y, 0.056), (0.098, 0.048, 0.052), stiffness=3)  # foot
    b.ell((0.128, y, 0.046), (0.055, 0.043, 0.035), stiffness=3)  # toe box
    b.ell((-0.03, y, 0.062), (0.042, 0.043, 0.056), stiffness=3)  # heel counter
    b.cap((0.0, y, 0.05), (0.004, y, 0.172), 0.047)  # shaft
    b.ell((0.012, y, 0.162), (0.05, 0.05, 0.028), stiffness=3)  # padded collar
    b.ell((0.05, y, -0.1), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat sole
    return b


def pouches_blob():
    """The pouches hung on the carrier: three magazines in a row across the belly, an
    admin pouch on the chest, and one utility pouch on either flank."""
    b = Blob(resolution=0.0045)
    for y in (-0.062, 0.0, 0.062):
        b.ell((0.152, y, 0.694), (0.026, 0.027, 0.044), stiffness=3)  # magazine
        b.ell((0.150, y, 0.724), (0.022, 0.028, 0.012), stiffness=4)  # flap, folded over
    b.ell((0.140, 0, 0.788), (0.018, 0.05, 0.03), stiffness=3)  # admin pouch
    b.ell((0.02, 0.158, 0.70), (0.048, 0.032, 0.052), stiffness=3)  # left utility pouch
    b.ell((-0.02, -0.158, 0.70), (0.044, 0.03, 0.048), stiffness=3)  # right utility pouch
    return b

def strap(m, piece, center_at, z, pad, weights, height=0.016, mat="Strap"):
    """A band round `piece` at height `z`, standing `pad` off its surface."""
    fit = [m.fit((piece,), center_at(z), 2 * math.pi * j / 40) for j in range(40)]
    band = ring_band(m.bm, center_at, lambda a, zz: fit[round(a / (2 * math.pi) * 40) % 40] + pad,
                     z - height / 2, z + height / 2, rows=1, sides=40)
    m.weigh(band, weights)
    m.paint(band, mat)


def carrier(m, on_fatigues):
    """The plate carrier: front and back plates laid on the shirt, a cummerbund round
    the ribs, and shoulder straps over the trapezius."""
    center = lambda z: Vector((0.0, 0.0, z))  # noqa: E731
    zs = [0.668, 0.70, 0.74, 0.78, 0.812, 0.84]
    hug_patch(m, "fatigues", center, [math.radians(a) for a in range(-74, 75, 8)], zs, 0.018, 0.032, "Vest", on_fatigues)
    hug_patch(m, "fatigues", center, [math.radians(a) for a in range(106, 255, 8)], zs, 0.018, 0.032, "Vest", on_fatigues)
    for z in (0.706, 0.762):
        strap(m, "fatigues", center, z, 0.015, on_fatigues, height=0.048, mat="Vest")
    for s in (1, -1):
        y = s * 0.064
        pts = [Vector((0.098, y, 0.836)), Vector((0.07, y * 0.98, 0.872)), Vector((0.0, y, 0.892)),
               Vector((-0.07, y * 0.98, 0.872)), Vector((-0.098, y, 0.838))]
        verts = tube(m.bm, pts, [0.019, 0.021, 0.022, 0.021, 0.019], sides=8)
        m.weigh(verts, on_fatigues)
        m.paint(verts, "Vest")


def pads(m, sleeve_r, sleeve_l, leg_r, leg_l):
    """Hard pads as curved shells over the shoulders, elbows and knees, held on by
    straps round the limb."""
    for side, s, weights in (("R", -1, sleeve_r), ("L", 1, sleeve_l)):
        y = s * SHOULDER[0]
        center = lambda z, y=y: Vector((0.0, y, z))  # noqa: E731
        outer = [math.radians(s * a) for a in range(8, 173, 11)]
        hug_patch(m, f"sleeve.{side}", center, outer, [0.792, 0.816, 0.84, 0.862], 0.005, 0.014, "Pad", weights)
        strap(m, f"sleeve.{side}", center, 0.781, 0.004, weights, height=0.013)
        back = [math.radians(a) for a in range(128, 233, 11)]
        hug_patch(m, f"sleeve.{side}", center, back, [0.616, 0.638, 0.662, 0.684], 0.004, 0.012, "Pad", weights)
        strap(m, f"sleeve.{side}", center, 0.698, 0.004, weights, height=0.012)
        strap(m, f"sleeve.{side}", center, 0.602, 0.004, weights, height=0.012)
    for side, s, weights in (("R", -1, leg_r), ("L", 1, leg_l)):
        y = s * HIP[0]
        center = lambda z, y=y: Vector((0.0, y, z))  # noqa: E731
        front = [math.radians(a) for a in range(-66, 67, 11)]
        hug_patch(m, f"leg.{side}", center, front, [0.252, 0.274, 0.298, 0.322, 0.346], 0.005, 0.014, "Pad", weights)
        strap(m, f"leg.{side}", center, 0.356, 0.005, weights, height=0.013)
        strap(m, f"leg.{side}", center, 0.242, 0.005, weights, height=0.013)


def goggles(m, weights):
    """Tactical goggles: a rubber frame round one wide dark lens, held by a strap that
    runs over the ears under the helmet."""
    center = lambda z: Vector((0.0, 0.0, z))  # noqa: E731
    ang = [math.radians(a) for a in range(-64, 65, 8)]
    hug_patch(m, "mask", center, ang, [1.038, 1.06, 1.082, 1.1], 0.013, 0.017, "GoggleFrame", weights)
    ang = [math.radians(a) for a in range(-54, 55, 9)]
    hug_patch(m, "mask", center, ang, [1.046, 1.066, 1.088], 0.022, 0.004, "GoggleGlass", weights)
    strap(m, "mask", center, 1.066, 0.009, weights, height=0.017)


def helmet(m):
    """An ACH-style helmet: a domed shell fitted to the head, a cover band with a small
    brow lip at the rim, side rails, an NVG shroud and a chinstrap."""
    sides = 64
    center = lambda z: Vector((-0.012, 0.0, z))  # noqa: E731
    fit = [m.fit(("mask",), center(1.13), 2 * math.pi * j / sides) for j in range(sides)]

    def fitted(a, pad=0.0):
        return fit[round(a / (2 * math.pi) * sides) % sides] + pad

    rim, top = 1.096, 1.208

    def dome(a, z):
        t = max(0.0, min(1.0, (z - rim) / (top - rim)))
        return fitted(a, 0.016) * math.sqrt(max(0.0, 1.0 - t * t))

    # The shell: a band up from the rim, closed with a fan at the crown.
    rows = 16
    grid = []
    for i in range(rows + 1):
        z = rim + (top - rim) * i / rows
        grid.append([m.bm.verts.new(center(z) + Vector((math.cos(a), math.sin(a), 0.0)) * dome(a, z))
                     for a in (2 * math.pi * j / sides for j in range(sides))])
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(sides):
            m.bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    crown = m.bm.verts.new(center(top) + Vector((0, 0, 0.008)))
    for j in range(sides):
        m.bm.faces.new((grid[-1][j], grid[-1][(j + 1) % sides], crown))
    shell = [v for row in grid for v in row] + [crown]
    m.weigh(shell, "head")
    m.paint(shell, "Helmet")
    register(m, "helmet", shell)

    # Cover band at the rim, standing a little proud at the brow.
    band = ring_band(m.bm, center, lambda a, z: fitted(a, 0.013 + 0.012 * max(0.0, math.cos(a)) ** 2),
                     rim - 0.015, rim + 0.008, rows=3, sides=sides)
    m.part(band, "head", "HelmetBand")
    # Side rails, laid on the shell, and the NVG shroud on the front.
    for s in (1, -1):
        hug_patch(m, "helmet", center, [math.radians(s * a) for a in range(34, 148, 12)],
                  [1.118, 1.136, 1.152], 0.003, 0.007, "HelmetBand")
        loc, normal = m.hit("helmet", center(1.166), Vector((0.3, s, 0)))
        if loc is not None:
            m.part(box(m.bm, loc + normal * 0.004, (0.026, 0.011, 0.014)), "head", "Pad", smooth=False)
    loc, normal = m.hit("helmet", center(1.148), Vector((1, 0, 0)))
    if loc is not None:
        m.part(box(m.bm, loc + normal * 0.002, (0.014, 0.032, 0.024)), "head", "Pad", smooth=False)
        m.part(box(m.bm, loc + normal * 0.004 - Vector((0, 0, 0.022)), (0.012, 0.018, 0.016)), "head", "HelmetBand", smooth=False)
    # Chinstrap: from the rim, down the cheek, to a buckle under the ear.
    for s in (1, -1):
        top_pt, _ = m.hit("mask", center(1.08), Vector((0.35, s, 0)))
        low, _ = m.hit("mask", Vector((0.02, 0, 1.0)), Vector((0.75, s, 0.2)))
        if top_pt is None or low is None:
            continue
        path = [top_pt + Vector((0.004, s * 0.008, 0.006)),
                (top_pt * 0.45 + low * 0.55) + Vector((0.01, s * 0.006, 0)),
                low + Vector((0.008, s * 0.006, -0.006))]
        m.part(tube(m.bm, path, [0.0055, 0.0065, 0.0055], sides=8), "head", "Strap")
    buckle, _ = m.hit("mask", Vector((0.02, 0, 1.0)), Vector((0.75, -0.6, 0.2)))
    if buckle is not None:
        m.part(box(m.bm, buckle + Vector((0.006, 0, 0)), (0.012, 0.024, 0.018)), "head", "Buckle", smooth=False)

def vest_details(m, on_pouches, on_fatigues):
    """The flaps and buckles on the pouches, the MOLLE rows on the plates, and a radio
    with its antenna in the left utility pouch."""
    for y in (-0.062, 0.0, 0.062):
        verts = box(m.bm, (0.152, y, 0.742), (0.05, 0.052, 0.013))
        m.weigh(verts, on_pouches)
        m.paint(verts, "VestPouch", smooth=False)
        verts = box(m.bm, (0.168, y, 0.726), (0.012, 0.016, 0.019))
        m.weigh(verts, on_pouches)
        m.paint(verts, "Buckle", smooth=False)
    for z in (0.66, 0.755):
        hug_patch(m, "fatigues", lambda zz: Vector((0.0, 0.0, zz)),
                  [math.radians(a) for a in range(-70, 71, 10)], [z - 0.005, z + 0.005],
                  0.024, 0.008, "Strap", on_fatigues)
    m.part(tube(m.bm, [(0.01, 0.162, 0.742), (-0.005, 0.176, 0.87)], [0.004, 0.003], sides=6), "spine", "Strap")
    m.part(box(m.bm, (0.01, 0.162, 0.752), (0.03, 0.024, 0.02)), "spine", "Buckle", smooth=False)


def belt(m, on_fatigues):
    """A trouser belt with a buckle, under the carrier."""
    strap(m, "fatigues", lambda z: Vector((0.0, 0.0, z)), 0.585, 0.008, on_fatigues, height=0.032)
    loc, normal = m.hit("fatigues", (0.3, 0, 0.585), (-1, 0, 0))
    if loc is not None:
        m.part(box(m.bm, loc + normal * 0.012, (0.016, 0.05, 0.036)), "hips", "Buckle", smooth=False)


def leg_gear(m, leg_r, leg_l):
    """A drop-leg holster on the near (right) thigh, a knife on the far one."""
    y = -HIP[0]
    verts = box(m.bm, (0.012, y - 0.082, 0.40), (0.062, 0.04, 0.1))
    m.weigh(verts, leg_r)
    m.paint(verts, "Strap", smooth=False)
    verts = box(m.bm, (0.014, y - 0.088, 0.436), (0.05, 0.026, 0.03))
    m.weigh(verts, leg_r)
    m.paint(verts, "Polymer", smooth=False)
    grip = tube(m.bm, [(0.0, y - 0.09, 0.452), (0.01, y - 0.106, 0.492)], [0.014, 0.012], sides=8)
    m.weigh(grip, leg_r)
    m.paint(grip, "Polymer")
    center = lambda z, yy=y: Vector((0.0, yy, z))  # noqa: E731
    strap(m, "leg.R", center, 0.465, 0.007, leg_r, height=0.016)
    strap(m, "leg.R", center, 0.352, 0.007, leg_r, height=0.016)
    # Knife on the far thigh.
    y = HIP[0]
    verts = box(m.bm, (0.0, y + 0.082, 0.40), (0.048, 0.032, 0.115))
    m.weigh(verts, leg_l)
    m.paint(verts, "Strap", smooth=False)
    verts = slab(m.bm, (0.004, y + 0.086, 0.452), (0.024, y + 0.09, 0.515), 0.026, 0.03, 0.03, 0.026)
    m.weigh(verts, leg_l)
    m.paint(verts, "Polymer", smooth=False)
    verts = box(m.bm, (0.028, y + 0.09, 0.518), (0.02, 0.036, 0.014))
    m.weigh(verts, leg_l)
    m.paint(verts, "Buckle", smooth=False)
    strap(m, "leg.L", lambda z: Vector((0.0, HIP[0], z)), 0.455, 0.007, leg_l, height=0.016)


def boot_details(m, boot_r, boot_l):
    """Soles, a heel block and laces on the boots."""
    for s, weights in ((-1, boot_r), (1, boot_l)):
        y = s * HIP[0]
        sole = slab(m.bm, (-0.062, y, 0.012), (0.152, y, 0.011), 0.1, 0.024, 0.086, 0.018)
        m.weigh(sole, weights)
        m.paint(sole, "Sole", smooth=False)
        heel = slab(m.bm, (-0.066, y, 0.031), (-0.008, y, 0.029), 0.096, 0.038, 0.1, 0.034)
        m.weigh(heel, weights)
        m.paint(heel, "Sole", smooth=False)
        for i in range(4):
            z = 0.085 + i * 0.021
            lace = tube(m.bm, [(0.075, y - 0.03, z), (0.083, y, z + 0.004), (0.075, y + 0.03, z)],
                        [0.0035, 0.0035, 0.0035], sides=6)
            m.weigh(lace, weights)
            m.paint(lace, "Lace")


def patches(m, on_sleeve):
    """The player-colored markings on the near sleeve (the `Body` material)."""
    y = -SHOULDER[0]
    center = lambda z, yy=y: Vector((0.0, yy, z))  # noqa: E731
    strap(m, "sleeve.R", center, 0.706, 0.006, on_sleeve, height=0.024, mat="Body")
    hug_patch(m, "sleeve.R", center, [math.radians(a) for a in range(-116, -63, 9)], [0.762, 0.791],
              0.005, 0.004, "Body", on_sleeve)


def seams(m, on_sleeve, on_leg):
    """Stitching seams down the near sleeve and leg, so the cloth looks sewn."""
    y = -SHOULDER[0]
    line = [Vector((0.006, y - 0.045, z)) for z in (0.79, 0.70, 0.60, 0.5)]
    verts = tube(m.bm, line, [0.0022] * len(line), sides=6)
    m.weigh(verts, on_sleeve)
    m.paint(verts, "Strap")
    y = -HIP[0]
    line = [Vector((0.006, y - 0.05, z)) for z in (0.47, 0.40, 0.30, 0.20)]
    verts = tube(m.bm, line, [0.0022] * len(line), sides=6)
    m.weigh(verts, on_leg)
    m.paint(verts, "Strap")

def rifle(m):
    """The rifle as a multi-part prop along +X from the grip: a polymer stock, a railed
    receiver, a pistol grip and trigger, a curved magazine, a vented handguard, a front
    sight, a muzzle device and a steel bayonet under the barrel, plus a sling."""
    bm = m.bm

    def at(x, y=0.0, z=0.0):
        return AXIS + Vector((x, y, z))

    def rod(x0, x1, r, mat, sides=12):
        m.part(tube(bm, [at(x0), at(x1)], [r, r], sides=sides), "rifle", mat)

    def bar(x0, x1, y0, y1, z0, z1, mat, taper=1.0):
        """A rectangular part from x0 to x1, `taper` shrinking the far end."""
        zc = (z0 + z1) / 2
        w, h = y1 - y0, z1 - z0
        m.part(slab(bm, at(x0, 0, zc), at(x1, 0, zc), w, h, w * taper, h * taper), "rifle", mat, smooth=False)

    # Stock: butt pad, the body of the stock, and a raised cheek rest.
    bar(-0.306, -0.292, -0.022, 0.022, -0.058, 0.03, "Polymer")
    bar(-0.292, -0.15, -0.02, 0.02, -0.05, 0.026, "Polymer")
    bar(-0.15, -0.028, -0.019, 0.019, -0.038, 0.03, "Polymer")
    bar(-0.27, -0.16, -0.017, 0.017, 0.026, 0.044, "Polymer")
    bar(-0.24, -0.175, -0.024, 0.024, -0.056, -0.046, "Strap")  # sling swivel band
    # Receiver, rail, teeth and the rear sight.
    bar(-0.028, 0.135, -0.024, 0.024, -0.032, 0.03, "Gunmetal")
    bar(-0.02, 0.128, -0.013, 0.013, 0.03, 0.044, "Gunmetal")
    for i in range(6):
        x = -0.004 + i * 0.023
        bar(x, x + 0.012, -0.014, 0.014, 0.044, 0.05, "Gunmetal")
    bar(-0.026, 0.004, -0.012, 0.012, 0.044, 0.062, "Gunmetal")
    bar(-0.028, -0.004, -0.026, 0.026, 0.002, 0.022, "Gunmetal")  # charging handle
    # Pistol grip, trigger and its guard.
    m.part(slab(bm, at(-0.004, 0, -0.026), at(-0.05, 0, -0.112), 0.03, 0.04, 0.028, 0.038, up=Vector((1, 0, 0))),
           "rifle", "Polymer", smooth=False)
    bar(0.006, 0.052, -0.005, 0.005, -0.05, -0.042, "Gunmetal")
    bar(0.006, 0.014, -0.005, 0.005, -0.048, -0.03, "Gunmetal")
    bar(0.044, 0.052, -0.005, 0.005, -0.048, -0.03, "Gunmetal")
    # Curved magazine.
    for x0, z0, x1, z1, w0, w1 in ((0.028, -0.032, 0.05, -0.102, 0.038, 0.036),
                                   (0.05, -0.102, 0.076, -0.168, 0.036, 0.032)):
        m.part(slab(bm, at(x0, 0, z0), at(x1, 0, z1), w0, 0.032, w1, 0.03, up=Vector((1, 0, 0))),
               "rifle", "Gunmetal", smooth=False)
    # Handguard with vents, the gas block, the front sight and the muzzle device.
    bar(0.132, 0.302, -0.027, 0.027, -0.028, 0.03, "Polymer")
    for i in range(5):
        x = 0.155 + i * 0.03
        for s in (1, -1):
            m.part(box(bm, at(x, s * 0.0275, 0.002), (0.018, 0.006, 0.014)), "rifle", "Gunmetal", smooth=False)
    bar(0.286, 0.316, -0.018, 0.018, -0.02, 0.026, "Gunmetal")
    bar(0.29, 0.306, -0.007, 0.007, 0.026, 0.052, "Gunmetal")
    rod(0.302, 0.5, 0.0125, "Barrel", sides=14)
    rod(0.5, 0.552, 0.017, "Gunmetal", sides=14)
    # Bayonet: a socket at the muzzle, then a flattened steel blade.
    rod(0.552, 0.578, 0.015, "Gunmetal")
    base, length, width, thick, steps = 0.578, 0.185, 0.026, 0.008, 12
    rings = []
    for i in range(steps + 1):
        t = i / steps
        x = base + length * t
        w, th = width * (1 - t), thick * (1 - t)
        if i == steps:
            rings.append([bm.verts.new(at(x + 0.014))])
        else:
            rings.append([bm.verts.new(at(x, w * a, th * b)) for a, b in ((0, 0.5), (-0.5, 0.15), (0, -0.5), (0.5, 0.15))])
    faces = []
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(4):
            quad = (r0[j], r0[(j + 1) % 4], r1[0]) if len(r1) == 1 else (r0[j], r0[(j + 1) % 4], r1[(j + 1) % 4], r1[j])
            faces.append((bm.faces.new(quad), j))
    faces.append((bm.faces.new(list(reversed(rings[0]))), 0))
    m.weigh([v for r in rings for v in r], "rifle")
    for f, _ in faces:
        f.material_index = MAT["Steel"]
        f.smooth = False
    # Sling, hanging on the near side.
    sling = [at(-0.278, -0.012, -0.048), at(-0.17, -0.02, -0.118), at(0.0, -0.022, -0.15),
             at(0.19, -0.02, -0.118), at(0.27, -0.012, -0.04)]
    m.part(tube(bm, sling, [0.006, 0.007, 0.008, 0.007, 0.006], sides=6), "rifle", "Strap")


def soldier_mesh():
    m = Model()
    mask = m.blob("mask", balaclava_blob(), 0.3, "Balaclava", "head")
    fatigues = m.blob("fatigues", fatigues_blob(), 0.22, "Camo", by_distance("hips", "spine"))
    pouches = m.blob("pouches", pouches_blob(), 0.3, "VestPouch", by_distance("hips", "spine", sharpness=6))
    sleeves, legs, boots = {}, {}, {}
    for side, s in (("L", 1), ("R", -1)):
        sleeves[side] = m.blob(f"sleeve.{side}", sleeve_blob(s), 0.25, "Camo",
                               by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", hand_blob(s), 0.35, "Glove", f"forearm.{side}")
        legs[side] = m.blob(f"leg.{side}", leg_blob(s), 0.22, "Camo",
                            by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        boots[side] = m.blob(f"boot.{side}", boot_blob(s), 0.35, "Boot",
                             by_distance(f"foot.{side}", f"shin.{side}", sharpness=9))
    goggles(m, "head")
    helmet(m)
    carrier(m, m.weights_near(fatigues))
    belt(m, m.weights_near(fatigues))
    vest_details(m, m.weights_near(pouches), m.weights_near(fatigues))
    pads(m, m.weights_near(sleeves["R"]), m.weights_near(sleeves["L"]),
         m.weights_near(legs["R"]), m.weights_near(legs["L"]))
    leg_gear(m, m.weights_near(legs["R"]), m.weights_near(legs["L"]))
    boot_details(m, m.weights_near(boots["R"]), m.weights_near(boots["L"]))
    patches(m, m.weights_near(sleeves["R"]))
    seams(m, m.weights_near(sleeves["R"]), m.weights_near(legs["R"]))
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
