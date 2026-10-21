"""Builds the soldier: a heavy infantryman in a combat helmet, tactical goggles and
ear-pro, his face covered by a balaclava, a plate carrier with MOLLE webbing and sewn
pouches over his fatigues, pads on his shoulders, elbows and knees, with a scoped
carbine that ends in a bayonet. Bakes ambient occlusion into the vertex colors and the
rest position into the UVs for the game's shaders. Then his armature and one action per
pose name the sim reports (`Fighter::anim()`), the ledge getups included. Saves `soldier.blend` next to this script, exports
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
import random
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
    "Buckle": ((0.045, 0.045, 0.048, 1), 0.72, 0.0),
    "Pad": ((0.095, 0.095, 0.09, 1), 0.6, 0.0),
    "Boot": ((0.17, 0.125, 0.085, 1), 0.55, 0.0),
    "Sole": ((0.045, 0.045, 0.045, 1), 0.85, 0.0),
    "Lace": ((0.12, 0.10, 0.075, 1), 0.9, 0.0),
    "Thread": ((0.26, 0.235, 0.17, 1), 0.9, 0.0),
    "Glove": ((0.095, 0.09, 0.085, 1), 0.8, 0.0),
    "Balaclava": ((0.055, 0.055, 0.062, 1), 0.95, 0.0),
    "Helmet": ((0.17, 0.18, 0.13, 1), 0.8, 0.0),
    "HelmetBand": ((0.10, 0.11, 0.08, 1), 0.85, 0.0),
    "GoggleFrame": ((0.035, 0.035, 0.04, 1), 0.55, 0.0),
    "GoggleGlass": ((0.01, 0.011, 0.014, 1), 0.06, 0.0),
    "Steel": ((0.52, 0.54, 0.57, 1), 0.38, 0.6),
    "Gunmetal": ((0.05, 0.052, 0.056, 1), 0.55, 0.4),
    "Barrel": ((0.04, 0.04, 0.042, 1), 0.6, 0.5),
    "Polymer": ((0.07, 0.072, 0.07, 1), 0.62, 0.0),
    "Grenade": ((0.26, 0.30, 0.16, 1), 0.55, 0.0),
}
MAT = {name: i for i, name in enumerate(MATERIALS)}


class Model(chef.Model):
    """The chef's `Model`, on this skeleton and these materials. Every vertex is also
    tagged with the `group` being built (the body, each arm, the rifle), which limits
    what can shadow it when the ambient occlusion is baked (see `bake_occlusion`)."""

    GROUPS = ("body", "arm.R", "arm.L", "rifle")

    def __init__(self):
        super().__init__()
        self.group_layer = self.bm.verts.layers.int.new("group")
        self.group = "body"

    def weigh(self, verts, weights):
        g = self.GROUPS.index(self.group)
        for v in verts:
            ws = {weights: 1.0} if isinstance(weights, str) else weights(v.co)
            for bone, w in ws.items():
                v[self.deform][BONE_NAMES.index(bone)] = w
            v[self.group_layer] = g

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


def chamfered(bm, build, offset, segments=1):
    """Hard gear with its edges bevelled: `build(tmp_bm)` makes the part in a scratch
    bmesh, every edge gets an `offset` bevel, and the result is copied into `bm`. Real
    machined and moulded parts never have knife edges, and the bevel catches the light."""
    tmp = bmesh.new()
    build(tmp)
    bmesh.ops.remove_doubles(tmp, verts=tmp.verts[:], dist=1e-6)
    bmesh.ops.bevel(tmp, geom=tmp.edges[:], offset=offset, offset_type="OFFSET",
                    segments=segments, profile=0.5, affect="EDGES", clamp_overlap=True)
    index = {v: bm.verts.new(v.co) for v in tmp.verts}
    for f in tmp.faces:
        try:
            bm.faces.new([index[v] for v in f.verts])
        except ValueError:
            pass
    tmp.free()
    return list(index.values())


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
    b.ell((0.024, 0, 1.028), (0.079, 0.077, 0.081))  # face and jaw
    b.ell((0.044, 0, 0.981), (0.045, 0.052, 0.036), stiffness=3)  # chin, masked
    b.cap((-0.014, 0, 0.85), (0.0, 0, 1.0), 0.066)  # neck, down into the collar
    b.ell((0.0, 0, 0.932), (0.07, 0.072, 0.03), stiffness=3)  # gaiter bunched up
    b.ell((-0.004, 0, 0.905), (0.074, 0.078, 0.026), stiffness=3)
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


def strap(m, piece, center_at, z, pad, weights, height=0.016, mat="Strap"):
    """A band round `piece` at height `z`, standing `pad` off its surface."""
    fit = [m.fit((piece,), center_at(z), 2 * math.pi * j / 40) for j in range(40)]
    band = ring_band(m.bm, center_at, lambda a, zz: fit[round(a / (2 * math.pi) * 40) % 40] + pad,
                     z - height / 2, z + height / 2, rows=1, sides=40)
    m.weigh(band, weights)
    m.paint(band, mat)


def ribbon(bm, points, width, thickness, ups):
    """Flat webbing along `points`: `width` across, `thickness` along `ups` (one normal
    per point, or one for all), for straps and slings that are bands, not cords."""
    pts = [Vector(p) for p in points]
    ups = [Vector(u) for u in ups] if isinstance(ups, list) else [Vector(ups)] * len(pts)
    rings = []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        n = (ups[i] - t * ups[i].dot(t)).normalized()
        w = t.cross(n)
        rings.append([bm.verts.new(p + w * (sx * width / 2) + n * (sy * thickness / 2))
                      for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))])
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(4):
            bm.faces.new((r0[j], r0[(j + 1) % 4], r1[(j + 1) % 4], r1[j]))
    bm.faces.new(tuple(reversed(rings[0])))
    bm.faces.new(tuple(rings[-1]))
    return [v for r in rings for v in r]


def close_shell(m, outer, inner):
    """Faces for a plate: grid `outer` over grid `inner` (rows of verts), walled round."""
    nz, na = len(outer), len(outer[0])
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
    return [v for row in outer + inner for v in row]


def panel(m, piece, side, ys, z_lo, z_hi, rows, lift, thickness, mat, weights,
          flatten=0.0, curve=0.0, round_edge=0.0, name=None):
    """A plate laid on the front (`side` +1) or back (-1) of `piece`, cast straight in
    along X over `ys` x `rows` (each column from `z_lo(y)` to `z_hi(y)`). `flatten` pulls
    it toward a flat sheet bowed by `curve` (a ballistic plate holds the cloth flat rather
    than following it), `round_edge` rolls its border back so it has no knife edge."""
    grid = []
    for i in range(rows + 1):
        row = []
        for y in ys:
            z = z_lo(y) + (z_hi(y) - z_lo(y)) * i / rows
            loc, _ = m.hit(piece, Vector((side * 0.6, y, z)), Vector((-side, 0, 0)))
            row.append((y, z, side * loc.x if loc is not None else 0.1))
        grid.append(row)
    peak = max(d for row in grid for _, _, d in row)
    outer, inner = [], []
    for i, row in enumerate(grid):
        ro, ri = [], []
        for j, (y, z, depth) in enumerate(row):
            d = max(depth + 0.003, depth * (1 - flatten) + (peak - curve * y * y) * flatten) + lift
            border = i in (0, rows) or j in (0, len(ys) - 1)
            ro.append(m.bm.verts.new((side * (d + thickness * (1 - round_edge * border)), y, z)))
            ri.append(m.bm.verts.new((side * d, y, z)))
        outer.append(ro)
        inner.append(ri)
    verts = close_shell(m, outer, inner)
    m.weigh(verts, weights)
    m.paint(verts, mat)
    if name:
        register(m, name, [v for row in outer for v in row])
    return verts


def front_of(m, piece, y, z, side=1):
    """How far out (along X, signed by `side`) `piece` is at (y, z)."""
    loc, _ = m.hit(piece, Vector((side * 0.6, y, z)), Vector((-side, 0, 0)))
    return loc.x if loc is not None else side * 0.14


def soft_box(m, center, size, weights, mat, bevel=0.005, segments=2):
    """A sewn pouch or bag: a box with rolled edges."""
    verts = chamfered(m.bm, lambda bm: box(bm, center, size), bevel, segments)
    m.weigh(verts, weights)
    m.paint(verts, mat)
    return verts


def stitches(m, corners, lift_dir, weights, radius=0.0011):
    """A seam of thread round a pouch face: a closed line through `corners`."""
    pts = [Vector(c) + Vector(lift_dir) * radius for c in corners]
    pts.append(pts[0])
    dense = []
    for a, b in zip(pts, pts[1:]):
        dense += [a.lerp(b, t / 4) for t in range(4)]
    dense.append(pts[0])
    verts = tube(m.bm, dense, [radius] * len(dense), sides=4, caps=False)
    m.weigh(verts, weights)
    m.paint(verts, "Thread")


def molle_rows(m, piece, side, y0, y1, zs, weights, lift=0.0015):
    """MOLLE webbing: rows of 1-inch tape stitched to `piece` with bar tacks every
    1.5 inches (scaled to his 1.2 m), across y0..y1 at each of `zs`."""
    ys = [y0 + (y1 - y0) * k / 10 for k in range(11)]
    for z in zs:
        panel(m, piece, side, ys, lambda y, z=z: z - 0.0085, lambda y, z=z: z + 0.0085, 1,
              lift, 0.0022, "Strap", weights)
        y = y0 + 0.004
        while y < y1 - 0.002:
            x = front_of(m, piece, y, z, side) + side * (lift + 0.0026)
            tack = box(m.bm, (x, y, z), (0.0016, 0.0024, 0.019))
            m.weigh(tack, weights)
            m.paint(tack, "Strap", smooth=False)
            y += 0.0265


def carrier(m, on_fatigues):
    """A plate carrier: rigid front and back plate bags (the front with shooter's cuts at
    the top corners), a cummerbund round the ribs, padded shoulder straps, MOLLE webbing
    on everything, and the pouches hung on it — three magazine pouches with flaps, an
    admin pouch, a radio and a medical pouch on the flanks and a hydration carrier on
    the back. Every edge of the pouches is sewn (`stitches`)."""
    ys = [-0.118 + 0.236 * k / 26 for k in range(27)]
    cut = lambda y: 0.868 - max(0.0, abs(y) - 0.066) * 1.25  # noqa: E731
    panel(m, "fatigues", 1, ys, lambda y: 0.636, cut, 16, 0.008, 0.032, "Vest", on_fatigues,
          flatten=0.65, curve=0.9, round_edge=0.5, name="plate.front")
    panel(m, "fatigues", -1, ys, lambda y: 0.64, lambda y: 0.872, 16, 0.008, 0.03, "Vest", on_fatigues,
          flatten=0.7, curve=0.9, round_edge=0.5, name="plate.back")
    center = lambda z: Vector((0.0, 0.0, z))  # noqa: E731
    zs = [0.646 + 0.12 * k / 5 for k in range(6)]
    for s in (1, -1):
        hug_patch(m, "fatigues", center, [math.radians(s * a) for a in range(40, 141, 7)], zs, 0.011, 0.011, "Vest", on_fatigues)
        molle_rows_side(m, s, on_fatigues)
    molle_rows(m, "plate.front", 1, -0.106, 0.106, (0.79, 0.816, 0.842), on_fatigues)
    molle_rows(m, "plate.back", -1, -0.104, 0.104, (0.86,), on_fatigues)
    # Padded shoulder straps, front plate to back plate over the trapezius.
    for s in (1, -1):
        y = s * 0.074
        pts = [Vector((0.118, y, 0.852)), Vector((0.096, y, 0.886)), Vector((0.04, y * 1.02, 0.903)),
               Vector((-0.03, y * 1.02, 0.9)), Vector((-0.086, y, 0.884)), Vector((-0.112, y, 0.858))]
        ups = [Vector((1, 0, 0.5)), Vector((0.8, 0, 1)), Vector((0.2, 0, 1)), Vector((-0.2, 0, 1)),
               Vector((-0.8, 0, 1)), Vector((-1, 0, 0.5))]
        verts = ribbon(m.bm, pts, 0.046, 0.014, ups)
        m.weigh(verts, on_fatigues)
        m.paint(verts, "Vest")
    # Drag handle at the top of the back plate.
    top = front_of(m, "plate.back", 0.0, 0.862, -1)
    verts = tube(m.bm, [(top - 0.004, -0.035, 0.862), (top - 0.016, -0.03, 0.882), (top - 0.018, 0.0, 0.888),
                        (top - 0.016, 0.03, 0.882), (top - 0.004, 0.035, 0.862)], [0.0045] * 5, sides=8)
    m.weigh(verts, on_fatigues)
    m.paint(verts, "Strap")


def molle_rows_side(m, s, weights):
    """Webbing rows on one side of the cummerbund."""
    center = lambda z: Vector((0.0, 0.0, z))  # noqa: E731
    for z in (0.666, 0.692, 0.718, 0.744):
        hug_patch(m, "fatigues", center, [math.radians(s * a) for a in range(46, 136, 6)],
                  [z - 0.0085, z + 0.0085], 0.0235, 0.0022, "Strap", weights)


def mag_pouch(m, y, weights):
    """A rifle magazine pouch on the front plate: the sewn box, its flap folded over the
    top with a lip down the front, a pull tab, and the magazine's base peeking out."""
    w, h, d, z0 = 0.05, 0.088, 0.032, 0.652
    x = front_of(m, "plate.front", y, z0 + h / 2) - 0.002
    soft_box(m, (x + d / 2, y, z0 + h / 2), (d, w, h), weights, "VestPouch")
    top = z0 + h
    soft_box(m, (x + d / 2 + 0.002, y, top + 0.004), (d + 0.008, w + 0.004, 0.011), weights, "VestPouch", 0.003)
    soft_box(m, (x + d + 0.005, y, top - 0.012), (0.006, w * 0.86, 0.034), weights, "VestPouch", 0.0025)
    tab = box(m.bm, (x + d + 0.0085, y, top - 0.032), (0.003, 0.014, 0.014))
    m.weigh(tab, weights)
    m.paint(tab, "Strap", smooth=False)
    front = x + d + 0.0004
    stitches(m, [(front, y - w / 2 + 0.005, z0 + 0.005), (front, y + w / 2 - 0.005, z0 + 0.005),
                 (front, y + w / 2 - 0.005, top - 0.03), (front, y - w / 2 + 0.005, top - 0.03)], (1, 0, 0), weights)


def pouches(m, on_fatigues):
    for y in (-0.058, 0.0, 0.058):
        mag_pouch(m, y, on_fatigues)
    # Admin pouch high on the chest, zipped along the top, with a loop panel on its face.
    x = front_of(m, "plate.front", 0.0, 0.81) - 0.002
    soft_box(m, (x + 0.013, 0.0, 0.812), (0.026, 0.096, 0.056), on_fatigues, "VestPouch", 0.006)
    verts = tube(m.bm, [(x + 0.022, -0.044, 0.839), (x + 0.022, 0.044, 0.839)], [0.0018, 0.0018], sides=6)
    m.weigh(verts, on_fatigues)
    m.paint(verts, "Strap")
    panel(m, "plate.front", 1, [-0.032 + 0.064 * k / 6 for k in range(7)], lambda y: 0.796, lambda y: 0.826, 2,
          0.026, 0.0018, "Strap", on_fatigues)
    stitches(m, [(x + 0.0262, -0.044, 0.789), (x + 0.0262, 0.044, 0.789), (x + 0.0262, 0.044, 0.835),
                 (x + 0.0262, -0.044, 0.835)], (1, 0, 0), on_fatigues)
    # Radio pouch on the left flank, the radio's top and antenna standing out of it.
    for s, kind in ((1, "radio"), (-1, "medical")):
        loc, normal = m.hit("fatigues", Vector((0.0, s * 0.6, 0.7)), Vector((0, -s, 0)))
        side_y = loc.y + s * 0.024
        if kind == "radio":
            soft_box(m, (0.0, side_y + s * 0.021, 0.70), (0.058, 0.042, 0.088), on_fatigues, "VestPouch", 0.006)
            soft_box(m, (0.0, side_y + s * 0.021, 0.756), (0.044, 0.03, 0.03), on_fatigues, "Polymer", 0.004, 1)
            m.part(tube(m.bm, [(0.008, side_y + s * 0.021, 0.77), (0.0, side_y + s * 0.02, 0.81),
                               (-0.02, side_y + s * 0.015, 0.88)], [0.0042, 0.0032, 0.0026], sides=8), "spine", "Polymer")
            stitches(m, [(-0.024, side_y + s * 0.0425, 0.662), (0.024, side_y + s * 0.0425, 0.662),
                         (0.024, side_y + s * 0.0425, 0.738), (-0.024, side_y + s * 0.0425, 0.738)], (0, s, 0), on_fatigues)
        else:
            soft_box(m, (0.004, side_y + s * 0.02, 0.704), (0.07, 0.04, 0.066), on_fatigues, "VestPouch", 0.008)
            # A red cross-less medic tab and the pull handle on top.
            m.part(tube(m.bm, [(-0.02, side_y + s * 0.02, 0.737), (0.004, side_y + s * 0.022, 0.75),
                               (0.028, side_y + s * 0.02, 0.737)], [0.003] * 3, sides=6), "spine", "Strap")
            stitches(m, [(-0.028, side_y + s * 0.0405, 0.676), (0.036, side_y + s * 0.0405, 0.676),
                         (0.036, side_y + s * 0.0405, 0.732), (-0.028, side_y + s * 0.0405, 0.732)], (0, s, 0), on_fatigues)
    # Hydration carrier on the back plate.
    x = front_of(m, "plate.back", 0.0, 0.76, -1) + 0.002
    soft_box(m, (x - 0.017, 0.0, 0.752), (0.034, 0.17, 0.18), on_fatigues, "VestPouch", 0.012, 3)
    stitches(m, [(x - 0.0342, -0.078, 0.668), (x - 0.0342, 0.078, 0.668), (x - 0.0342, 0.078, 0.836),
                 (x - 0.0342, -0.078, 0.836)], (-1, 0, 0), on_fatigues)


def arm_pads(m, side, weights):
    """Hard pads as curved shells over the shoulder and elbow, held on by straps."""
    for s in ((-1,) if side == "R" else (1,)):
        y = s * SHOULDER[0]
        center = lambda z, y=y: Vector((0.0, y, z))  # noqa: E731
        outer = [math.radians(s * a) for a in range(8, 173, 11)]
        hug_patch(m, f"sleeve.{side}", center, outer, [0.792, 0.816, 0.84, 0.862], 0.005, 0.014, "Pad", weights)
        strap(m, f"sleeve.{side}", center, 0.781, 0.004, weights, height=0.013)
        back = [math.radians(a) for a in range(128, 233, 11)]
        hug_patch(m, f"sleeve.{side}", center, back, [0.616, 0.638, 0.662, 0.684], 0.004, 0.012, "Pad", weights)
        strap(m, f"sleeve.{side}", center, 0.698, 0.004, weights, height=0.012)
        strap(m, f"sleeve.{side}", center, 0.602, 0.004, weights, height=0.012)


def leg_pads(m, side, weights):
    """A knee pad: a hard cap over the knee, strapped above and below."""
    for s in ((-1,) if side == "R" else (1,)):
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

def patches(m, on_sleeve):
    """The player-colored markings on the near sleeve (the `Body` material)."""
    y = -SHOULDER[0]
    center = lambda z, yy=y: Vector((0.0, yy, z))  # noqa: E731
    strap(m, "sleeve.R", center, 0.706, 0.006, on_sleeve, height=0.024, mat="Body")
    hug_patch(m, "sleeve.R", center, [math.radians(a) for a in range(-116, -63, 9)], [0.762, 0.791],
              0.005, 0.004, "Body", on_sleeve)



def belt(m, on_fatigues):
    """A padded battle belt over the trouser belt, closed with a cobra buckle."""
    center = lambda z: Vector((0.0, 0.0, z))  # noqa: E731
    strap(m, "fatigues", center, 0.582, 0.006, on_fatigues, height=0.03)
    strap(m, "fatigues", center, 0.578, 0.014, on_fatigues, height=0.038, mat="Vest")
    x = front_of(m, "fatigues", 0.0, 0.578) + 0.018
    for y0, w in ((-0.016, 0.026), (0.014, 0.024)):
        verts = chamfered(m.bm, lambda bm, y0=y0, w=w: box(bm, (x, y0, 0.578), (0.009, w, 0.034)), 0.002)
        m.part(verts, "hips", "Buckle")


def leg_gear(m, leg_r, leg_l):
    """A drop-leg holster on the near (right) thigh — a platform strapped to the leg, a
    moulded holster with the pistol's grip and slide showing — and a knife on the far one."""
    y = -HIP[0]
    verts = chamfered(m.bm, lambda bm: box(bm, (0.012, y - 0.08, 0.405), (0.07, 0.012, 0.11)), 0.004, 2)
    m.weigh(verts, leg_r)
    m.paint(verts, "Strap")
    verts = chamfered(m.bm, lambda bm: box(bm, (0.016, y - 0.094, 0.405), (0.058, 0.03, 0.094)), 0.006, 2)
    m.weigh(verts, leg_r)
    m.paint(verts, "Polymer")
    verts = chamfered(m.bm, lambda bm: slab(bm, (-0.004, y - 0.094, 0.448), (-0.018, y - 0.096, 0.49),
                                              0.024, 0.032, 0.022, 0.03, up=Vector((1, 0, 0))), 0.004, 1)
    m.weigh(verts, leg_r)
    m.paint(verts, "Polymer")
    verts = chamfered(m.bm, lambda bm: box(bm, (0.03, y - 0.096, 0.462), (0.05, 0.018, 0.026)), 0.003)
    m.weigh(verts, leg_r)
    m.paint(verts, "Polymer")
    center = lambda z, yy=y: Vector((0.0, yy, z))  # noqa: E731
    for z in (0.468, 0.352):
        strap(m, "leg.R", center, z, 0.006, leg_r, height=0.016)
        verts = chamfered(m.bm, lambda bm, z=z: box(bm, (0.05, y - 0.07, z), (0.012, 0.024, 0.02)), 0.002)
        m.weigh(verts, leg_r)
        m.paint(verts, "Buckle")
    # Knife on the far thigh: a sheath with a strap over the guard and the grip above.
    y = HIP[0]
    verts = chamfered(m.bm, lambda bm: box(bm, (0.0, y + 0.082, 0.40), (0.044, 0.026, 0.115)), 0.005, 2)
    m.weigh(verts, leg_l)
    m.paint(verts, "Strap")
    verts = chamfered(m.bm, lambda bm: slab(bm, (0.004, y + 0.084, 0.458), (0.016, y + 0.086, 0.52),
                                              0.022, 0.026, 0.024, 0.022), 0.004, 1)
    m.weigh(verts, leg_l)
    m.paint(verts, "Polymer")
    verts = chamfered(m.bm, lambda bm: box(bm, (0.004, y + 0.084, 0.456), (0.042, 0.03, 0.008)), 0.002)
    m.weigh(verts, leg_l)
    m.paint(verts, "Polymer")
    strap(m, "leg.L", lambda z: Vector((0.0, HIP[0], z)), 0.455, 0.006, leg_l, height=0.016)


def boot_details(m, boot_r, boot_l):
    """Lugged soles and heels, a stitched welt, a tongue under laces criss-crossed through
    eyelets, and a pull tab at the heel."""
    for side, s, weights in (("R", -1, boot_r), ("L", 1, boot_l)):
        y = s * HIP[0]
        piece = f"boot.{side}"
        verts = chamfered(m.bm, lambda bm: slab(bm, (-0.066, y, 0.017), (0.158, y, 0.016), 0.102, 0.022, 0.088, 0.018), 0.004)
        m.weigh(verts, weights)
        m.paint(verts, "Sole")
        verts = chamfered(m.bm, lambda bm: slab(bm, (-0.07, y, 0.034), (-0.01, y, 0.032), 0.098, 0.03, 0.1, 0.028), 0.004)
        m.weigh(verts, weights)
        m.paint(verts, "Sole")
        # Tread: staggered lugs under the sole and heel.
        for i in range(11):
            x = -0.058 + i * 0.0205
            for k, yo in enumerate((-0.03, -0.01, 0.01, 0.03)):
                if (i + k) % 2 or (x > 0.13 and abs(yo) > 0.02):
                    continue
                lug = box(m.bm, (x, y + yo, 0.0035), (0.014, 0.017, 0.008))
                m.weigh(lug, weights)
                m.paint(lug, "Sole", smooth=False)
        strap(m, piece, lambda z: Vector((0.03, y, z)), 0.036, 0.0008, weights, height=0.003, mat="Thread")
        # Tongue and lacing.
        panel(m, piece, 1, [y - 0.018 + 0.036 * k / 6 for k in range(7)], lambda yy: 0.074, lambda yy: 0.176, 6,
              0.0, 0.004, "Boot", weights, round_edge=0.6)
        # The lacing runs up the instep and the front of the shaft: cast square to it.
        rows = []
        for k in range(6):
            t = k / 5
            on_line = Vector((0.098 - 0.05 * t, 0.0, 0.088 + 0.084 * t))
            out = Vector((0.85 - 0.25 * t, 0.0, 0.52 - 0.42 * t)).normalized()
            row = []
            for yo in (-0.02, 0.02):
                start = on_line + Vector((0, y + yo, 0)) + out * 0.3
                loc, normal = m.hit(piece, start, -out)
                if loc is None:
                    loc, normal = on_line + Vector((0, y + yo, 0)), out
                p = loc + normal * 0.004
                eyelet = tube(m.bm, [p - normal * 0.004, p + normal * 0.001], [0.0038, 0.0038], sides=8)
                m.weigh(eyelet, weights)
                m.paint(eyelet, "Barrel")
                row.append((p, normal))
            rows.append(row)
        for r0, r1 in zip(rows, rows[1:]):
            for (a, na), (b, nb) in ((r0[0], r1[1]), (r0[1], r1[0])):
                mid = (a + b) / 2 + (na + nb).normalized() * 0.004
                lace = tube(m.bm, [a, mid, b], [0.0022] * 3, sides=6)
                m.weigh(lace, weights)
                m.paint(lace, "Lace")
        top = (rows[-1][0][0] + rows[-1][1][0]) / 2 + Vector((0.006, 0, 0.002))
        for side_y in (-1, 1):
            loop = tube(m.bm, [top, top + Vector((0.01, side_y * 0.014, 0.008)), top + Vector((0.004, side_y * 0.02, -0.006)), top],
                        [0.002] * 4, sides=5)
            m.weigh(loop, weights)
            m.paint(loop, "Lace")
        tab = ribbon(m.bm, [(-0.044, y, 0.15), (-0.056, y, 0.172), (-0.05, y, 0.19)], 0.016, 0.003, Vector((-1, 0, 0.2)))
        m.weigh(tab, weights)
        m.paint(tab, "Strap")


def seam(m, piece, center_at, angle, zs, weights, lift=0.001, radius=0.0021):
    """A sewn seam: a fine ridge of the same cloth along `piece` at `angle`."""
    d = Vector((math.cos(angle), math.sin(angle), 0.0))
    pts = []
    for z in zs:
        loc, normal = m.hit(piece, center_at(z) + d * 0.5, -d)
        if loc is not None:
            pts.append(loc + normal * lift)
    if len(pts) > 1:
        verts = tube(m.bm, pts, [radius] * len(pts), sides=6)
        m.weigh(verts, weights)
        m.paint(verts, "Camo")


def leg_cloth(m, legs):
    """Seams down both trouser legs and a buttoned flap over each cargo pocket."""
    for side, s in (("R", -1), ("L", 1)):
        y = s * HIP[0]
        weights = m.weights_near(legs[side])
        center = lambda z, yy=y: Vector((0.0, yy, z))  # noqa: E731
        zs = [0.5 - 0.33 * k / 16 for k in range(17)]
        seam(m, f"leg.{side}", center, s * math.pi / 2, zs, weights)
        seam(m, f"leg.{side}", center, -s * math.pi / 2, [z for z in zs if z < 0.45], weights)
        seam(m, f"leg.{side}", center, math.radians(s * 20), [0.31 + 0.1 * k / 6 for k in range(7)], weights, radius=0.0016)
        hug_patch(m, f"leg.{side}", center, [math.radians(s * a) for a in range(64, 121, 7)],
                  [0.448, 0.459, 0.47], 0.004, 0.0045, "Camo", weights)
        for a in (80, 104):
            loc, normal = m.hit(f"leg.{side}", center(0.452) + Vector((math.cos(math.radians(s * a)), math.sin(math.radians(s * a)), 0)) * 0.5,
                                -Vector((math.cos(math.radians(s * a)), math.sin(math.radians(s * a)), 0)))
            if loc is not None:
                button = chamfered(m.bm, lambda bm, p=loc + normal * 0.009: box(bm, p, (0.007, 0.007, 0.007)), 0.0025)
                m.weigh(button, weights)
                m.paint(button, "Strap")


def sleeve_cloth(m, side, sleeve):
    """Seams down the sleeve, and on the far arm a shoulder pocket with a flap."""
    s = 1 if side == "L" else -1
    y = s * SHOULDER[0]
    weights = m.weights_near(sleeve)
    center = lambda z, yy=y: Vector((0.0, yy, z))  # noqa: E731
    seam(m, f"sleeve.{side}", center, s * math.pi / 2 + 0.25, [0.79 - 0.3 * k / 12 for k in range(13)], weights)
    seam(m, f"sleeve.{side}", center, math.pi + 0.2, [0.76 - 0.26 * k / 10 for k in range(11)], weights)
    if side == "L":
        ang = [math.radians(a) for a in range(52, 129, 8)]
        hug_patch(m, f"sleeve.{side}", center, ang, [0.704, 0.722, 0.742, 0.762], 0.003, 0.004, "Camo", weights)
        hug_patch(m, f"sleeve.{side}", center, ang, [0.758, 0.772, 0.784], 0.0075, 0.004, "Camo", weights)
        hug_patch(m, f"sleeve.{side}", center, [math.radians(a) for a in range(66, 115, 8)], [0.73, 0.752],
                  0.008, 0.002, "Strap", weights)


def gloves(m):
    """Hard knuckle guards and a wrist strap on each glove."""
    for side, s in (("L", 1), ("R", -1)):
        y = s * SHOULDER[0]
        bone = f"forearm.{side}"
        m.group = f"arm.{side}"
        guard = chamfered(m.bm, lambda bm, y=y, s=s: box(bm, (0.006, y + s * 0.021, WRIST[1] - 0.056), (0.064, 0.009, 0.024)), 0.003, 2)
        m.part(guard, bone, "Pad")
        strap(m, f"hand.{side}", lambda z, y=y: Vector((0.0, y, z)), WRIST[1] + 0.022, 0.0025, bone, height=0.012)


def headset(m):
    """Electronic hearing protection: an ear cup over each ear with its cushion, the
    rail adapters up to the helmet, and a boom mic in front of the mouth."""
    for s in (1, -1):
        loc, _ = m.hit("mask", Vector((-0.014, s * 0.4, 1.054)), Vector((0, -s, 0)))
        if loc is None:
            continue
        out = Vector((0, s, 0))
        base = loc - out * 0.004
        m.part(tube(m.bm, [base, base + out * 0.013], [0.031, 0.031], sides=24), "head", "Pad")
        m.part(tube(m.bm, [base + out * 0.011, base + out * 0.024, base + out * 0.031], [0.03, 0.028, 0.019], sides=24), "head", "Polymer")
        m.part(chamfered(m.bm, lambda bm, p=base + out * 0.03: box(bm, p + Vector((0.008, 0, 0.004)), (0.016, 0.004, 0.01)), 0.0015), "head", "Polymer")
        arm = [base + out * 0.016 + Vector((0, 0, 0.026)), base + out * 0.02 + Vector((0, 0, 0.05))]
        m.part(ribbon(m.bm, arm, 0.012, 0.004, out), "head", "Polymer")
        if s == -1:
            boom = [base + out * 0.025 + Vector((0.02, 0, -0.012)), base + out * 0.024 + Vector((0.06, 0, -0.04)),
                    Vector((0.095, -0.036, 0.995)), Vector((0.11, -0.016, 0.99))]
            m.part(tube(m.bm, boom, [0.0028] * 4, sides=8), "head", "Polymer")
            m.part(tube(m.bm, [Vector((0.106, -0.022, 0.99)), Vector((0.114, -0.004, 0.99))], [0.0065, 0.0065], sides=10), "head", "Pad")


def helmet_extras(m):
    """Loop-velcro panels on the shell, a counterweight pouch at the back and a strobe."""
    center = lambda z: Vector((-0.012, 0.0, z))  # noqa: E731
    hug_patch(m, "helmet", center, [math.radians(a) for a in range(-26, 27, 6)], [1.168, 1.184, 1.198],
              0.0015, 0.0025, "HelmetBand")
    hug_patch(m, "helmet", center, [math.radians(a) for a in range(150, 211, 6)], [1.13, 1.15, 1.17],
              0.0015, 0.0025, "HelmetBand")
    loc, _ = m.hit("helmet", center(1.112), Vector((-1, 0, 0)))
    if loc is not None:
        m.part(chamfered(m.bm, lambda bm: box(bm, loc + Vector((-0.012, 0, -0.004)), (0.026, 0.072, 0.04)), 0.007, 2),
               "head", "VestPouch")
    loc, _ = m.hit("helmet", center(1.195), Vector((-1, 0, 0.6)))
    if loc is not None:
        m.part(chamfered(m.bm, lambda bm: box(bm, loc + Vector((-0.004, 0, 0.008)), (0.018, 0.016, 0.014)), 0.003),
               "head", "Polymer")


def rifle(m):
    """A carbine as a multi-part prop along +X from the grip, built like an AR: a
    collapsible stock on its buffer tube, upper and lower receivers (ejection port,
    forward assist, charging handle, magwell, trigger and guard), a pistol grip, a
    curved polymer magazine, a full-length top rail with its slots, a free-float
    handguard with M-LOK slots, a weapon light and a vertical grip, a variable optic on a
    cantilever mount, the barrel and a birdcage flash hider, then the bayonet. All the
    hard parts are bevelled, like real machined and moulded parts."""
    bm = m.bm

    def at(x, y=0.0, z=0.0):
        return AXIS + Vector((x, y, z))

    def block(x0, x1, y0, y1, z0, z1, mat, bevel=0.0025, segments=1):
        center = at((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        size = (x1 - x0, y1 - y0, z1 - z0)
        if bevel:
            m.part(chamfered(bm, lambda t: box(t, center, size), bevel, segments), "rifle", mat)
        else:
            m.part(box(bm, center, size), "rifle", mat, smooth=False)

    def rod(x0, x1, r0, mat, r1=None, y=0.0, z=0.0, sides=18):
        m.part(tube(bm, [at(x0, y, z), at(x1, y, z)], [r0, r1 or r0], sides=sides), "rifle", mat)

    def angled(a, b, wa, ha, wb, hb, mat, up=(1, 0, 0), bevel=0.003):
        m.part(chamfered(bm, lambda t: slab(t, at(*a), at(*b), wa, ha, wb, hb, up=Vector(up)), bevel), "rifle", mat)

    # Stock: buffer tube, castle nut, the stock body with its cheek weld and a rubber pad.
    rod(-0.25, -0.04, 0.0155, "Gunmetal")
    rod(-0.05, -0.036, 0.02, "Barrel", sides=12)
    angled((-0.306, 0, -0.024), (-0.17, 0, -0.006), 0.038, 0.104, 0.034, 0.054, "Polymer", bevel=0.006)
    angled((-0.29, 0, 0.026), (-0.19, 0, 0.022), 0.03, 0.012, 0.028, 0.01, "Polymer", bevel=0.004)
    angled((-0.318, 0, -0.026), (-0.304, 0, -0.026), 0.042, 0.112, 0.042, 0.112, "Pad", bevel=0.004)
    block(-0.245, -0.215, -0.022, 0.022, -0.07, -0.058, "Barrel", 0.002)  # sling mount
    # Lower receiver: body, magwell with its flared lip, trigger guard, trigger, controls.
    block(-0.036, 0.118, -0.0195, 0.0195, -0.044, -0.006, "Gunmetal", 0.003)
    angled((0.064, 0, -0.04), (0.06, 0, -0.088), 0.036, 0.066, 0.034, 0.06, "Gunmetal")
    block(0.002, 0.052, -0.004, 0.004, -0.071, -0.066, "Gunmetal", 0.0015)
    block(0.046, 0.054, -0.004, 0.004, -0.07, -0.044, "Gunmetal", 0.0015)
    angled((0.02, 0, -0.046), (0.016, 0, -0.064), 0.004, 0.006, 0.004, 0.004, "Barrel", bevel=0.001)
    block(-0.012, 0.0, -0.023, -0.0195, -0.03, -0.02, "Barrel", 0.0012)  # selector
    block(0.098, 0.108, -0.023, -0.0195, -0.034, -0.024, "Barrel", 0.0012)  # mag release
    # Pistol grip, raked back, with its beavertail.
    angled((-0.006, 0, -0.04), (-0.038, 0, -0.118), 0.03, 0.04, 0.028, 0.036, "Polymer", bevel=0.006)
    # Upper receiver: body, ejection port cover, brass deflector, forward assist, charging handle.
    block(-0.04, 0.152, -0.019, 0.019, -0.008, 0.022, "Gunmetal", 0.003)
    block(0.036, 0.098, -0.0205, -0.018, -0.002, 0.015, "Barrel", 0.001)
    block(0.012, 0.03, -0.024, -0.016, 0.002, 0.016, "Gunmetal", 0.002)
    rod(-0.034, -0.004, 0.0065, "Gunmetal", y=-0.022, z=0.008, sides=12)
    block(-0.066, -0.04, -0.026, 0.026, 0.014, 0.024, "Gunmetal", 0.002)
    # Full-length top rail with its cross slots, and folding iron sights at each end.
    block(-0.04, 0.37, -0.011, 0.011, 0.022, 0.03, "Gunmetal", 0.0015)
    x = -0.036
    while x < 0.366:
        block(x, x + 0.0052, -0.0115, 0.0115, 0.03, 0.0355, "Gunmetal", 0.0)
        x += 0.0104
    block(-0.036, -0.016, -0.009, 0.009, 0.0355, 0.046, "Barrel", 0.0015)
    block(0.346, 0.364, -0.008, 0.008, 0.0355, 0.05, "Barrel", 0.0015)
    # Free-float handguard: an octagonal tube with M-LOK slots, an end cap and a QD cup.
    rings = []
    for xx in (0.152, 0.37):
        ring = []
        for k in range(8):
            a = math.radians(22.5 + 45 * k)
            ring.append(bm.verts.new(at(xx, 0.0255 * math.cos(a), 0.002 + 0.0255 * math.sin(a))))
        rings.append(ring)
    hg = [v for r in rings for v in r]
    for k in range(8):
        bm.faces.new((rings[0][k], rings[0][(k + 1) % 8], rings[1][(k + 1) % 8], rings[1][k]))
    bm.faces.new(tuple(reversed(rings[0])))
    bm.faces.new(tuple(rings[1]))
    m.part(hg, "rifle", "Gunmetal", smooth=False)
    for i in range(5):
        xx = 0.178 + i * 0.037
        block(xx, xx + 0.024, -0.0245, -0.0229, -0.0016, 0.0056, "Barrel", 0.0)
        block(xx, xx + 0.024, -0.0042, 0.0042, -0.0225, -0.0209, "Barrel", 0.0)
    rod(0.37, 0.378, 0.022, "Barrel", sides=16)
    # Weapon light on the near side, its bezel lens, and a vertical grip underneath.
    rod(0.302, 0.366, 0.0105, "Gunmetal", y=-0.038, z=0.002, sides=14)
    rod(0.352, 0.37, 0.0128, "Gunmetal", y=-0.038, z=0.002, sides=14)
    rod(0.369, 0.3715, 0.0105, "GoggleGlass", y=-0.038, z=0.002, sides=14)
    block(0.31, 0.344, -0.031, -0.024, -0.006, 0.01, "Gunmetal", 0.0015)
    angled((0.262, 0, -0.024), (0.27, 0, -0.084), 0.022, 0.024, 0.02, 0.022, "Polymer", bevel=0.005)
    # Variable optic on a cantilever mount: two rings, the tube, the bells and turrets.
    block(-0.004, 0.086, -0.012, 0.012, 0.0355, 0.046, "Gunmetal", 0.002)
    for xx in (0.006, 0.066):
        block(xx, xx + 0.014, -0.006, 0.006, 0.046, 0.058, "Gunmetal", 0.0015)
        rod(xx, xx + 0.014, 0.0205, "Gunmetal", z=0.074, sides=20)
    rod(-0.03, 0.118, 0.0152, "Gunmetal", z=0.074, sides=20)
    rod(-0.072, -0.03, 0.0195, "Gunmetal", r1=0.0175, z=0.074, sides=20)
    rod(0.118, 0.158, 0.0165, "Gunmetal", r1=0.0215, z=0.074, sides=20)
    rod(-0.073, -0.071, 0.016, "GoggleGlass", z=0.074, sides=20)
    rod(0.157, 0.159, 0.019, "GoggleGlass", z=0.074, sides=20)
    m.part(tube(bm, [at(0.038, 0, 0.088), at(0.038, 0, 0.104)], [0.0085, 0.0085], sides=14), "rifle", "Gunmetal")
    m.part(tube(bm, [at(0.038, -0.014, 0.074), at(0.038, -0.03, 0.074)], [0.0085, 0.0085], sides=14), "rifle", "Gunmetal")
    rod(-0.05, -0.04, 0.021, "Barrel", z=0.074, sides=20)  # magnification ring
    # Barrel and a birdcage flash hider with its slots.
    rod(0.378, 0.505, 0.0092, "Barrel", sides=16)
    rod(0.44, 0.454, 0.0125, "Barrel", sides=14)  # sight base / gas block shoulder
    rod(0.505, 0.552, 0.0118, "Barrel", sides=16)
    for k in range(4):
        a = math.radians(45 + 90 * k)
        block(0.512, 0.546, 0.0112 * math.cos(a) - 0.0016, 0.0112 * math.cos(a) + 0.0016,
              0.0112 * math.sin(a) - 0.0016, 0.0112 * math.sin(a) + 0.0016, "GoggleGlass", 0.0)
    # Curved polymer magazine with its base plate and grip ribs.
    for (x0, z0), (x1, z1), w in ((((0.063, -0.084), (0.07, -0.13), 0.058)), (((0.07, -0.13), (0.088, -0.176), 0.056))):
        angled((x0, 0, z0), (x1, 0, z1), 0.026, w, 0.026, w, "Polymer", bevel=0.003)
    angled((0.088, 0, -0.176), (0.091, 0, -0.186), 0.03, 0.062, 0.03, 0.062, "Polymer", bevel=0.003)
    for k in range(4):
        zz = -0.14 - k * 0.009
        xx = 0.07 + (zz + 0.13) * -0.4
        block(xx - 0.02, xx + 0.02, -0.0145, -0.0128, zz - 0.002, zz + 0.002, "Polymer", 0.0)
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
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(4):
            quad = (r0[j], r0[(j + 1) % 4], r1[0]) if len(r1) == 1 else (r0[j], r0[(j + 1) % 4], r1[(j + 1) % 4], r1[j])
            bm.faces.new(quad)
    bm.faces.new(list(reversed(rings[0])))
    m.part([v for r in rings for v in r], "rifle", "Steel", smooth=False)
    # Sling: flat webbing from the stock mount to the handguard, hanging on the near side.
    sling = [at(-0.23, -0.026, -0.07), at(-0.12, -0.03, -0.13), at(0.02, -0.032, -0.155),
             at(0.16, -0.03, -0.13), at(0.3, -0.03, -0.04)]
    m.part(ribbon(bm, sling, 0.016, 0.003, Vector((0, 1, 0))), "rifle", "Strap")


def soldier_mesh():
    m = Model()
    m.group = "body"
    mask = m.blob("mask", balaclava_blob(), 0.34, "Balaclava", "head")
    fatigues = m.blob("fatigues", fatigues_blob(), 0.3, "Camo", by_distance("hips", "spine"))
    sleeves, legs, boots = {}, {}, {}
    for side, s in (("L", 1), ("R", -1)):
        legs[side] = m.blob(f"leg.{side}", leg_blob(s), 0.3, "Camo",
                            by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        boots[side] = m.blob(f"boot.{side}", boot_blob(s), 0.4, "Boot",
                             by_distance(f"foot.{side}", f"shin.{side}", sharpness=9))
    goggles(m, "head")
    helmet(m)
    helmet_extras(m)
    headset(m)
    on_fatigues = m.weights_near(fatigues)
    carrier(m, on_fatigues)
    pouches(m, on_fatigues)
    belt(m, on_fatigues)
    for side in ("R", "L"):
        leg_pads(m, side, m.weights_near(legs[side]))
    leg_gear(m, m.weights_near(legs["R"]), m.weights_near(legs["L"]))
    boot_details(m, m.weights_near(boots["R"]), m.weights_near(boots["L"]))
    leg_cloth(m, legs)
    for side, s in (("L", 1), ("R", -1)):
        m.group = f"arm.{side}"
        sleeves[side] = m.blob(f"sleeve.{side}", sleeve_blob(s), 0.32, "Camo",
                               by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", hand_blob(s), 0.4, "Glove", f"forearm.{side}")
        arm_pads(m, side, m.weights_near(sleeves[side]))
        sleeve_cloth(m, side, sleeves[side])
        if side == "R":
            patches(m, m.weights_near(sleeves["R"]))
    gloves(m)
    m.group = "rifle"
    rifle(m)

    mesh = bpy.data.meshes.new("SoldierMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    bake_occlusion(m)
    rest_uvs(m.bm)
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    # Hard edges stay hard (box corners, pouch seams), everything shallower shades smooth,
    # so a bevel reads as a rounded edge rather than a facet.
    mesh.set_sharp_from_angle(angle=math.radians(65))
    mesh.color_attributes.active_color = mesh.color_attributes["Occlusion"]
    return mesh


# --- Baked shading data ------------------------------------------------------
# Two things the game's shaders read off the mesh (godot/shaders/soldier.gdshaderinc):
# - The *rest position* of every vertex, in the two UV maps: (x, z) in `UVMap` and
#   (y, 0) in `Rest`. Godot skins the mesh before the shader runs, so a pattern drawn in
#   object space would slide over the cloth as he moves; drawn at the rest position it
#   stays printed on the fabric.
# - *Ambient occlusion* in the vertex color: how much of the sky each vertex sees, so
#   the creases, the gaps between pouches and the underside of the helmet go dark the
#   way real gear does. Each group (body, arms, rifle) is only shadowed by itself, since
#   in the rest pose the arms hang beside the body where they never are in the game.

OCCLUSION_RAYS = 40
OCCLUSION_REACH = 0.07  # meters: local creases and contact shadows, not whole-body shade


def bake_occlusion(m):
    bm = m.bm
    bm.normal_update()
    bm.verts.index_update()
    layer = bm.verts.layers.float_color.new("Occlusion")
    rng = random.Random(1944)
    dirs = []
    for _ in range(OCCLUSION_RAYS):  # cosine-weighted over the hemisphere
        u, a = rng.random(), 2 * math.pi * rng.random()
        r = math.sqrt(u)
        dirs.append(Vector((r * math.cos(a), r * math.sin(a), math.sqrt(1 - u))))
    groups = [v[m.group_layer] for v in bm.verts]
    trees = {}
    for g in set(groups):
        faces = [f for f in bm.faces if all(groups[v.index] == g for v in f.verts)]
        index, coords = {}, []
        for f in faces:
            for v in f.verts:
                if v not in index:
                    index[v] = len(coords)
                    coords.append(v.co.copy())
        trees[g] = BVHTree.FromPolygons(coords, [[index[v] for v in f.verts] for f in faces])
    for v in bm.verts:
        n = v.normal
        if n.length < 0.5:
            v[layer] = (1, 1, 1, 1)
            continue
        t = n.orthogonal().normalized()
        b = n.cross(t)
        tree = trees[groups[v.index]]
        origin = v.co + n * 0.0012
        shade = 0.0
        for d in dirs:
            loc, _, _, dist = tree.ray_cast(origin, t * d.x + b * d.y + n * d.z, OCCLUSION_REACH)
            if loc is not None:
                shade += 1.0 - (dist / OCCLUSION_REACH) ** 2
        ao = 1.0 - shade / len(dirs)
        v[layer] = (ao, ao, ao, 1.0)
    # A little blur along the surface, so the bake has no speckle.
    for _ in range(2):
        values = {v: v[layer][0] for v in bm.verts}
        for v in bm.verts:
            near = [e.other_vert(v) for e in v.link_edges]
            if near:
                ao = 0.5 * values[v] + 0.5 * sum(values[o] for o in near) / len(near)
                v[layer] = (ao, ao, ao, 1.0)


def rest_uvs(bm):
    uv, rest = bm.loops.layers.uv.new("UVMap"), bm.loops.layers.uv.new("Rest")
    for f in bm.faces:
        for loop in f.loops:
            co = loop.vert.co
            loop[uv].uv = (co.x, co.z)
            loop[rest].uv = (co.y, 0.0)


def export(path):
    """The chef's export settings (build_fighter.export), plus the baked vertex colors and
    both UV maps, which the soldier's shaders read."""
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
        export_texcoords=True,
        export_vertex_color="ACTIVE",
        export_all_vertex_colors=False,
        export_cameras=False,
        export_lights=False,
    )

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


# --- Ledge ------------------------------------------------------------------
# The sim (`try_grab_ledge`, `ledge_getup_pos` in sim/src/fighter.rs) hangs the origin
# 0.1 m outside the edge with the top of the hurtbox (H) level with the platform, so the
# corner is at model-local (0.1, H). A getup slides the origin linearly onto the stage:
# on getup frame k the sim has moved it (k - 1) / total of the way (frame 1 is shown
# before the first move), and the frame after the last is `idle` at the end point.
# The clips are authored in *ledge space* (origin = the hang spot, fixed to the stage),
# keyed on every frame with that root motion taken back out, so a hand or foot planted
# on the stage stays put while the origin slides under it.

H = 1.2  # FighterParams::SOLDIER height (12) x 0.1
CORNER = Vector((0.1, H))  # (forward, up) in ledge space
UPPER_ARM, FOREARM = SHOULDER[1] - ELBOW[1], ELBOW[1] - WRIST[1]
FIST_REACH = FOREARM + chef.FIST
GRIP_EDGE = Vector((0.118, H + 0.012))  # the fist wrapped over the corner
ARM_CHAIN = ("hips", "spine", "upper_arm.R", "forearm.R")


def rot(deg, x, z):
    """(x, z) turned counter-clockwise as the game camera sees it (0 = down is +90 forward)."""
    a = math.radians(deg)
    return Vector((x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)))


def shoulder_at(pose):
    """The shoulder joint (forward, up) in model space, from the hips and spine."""
    fwd, up = pose.get("hips_loc", (0, 0))
    hp, sp = pitch(pose.get("hips", 0)), pitch(pose.get("spine", 0))
    return Vector((fwd, 0.55 + up)) + rot(hp, 0, 0.13) + rot(hp + sp, 0, SHOULDER[1] - 0.68)


def arm_ik(pose, side, target):
    """Puts the `side` fist on `target` (model space), the elbow bending the natural way."""
    s = shoulder_at(pose)
    d = Vector(target) - s
    dist = max(0.06, min(d.length, UPPER_ARM + FIST_REACH - 1e-3))
    toward = math.degrees(math.atan2(d.x, -d.y))  # 0 = straight down, + = forward
    cos_a = (UPPER_ARM**2 + dist**2 - FIST_REACH**2) / (2 * UPPER_ARM * dist)
    cos_b = (FIST_REACH**2 + dist**2 - UPPER_ARM**2) / (2 * FIST_REACH * dist)
    a = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
    b = math.degrees(math.acos(max(-1.0, min(1.0, cos_b))))
    base = pitch(pose.get("hips", 0)) + pitch(pose.get("spine", 0))
    pose[f"upper_arm.{side}"] = toward - a - base
    pose[f"forearm.{side}"] = a + b
    return pose


def arm_chain(pose):
    return sum(pitch(pose.get(b, 0)) for b in ARM_CHAIN)


def ledge_key(pose, at=(0.0, 0.0), hands=None, feet=None, grip=None):
    """A getup key in ledge space: `pose` placed with its origin at `at`, plus contacts
    held there — `hands` {side: (x, z) fist}, `feet` {side: (x, floor z)} — and `grip`,
    the rifle's angle to the right forearm (it then turns with the arm; else `aim` holds)."""
    return {"pose": pose, "at": Vector(at), "hands": hands or {}, "feet": feet or {}, "grip": grip}


def place(key, root):
    """`key` solved in model space for the origin at `root` (ledge space)."""
    pose = dict(key["pose"])
    fwd, up = pose.get("hips_loc", (0, 0))
    pose["hips_loc"] = (key["at"].x + fwd - root.x, key["at"].y + up - root.y)
    for side, target in key["hands"].items():
        arm_ik(pose, side, Vector(target) - root)
    for side, (x, floor) in key["feet"].items():
        leg_ik(pose, side, x - root.x, floor - root.y)
    if key["grip"] is not None:
        pose["aim"] = arm_chain(pose) + key["grip"]
    pose.setdefault("aim", 12)
    return pose


def spline(times, values, t):
    """Smooth monotone-ish curve through (times, values): Catmull-Rom tangents, flattened
    at turning points so nothing overshoots a key."""
    n = len(times)
    if t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    i = max(j for j in range(n - 1) if times[j] <= t)

    def tangent(j):
        if j == 0 or j == n - 1:
            return 0.0
        if (values[j] - values[j - 1]) * (values[j + 1] - values[j]) <= 0:
            return 0.0
        m = (values[j + 1] - values[j - 1]) / (times[j + 1] - times[j - 1])
        lo = min(abs(values[j] - values[j - 1]) / (times[j] - times[j - 1]),
                 abs(values[j + 1] - values[j]) / (times[j + 1] - times[j]))
        return math.copysign(min(abs(m), 3 * lo), m)

    h = times[i + 1] - times[i]
    u = (t - times[i]) / h
    h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2
    return h00 * values[i] + h10 * h * tangent(i) + h01 * values[i + 1] + h11 * h * tangent(i + 1)


def getup(total, inward, keys):
    """A getup clip of `total` frames that moves the origin `inward` and up H: every frame
    keyed, `keys` [(frame, ledge_key)] splined in ledge space, contacts held by IK."""
    def root(frame):
        t = (frame - 1) / total
        return Vector((inward * t, H * t))

    frames = [f for f, _ in keys]
    solved = []
    for f, key in keys:
        pose = place(key, root(f))
        world = Vector(pose["hips_loc"]) + root(f)
        solved.append((pose, world, pose["aim"] - arm_chain(pose)))
    channels = sorted({b for pose, _, _ in solved for b in pose if b not in ("hips_loc", "aim")})
    # IK answers come back modulo 360: unwrap every joint (and the rifle) key to key, so
    # the spline never spins one the long way round. Only the hips spin on purpose.
    def unwrapped(values):
        out = [values[0]]
        for v in values[1:]:
            out.append(v + 360 * round((out[-1] - v) / 360))
        return out

    for b in channels + ["aim"]:
        if b != "hips":
            for (pose, _, _), v in zip(solved, unwrapped([pitch(p.get(b, 0)) for p, _, _ in solved])):
                pose[b] = v
    grips = unwrapped([p["aim"] - arm_chain(p) for p, _, _ in solved])
    solved = [(p, w, g) for (p, w, _), g in zip(solved, grips)]
    out = []
    for frame in range(1, total + 1):
        i = max(j for j in range(len(frames)) if frames[j] <= frame) if frame < frames[-1] else len(frames) - 2
        pose = {b: spline(frames, [pitch(p.get(b, 0)) for p, _, _ in solved], frame) for b in channels}
        world = Vector((spline(frames, [w.x for _, w, _ in solved], frame),
                        spline(frames, [w.y for _, w, _ in solved], frame)))
        r = root(frame)
        pose["hips_loc"] = tuple(world - r)
        (fa, ka), (fb, kb) = keys[i], keys[i + 1]
        u = (frame - fa) / (fb - fa)
        u = u * u * (3 - 2 * u)
        # A contact held through both keys around this frame is re-solved, so it stays put.
        for side in set(ka["hands"]) & set(kb["hands"]):
            target = Vector(ka["hands"][side]).lerp(Vector(kb["hands"][side]), u)
            arm_ik(pose, side, target - r)
        for side in set(ka["feet"]) & set(kb["feet"]):
            x = ka["feet"][side][0] + (kb["feet"][side][0] - ka["feet"][side][0]) * u
            floor = ka["feet"][side][1] + (kb["feet"][side][1] - ka["feet"][side][1]) * u
            leg_ik(pose, side, x - r.x, floor - r.y)
        if ka["grip"] is not None and kb["grip"] is not None:
            pose["aim"] = arm_chain(pose) + spline(frames, [g for _, _, g in solved], frame)
        else:
            pose["aim"] = spline(frames, [p["aim"] for p, _, _ in solved], frame)
        if out:  # keep the rifle bone's own angle continuous frame to frame
            prev = out[-1][1]
            turn = (prev["aim"] - arm_chain(prev)) - (pose["aim"] - arm_chain(pose))
            pose["aim"] += 360 * round(turn / 360)
        out.append((frame, pose))
    return out


def standing(at_x, pose=S):
    """`pose` (standing, feet at +-0.11) on the stage top at ledge-space x `at_x`."""
    return ledge_key(pose, (at_x, H), feet={"R": (at_x + 0.11, H), "L": (at_x - 0.11, H)})


# The hang: the far (left) hand wrapped over the corner, the near one holding the rifle
# upright against his chest (port arms, so it clears the wall), the body hanging against the wall and swaying a little.
def hang(phase):
    sway, breath = math.sin(phase), math.sin(2 * phase)
    pose = {
        "hips_loc": (-0.088 + 0.008 * sway, -0.052 + 0.003 * breath),
        "hips": 2 * sway, "spine": 4 + 1.5 * breath, "head": 16 - 2 * breath,
        "upper_arm.R": 8 + 3 * sway, "forearm.R": 112, "aim": 96 + 2 * sway,
        "thigh.R": 16 + 5 * math.sin(phase + 0.5), "shin.R": -34 - 4 * sway, "foot.R": -38,
        "thigh.L": -2 + 5 * math.sin(phase + 1.3), "shin.L": -22, "foot.L": -30,
    }
    return ledge_key(pose, hands={"L": GRIP_EDGE})


HANG = 72  # frames per sway, looped on the world clock
ANIMATIONS["ledge_hang"] = [(f, place(hang(2 * math.pi * (f - 1) / HANG), Vector((0, 0)))) for f in range(1, HANG + 2)]


# Climb: 20 frames, 0.9 m in. A one-arm pull with the left hand, the right knee onto the
# stage, then up over the right foot and a step into the stance.
EDGE = {"L": GRIP_EDGE}
ANIMATIONS["ledge_climb"] = getup(20, 0.9, [
    (1, hang(0.0)),
    (6, ledge_key({"hips_loc": (-0.05, 0.27), "hips": -6, "spine": -16, "head": 18,
                   "upper_arm.R": 14, "forearm.R": 116, "aim": 94,
                   "thigh.R": 60, "shin.R": -100, "foot.R": -10, "thigh.L": 8, "shin.L": -40, "foot.L": -30}, hands=EDGE)),
    (10, ledge_key({"hips_loc": (0.06, 0.80), "hips": -14, "spine": -30, "head": 30,
                    "upper_arm.R": 40, "forearm.R": 100, "aim": 70,
                    "thigh.R": 84, "shin.R": -160, "foot.R": 0, "thigh.L": -10, "shin.L": -30, "foot.L": -20}, hands=EDGE)),
    (14, ledge_key({"hips_loc": (0.0, -0.14), "hips": -6, "spine": -18, "head": 12,
                    "upper_arm.R": 28, "forearm.R": 84, "aim": 2, "upper_arm.L": 30, "forearm.L": 60,
                    "thigh.L": 70, "shin.L": -110, "foot.L": 0}, (0.52, H), feet={"R": (0.62, H)})),
    (17, ledge_key({"hips_loc": (0.02, -0.08), "spine": -10, "head": 8,
                    "upper_arm.R": 32, "forearm.R": 82, "aim": 10, "upper_arm.L": 40, "forearm.L": 66,
                    "thigh.R": 50, "shin.R": -60, "foot.R": 0}, (0.80, H), feet={"L": (0.79, H)})),
    (20, standing(0.9)),
])


def ball(spin, center_x):
    """The tucked roll, turned `spin` degrees (negative = forward) about its own middle,
    which sits 0.27 m above the stage at ledge-space x `center_x`."""
    tuck = {"spine": -50, "head": 30, "thigh.R": 115, "shin.R": -145, "foot.R": 20,
            "thigh.L": 108, "shin.L": -140, "foot.L": 20,
            "upper_arm.R": 50, "forearm.R": 120, "upper_arm.L": 45, "forearm.L": 125}
    middle = Vector((0.12, 0.105))  # the tuck's middle, from the hips, unturned
    hips = Vector((center_x, H + 0.27)) - rot(spin, middle.x, middle.y)
    return ledge_key(dict(tuck, hips=spin, hips_loc=(hips.x, hips.y - 0.55)), grip=102)


# Roll: 25 frames, 1.6 m in. A quick hoist on the left hand, a full forward roll in a
# tight tuck with the rifle hugged in, and up into the stance.
ANIMATIONS["ledge_roll"] = getup(25, 1.6, [
    (1, hang(0.0)),
    (5, ledge_key({"hips_loc": (-0.03, 0.40), "hips": -10, "spine": -24, "head": 20,
                   "upper_arm.R": 14, "forearm.R": 116, "aim": 94,
                   "thigh.R": 70, "shin.R": -110, "thigh.L": 40, "shin.L": -90}, hands=EDGE)),
    (8, ledge_key({"hips_loc": (0.12, 0.77), "hips": -45, "spine": -45, "head": 35,
                   "upper_arm.R": 50, "forearm.R": 115, "thigh.R": 110, "shin.R": -140, "foot.R": 20,
                   "thigh.L": 105, "shin.L": -140, "foot.L": 20}, hands=EDGE, grip=102)),
    (11, ball(-110, 0.48)),
    (14, ball(-200, 0.78)),
    (17, ball(-285, 1.06)),
    (20, dict(ball(-350, 1.30), grip=None, pose=dict(ball(-350, 1.30)["pose"], aim=70))),
    (22, ledge_key(with_(crouch(0.2), hips=-360, upper_arm_R=30, forearm_R=90, aim=0), (1.48, H),
                   feet={"R": (1.62, H), "L": (1.40, H)})),
    (25, ledge_key(with_(S, hips=-360), (1.6, H), feet={"R": (1.71, H), "L": (1.49, H)})),
])

# Getup attack: 30 frames, 1.1 m in; the hitbox (LEDGE_ATTACK_HITBOX in sim/src/world.rs)
# is live on 15-18, 0.6 m ahead of and above the origin with a 0.6 m radius — low across
# the stage top. Vaults up, lands crouched with the rifle wound back, and sweeps it round
# along the floor.
SWING_WIND = with_(crouch(0.2), spine=-6, head=4, upper_arm_R=-30, forearm_R=50, aim=178, upper_arm_L=40, forearm_L=60)
SWING = with_(crouch(0.24), spine=-14, head=12, upper_arm_R=96, forearm_R=0, aim=-12, upper_arm_L=-55, forearm_L=30)
LANDED = {"R": (1.0, H), "L": (0.44, H)}
ANIMATIONS["ledge_attack"] = getup(30, 1.1, [
    (1, hang(0.0)),
    (5, ledge_key({"hips_loc": (-0.03, 0.40), "hips": -10, "spine": -24, "head": 20,
                   "upper_arm.R": 14, "forearm.R": 116, "aim": 94,
                   "thigh.R": 70, "shin.R": -110, "thigh.L": 40, "shin.L": -90}, hands=EDGE)),
    (9, ledge_key({"hips_loc": (0.16, 0.86), "hips": -20, "spine": -30, "head": 26,
                   "upper_arm.R": -10, "forearm.R": 70, "aim": 150,
                   "thigh.R": 100, "shin.R": -130, "foot.R": 10, "thigh.L": 90, "shin.L": -130, "foot.L": 10}, hands=EDGE)),
    (12, ledge_key(SWING_WIND, (0.72, H), feet=LANDED)),
    (14, ledge_key(with_(SWING_WIND, spine=-2, upper_arm_R=-38, aim=186), (0.72, H), feet=LANDED)),
    (15, ledge_key(with_(SWING, upper_arm_R=60, aim=50), (0.72, H), feet=LANDED)),
    (16, ledge_key(SWING, (0.72, H), feet=LANDED)),
    (18, ledge_key(with_(SWING, upper_arm_R=80, aim=-22), (0.72, H), feet=LANDED)),
    (22, ledge_key(with_(SWING, upper_arm_R=60, aim=-8), (0.74, H), feet=LANDED)),
    (26, ledge_key(with_(crouch(0.1), upper_arm_R=30, forearm_R=80, aim=4), (0.98, H),
                   feet={"R": (1.0, H), "L": (0.99, H)})),
    (30, standing(1.1)),
])


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
