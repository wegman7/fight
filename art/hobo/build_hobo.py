"""Builds the drunk hobo: a ragged, stubbly brawler in a tattered overcoat and torn
trousers, with a bottle in his near hand and a shopping cart he pulls out for one move.
Then his armature and one action per pose name the sim reports (`Fighter::anim()`).
Saves `hobo.blend` next to this script and exports `godot/models/hobo.glb`.

    blender --background --factory-startup --python art/hobo/build_hobo.py

He stands on the chef's skeleton (same joints, same 1.2 m), so the shapes, pose helpers
and conventions come from `art/fighter/build_fighter.py` (see its README). On top of it
are two props, each scaled to 0 except in the moves that use them: `bottle` (the right
fist) and `cart` (in front of his hips).

The coat has its own grimy look: its `Coat` material uses two procedural textures baked
to `hobo_coat.png` (the mottled, stained coat colour) and `hobo_coat_rough.png` (its
roughness), so the grime and rough, weathered finish survive into the exported glb. The
`Body` material is the shirt underneath, which gets the player's colour in game.
"""

import math
import os
import struct
import sys
import zlib

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "hobo.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "hobo.glb")
COAT_PATH = os.path.join(HERE, "hobo_coat.png")
COAT_ROUGH_PATH = os.path.join(HERE, "hobo_coat_rough.png")

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
    UP,
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
FIST = 0.055

# The chef's bones, minus the pie, plus the bottle (right fist) and the shopping cart
# (in front of the hips).
GRIP = Vector((0.0, -SHOULDER[0], WRIST[1] - FIST))
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONES.append(("bottle", "forearm.R", tuple(GRIP), tuple(GRIP + Vector((0.14, 0, 0))), FWD))
CART_PIVOT = Vector((0.34, 0.0, 0.52))
BONES.append(("cart", "hips", tuple(CART_PIVOT), tuple(CART_PIVOT + Vector((0.0, 0, 0.24))), UP))
BONE_NAMES = [b[0] for b in BONES]

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the shirt)
# with the player's color; the rest keep their own.
MATERIALS = {
    "Body": ((0.42, 0.50, 0.32, 1), 0.85, 0.0),
    "Coat": ((0.28, 0.24, 0.16, 1), 0.92, 0.0),
    "Grime": ((0.10, 0.09, 0.06, 1), 1.0, 0.0),
    "Skin": ((0.84, 0.64, 0.50, 1), 0.55, 0.0),
    "Lip": ((0.66, 0.34, 0.30, 1), 0.45, 0.0),
    "Hair": ((0.24, 0.18, 0.12, 1), 0.7, 0.0),
    "Stubble": ((0.32, 0.26, 0.20, 1), 0.9, 0.0),
    "Eye": ((0.93, 0.91, 0.87, 1), 0.12, 0.0),
    "Iris": ((0.30, 0.20, 0.10, 1), 0.15, 0.0),
    "Pupil": ((0.01, 0.01, 0.01, 1), 0.1, 0.0),
    "Pants": ((0.15, 0.14, 0.12, 1), 0.9, 0.0),
    "Shoe": ((0.05, 0.045, 0.04, 1), 0.9, 0.0),
    "Bottle": ((0.16, 0.40, 0.20, 1), 0.2, 0.0),
    "Label": ((0.86, 0.78, 0.56, 1), 0.7, 0.0),
    "Cap": ((0.55, 0.12, 0.12, 1), 0.4, 0.7),
    "Cart": ((0.55, 0.55, 0.58, 1), 0.4, 0.9),
    "CartWheel": ((0.06, 0.06, 0.06, 1), 0.9, 0.0),
    "CartTrim": ((0.75, 0.16, 0.16, 1), 0.5, 0.5),
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


# --- Procedural grime/roughness textures ------------------------------------
# The coat's colour and roughness come from two textures generated here (a coarse
# value noise), so the grimy, weathered look survives the glTF export. Everything is
# seeded, so rebuilding produces the same maps.


def _hash2(x, y, seed):
    n = (x * 374761393 + y * 668265263 + seed * 1442695040888963407) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return (n ^ (n >> 16)) / 0xFFFFFFFF


def _smooth(t):
    return t * t * (3 - 2 * t)


def _noise(x, y, seed, period):
    x0, y0 = int(x // period), int(y // period)
    tx, ty = _smooth((x % period) / period), _smooth((y % period) / period)
    a, b = _hash2(x0, y0, seed), _hash2(x0 + 1, y0, seed)
    c, d = _hash2(x0, y0 + 1, seed), _hash2(x0 + 1, y0 + 1, seed)
    return a + (b - a) * tx + (c - a) * ty + (a - b - c + d) * tx * ty


def _png(path, w, h, rows):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *p) for p in row) for row in rows)
    with open(path, "wb") as f:
        f.write(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )


def make_textures():
    size = 256
    coat = (0.28, 0.24, 0.16)
    grime = (0.08, 0.07, 0.05)
    color_rows, rough_rows = [], []
    for y in range(size):
        crow, rrow = [], []
        for x in range(size):
            n = _noise(x, y, 7, 24) + 0.5 * _noise(x, y, 31, 9) + 0.25 * _noise(x, y, 127, 4)
            n /= 1.75
            # Dark grime stains where the noise peaks, plus a lighter worn patch.
            g = max(0.0, (n - 0.55)) / 0.45
            wear = max(0.0, (0.42 - n)) / 0.42
            c = [coat[i] * (1 - g) + grime[i] * g + 0.06 * wear for i in range(3)]
            crow.append(tuple(int(min(1.0, c[i]) * 255) for i in range(3)) + (255,))
            rough = 0.75 + 0.25 * n
            rrow.append((int(rough * 255),) * 3 + (255,))
        color_rows.append(crow)
        rough_rows.append(rrow)
    _png(COAT_PATH, size, size, color_rows)
    _png(COAT_ROUGH_PATH, size, size, rough_rows)


# --- Shapes -----------------------------------------------------------------


def head_blob():
    """A weathered, gaunt face: long, with hollow cheeks and a big drinker's nose."""
    b = Blob(resolution=0.0035)
    b.ell((-0.005, 0, 1.085), (0.086, 0.074, 0.09))  # cranium
    b.ell((0.03, 0, 1.028), (0.068, 0.062, 0.072))  # face
    b.ell((0.05, 0, 0.975), (0.04, 0.045, 0.024), stiffness=3)  # pointed chin
    b.cap((-0.014, 0, 0.84), (0.0, 0, 0.99), 0.05)  # neck
    for s in (1, -1):
        b.ell((0.058, s * 0.04, 1.05), (0.02, 0.024, 0.02), stiffness=3)  # cheekbones
        b.cap((-0.02, s * 0.056, 1.02), (0.055, s * 0.03, 0.975), 0.015, stiffness=3)  # jawline
        b.cap((0.082, s * 0.012, 1.097), (0.075, s * 0.05, 1.102), 0.011, stiffness=3)  # brow ridge
        b.ball((0.074, s * 0.031, 1.074), 0.013, stiffness=4, negative=True)  # eye socket
        b.ell((-0.012, s * 0.078, 1.06), (0.016, 0.01, 0.026), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-10 * s)))  # ears
        b.ell((-0.006, s * 0.086, 1.062), (0.008, 0.007, 0.015), stiffness=5, negative=True)
    b.cap((0.088, 0, 1.09), (0.102, 0, 1.05), 0.01, stiffness=3)  # nose bridge
    b.ball((0.105, 0, 1.038), 0.017, stiffness=3)  # big nose bulb
    b.cap((0.09, -0.019, 1.006), (0.09, 0.019, 1.006), 0.0035, stiffness=6, negative=True)  # mouth
    b.ell((0.087, 0, 0.998), (0.009, 0.018, 0.006), stiffness=4)  # lower lip
    return b


def hair_blob():
    """A greasy, unkempt mop, lank over the forehead and ears."""
    b = Blob(resolution=0.004)
    b.ell((-0.02, 0, 1.1), (0.092, 0.082, 0.08))
    for s in (1, -1):
        b.ell((0.03, s * 0.082, 1.07), (0.016, 0.008, 0.03), stiffness=4)  # sideburns
        b.ell((-0.01, s * 0.09, 1.06), (0.026, 0.02, 0.036), stiffness=4, negative=True)  # ears
    b.ell((0.06, 0, 1.05), (0.05, 0.08, 0.06), stiffness=4, negative=True)  # clear of the face
    b.cap((0.045, 0, 1.1), (0.03, 0, 1.0), 0.012, stiffness=4)  # a lock over the brow
    return b


def stubble_blob():
    """A few days' beard, hugging the jaw and chin under the skin."""
    b = Blob(resolution=0.0035)
    b.ell((0.05, 0, 0.99), (0.05, 0.065, 0.045), stiffness=3)
    b.ell((0.045, 0, 0.945), (0.04, 0.06, 0.03), stiffness=3)
    for s in (1, -1):
        b.ell((0.015, s * 0.058, 1.02), (0.03, 0.028, 0.03), stiffness=3)
    return b


def coat_blob():
    """The ragged overcoat: broad shoulders, a long body flaring to a torn hem."""
    b = Blob(resolution=0.006)
    b.ell((0.0, 0, 0.79), (0.105, 0.15, 0.11))  # chest
    b.ell((0.01, 0, 0.62), (0.11, 0.14, 0.13))  # waist, open front
    b.ell((0.005, 0, 0.42), (0.125, 0.15, 0.12))  # flaring hem
    for s in (1, -1):
        b.ell((-0.005, s * 0.09, 0.86), (0.06, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.155, 0.84), (0.058, 0.045, 0.045))  # shoulder seam
        b.ell((-0.06, s * 0.06, 0.79), (0.045, 0.06, 0.07))  # shoulder blades
        b.ell((0.03, s * 0.06, 0.72), (0.035, 0.05, 0.05), stiffness=4, negative=True)  # fold crease
    # The ragged hem: a few notches cut into the bottom edge.
    for i, (dz, dz2) in enumerate(((0.0, 0.34), (0.3, 0.28), (0.5, 0.36))):
        b.ell((0.02, 0, dz), (0.16, 0.16, 0.03), stiffness=4, negative=True)
    return b


def coat_sleeve_blob(s):
    """A baggy sleeve with a ragged cuff, the coat's loose fold under the arm."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.005)
    b.ell((0.0, y - s * 0.005, 0.84), (0.06, 0.06, 0.062))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.055)
    b.ell((0.012, y, 0.73), (0.04, 0.04, 0.06), stiffness=3)  # biceps fold
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.06), 0.052)
    b.ell((-0.012, y, 0.6), (0.042, 0.042, 0.055), stiffness=3)  # forearm
    b.ell((0.0, y, WRIST[1] - 0.02), (0.045, 0.045, 0.015), stiffness=4, negative=True)  # ragged cuff
    b.ell((-0.05, y, 0.58), (0.05, 0.045, 0.1), stiffness=3)  # the hanging fold
    return b


def shirt_blob():
    """The grimy shirt (`Body`) showing where the coat hangs open."""
    b = Blob(resolution=0.006)
    b.ell((0.05, 0, 0.78), (0.085, 0.11, 0.06), stiffness=3)  # chest, under the coat
    b.ell((0.07, 0, 0.62), (0.075, 0.1, 0.07), stiffness=3)  # belly
    b.cap((0.06, 0, 0.9), (0.05, 0, 0.6), 0.06)  # the front opening
    return b


def hobo_hand_blob(s):
    """An open hand with four separate fingers and a thumb, palm forward."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0022)
    b.cap((0, y, WRIST[1] + 0.03), (0, y, WRIST[1] - 0.02), 0.018)  # wrist
    b.ell((0.0, y - s * 0.004, WRIST[1] - 0.045), (0.032, 0.017, 0.036), stiffness=3)  # palm
    for i, spread in enumerate((-0.028, -0.009, 0.01, 0.028)):
        knuckle = Vector((spread, y - s * 0.004, WRIST[1] - 0.08))
        b.cap(knuckle, knuckle + Vector((0, -s * 0.006, -0.045)), 0.0068, stiffness=4)
        b.ball(knuckle + Vector((0, -s * 0.006, -0.055)), 0.0055, stiffness=4)
    b.cap((0.02, y - s * 0.02, WRIST[1] - 0.05), (0.028, y - s * 0.032, WRIST[1] - 0.09), 0.008, stiffness=4)
    return b


def pants_blob(s):
    """One leg of torn trousers, a tear at the knee showing the skin."""
    y = s * HIP[0]
    b = Blob(resolution=0.006)
    b.ell((-0.025, s * 0.05, 0.5), (0.09, 0.07, 0.07))  # seat
    b.cap((0, y, HIP[1] - 0.05), (0, y, KNEE[1]), 0.064)
    b.ell((0.01, y + s * 0.004, 0.43), (0.068, 0.064, 0.1), stiffness=3)  # thigh
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.01), 0.052)
    b.ell((-0.012, y, 0.21), (0.05, 0.052, 0.08), stiffness=3)  # calf
    b.ell((0.0, y, 0.09), (0.06, 0.058, 0.02), stiffness=4)  # ragged hem
    b.ell((0.005, y + s * 0.01, KNEE[1] - 0.02), (0.04, 0.04, 0.03), stiffness=4, negative=True)  # the knee tear
    return b


def boot_blob(s):
    """A worn, scuffed boot."""
    y = s * HIP[0]
    b = Blob(resolution=0.004)
    b.ell((0.04, y, 0.04), (0.09, 0.046, 0.042), stiffness=3)
    b.ell((0.115, y, 0.03), (0.05, 0.045, 0.03), stiffness=3)  # toe
    b.ell((-0.03, y, 0.045), (0.042, 0.042, 0.05), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.13), 0.044)  # shaft
    b.ell((0.05, y, -0.09), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat sole
    return b


def face(m):
    def on_skin(y, z, lift):
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.03, 1.074, 0)
        eye = socket - Vector((0.011, 0, 0))
        m.part(uv_ellipsoid(m.bm, eye, (0.0115,) * 3, segments=(16, 10)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.01, 0, 0)), (0.0023, 0.0068, 0.0068), segments=(14, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0122, 0, 0)), (0.0011, 0.0032, 0.0032), segments=(10, 6)), "head", "Pupil")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0, 0, 0.004)), (0.0122, 0.014, 0.01), segments=(16, 10)), "head", "Skin")
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.012, 1.098), (0.03, 1.103), (0.05, 1.098))]
        m.part(tube(m.bm, brow, [0.0045, 0.006, 0.0038], sides=8), "head", "Hair")
    # A red drinker's nose tip.
    m.part(uv_ellipsoid(m.bm, on_skin(0, 1.04, 0.004), (0.013, 0.015, 0.012), segments=(14, 8)), "head", "Lip")
    lip = on_skin(0, 1.008, -0.004)
    m.part(uv_ellipsoid(m.bm, lip, (0.008, 0.017, 0.005), segments=(14, 8)), "head", "Lip")


def seams_and_grime(m, on_coat):
    """Stitch lines down the coat's front, and grime stains at the hem and elbows."""
    for s, depth in ((1, 0.004), (-1, 0.002)):
        line = []
        for i in range(12):
            t = i / 11
            y = s * (0.09 - 0.02 * t)
            z = 0.84 - 0.42 * t
            hit = m.hit("coat", (0.5, y, z), (-1, 0, 0))
            if hit[0] is None:
                continue
            line.append(hit[0] + hit[1] * depth)
        if len(line) >= 2:
            verts = tube(m.bm, line, [0.003] * len(line), sides=6)
            m.weigh(verts, on_coat)
            m.paint(verts, "Coat")
    for y0, z0 in ((0.0, 0.44), (0.13, 0.40), (-0.13, 0.42), (0.0, 0.62)):
        hit = m.hit("coat", (0.4, y0, z0), (-1, 0, 0))
        if hit[0] is None:
            continue
        patch = uv_ellipsoid(m.bm, hit[0] + hit[1] * 0.004, (0.05, 0.04, 0.008), segments=(14, 8))
        m.weigh(patch, on_coat)
        m.paint(patch, "Grime", smooth=False)


def bottle(m):
    """A multi-part bottle along +X from the grip: glass body, paper label, red cap."""
    bm = m.bm

    def at(x, r, y=0.0, z=0.0):
        return GRIP + Vector((x, y, z))

    def rod(x0, x1, r, mat, sides=14):
        m.part(tube(bm, [at(x0, r), at(x1, r)], [r, r], sides=sides), "bottle", mat)

    rod(0.005, 0.02, 0.018, "Cap")  # the cap
    rod(0.02, 0.05, 0.013, "Bottle")  # the neck
    rod(0.05, 0.09, 0.02, "Bottle")  # the shoulder
    rod(0.09, 0.16, 0.026, "Bottle")  # the body
    # The label, wrapped around the body.
    label = ring_band(bm, lambda z: at(0.125, 0.0265) + Vector((0, 0, z)), lambda a, z: 0.0268, -0.028, 0.028, rows=2, sides=20)
    m.weigh(label, "bottle")
    m.paint(label, "Label")
    # A flat base.
    base = bmesh.ops.create_circle(bm, cap_ends=True, segments=14, radius=0.026, matrix=Matrix.Translation(at(0.16, 0)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))["verts"]
    m.weigh(base, "bottle")
    m.paint(base, "Bottle", smooth=False)


def cart(m):
    """A beat-up shopping cart: a wire basket, a handle, four legs and four casters."""
    bm = m.bm
    p = CART_PIVOT

    def at(x, y, z):
        return p + Vector((x, y, z))

    def bar(a, b, r, mat, sides=8):
        m.part(tube(bm, [at(*a), at(*b)], [r, r], sides=sides), "cart", mat)

    def ring(center, r, z, mat, sides=16):
        loop = [at(center[0] + r * math.cos(a), center[1] + r * math.sin(a), z) for a in (2 * math.pi * i / sides for i in range(sides + 1))]
        m.part(tube(bm, loop, [0.004] * len(loop), sides=6), "cart", mat)

    # The basket: two hoops and the slanting sides, as wire bars.
    ring((0.0, 0.0), 0.22, 0.30, "Cart")
    ring((0.0, 0.0), 0.17, 0.10, "Cart")
    for i in range(8):
        a = 2 * math.pi * i / 8
        bar((0.17 * math.cos(a), 0.17 * math.sin(a), 0.10), (0.22 * math.cos(a), 0.22 * math.sin(a), 0.30), 0.004, "Cart")
        bar((0.0, 0.0, 0.30), (0.22 * math.cos(a), 0.22 * math.sin(a), 0.30), 0.004, "Cart")
    # The handle, sweeping back toward him.
    for side in (-1, 1):
        bar((side * 0.22, 0.0, 0.30), (side * 0.20, 0.0, 0.06), 0.006, "Cart")
    bar((-0.2, 0.0, 0.06), (0.2, 0.0, 0.06), 0.008, "CartTrim")
    # Four legs and caster wheels.
    for x in (-0.2, 0.2):
        for y in (-0.16, 0.16):
            bar((x, y, 0.06), (x, y, -0.04), 0.007, "Cart")
            wheel = bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.035, radius2=0.035, depth=0.012,
                                          matrix=Matrix.Translation(at(x, y, -0.05)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))["verts"]
            m.weigh(wheel, "cart")
            m.paint(wheel, "CartWheel", smooth=False)
    # The under-tray.
    bar((-0.16, -0.12, 0.02), (0.16, -0.12, 0.02), 0.004, "Cart")
    bar((-0.16, 0.12, 0.02), (0.16, 0.12, 0.02), 0.004, "Cart")


def hobo_mesh():
    m = Model()
    m.blob("head", head_blob(), 0.5, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    m.blob("stubble", stubble_blob(), 0.35, "Stubble", "head")
    m.blob("shirt", shirt_blob(), 0.25, "Body", by_distance("hips", "spine"))
    coat = m.blob("coat", coat_blob(), 0.25, "Coat", by_distance("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        m.blob(f"sleeve.{side}", coat_sleeve_blob(s), 0.25, "Coat", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", hobo_hand_blob(s), 0.3, "Skin", f"forearm.{side}")
        m.blob(f"leg.{side}", pants_blob(s), 0.25, "Pants", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"boot.{side}", boot_blob(s), 0.3, "Shoe", f"foot.{side}")
    face(m)
    seams_and_grime(m, m.weights_near(coat))
    bottle(m)
    cart(m)

    mesh = bpy.data.meshes.new("HoboMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    return mesh


def materials():
    make_textures()
    mats = []
    for name, (color, rough, metal) in MATERIALS.items():
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.diffuse_color = color
        if mat.node_tree is None:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        if name == "Coat":
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Metallic"].default_value = metal
            tree = mat.node_tree
            color_img = bpy.data.images.load(COAT_PATH)
            color_img.colorspace_settings.name = "sRGB"
            color_tex = tree.nodes.new("ShaderNodeTexImage")
            color_tex.image = color_img
            tree.links.new(color_tex.outputs["Color"], bsdf.inputs["Base Color"])
            rough_img = bpy.data.images.load(COAT_ROUGH_PATH)
            rough_img.colorspace_settings.name = "Non-Color"
            rough_tex = tree.nodes.new("ShaderNodeTexImage")
            rough_tex.image = rough_img
            tree.links.new(rough_tex.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = rough
            bsdf.inputs["Metallic"].default_value = metal
        mats.append(mat)
    return mats


# --- Rig --------------------------------------------------------------------


def build_rig(mesh):
    rig = bpy.data.objects.new("Fighter", bpy.data.armatures.new("HoboRig"))
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

    body = bpy.data.objects.new("Hobo", mesh)
    bpy.context.scene.collection.objects.link(body)
    body.parent = rig
    for name in BONE_NAMES:
        body.vertex_groups.new(name=name)
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"

    # UVs for the coat's grime/roughness textures.
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66))
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


# --- Poses ------------------------------------------------------------------


def hobo_guard():
    """A slouchy, loose stance: knees bent, fists up but lazy."""
    pose = guard(drop=0.05, lean=-4)
    pose.update({"head": 8, "upper_arm.R": 42, "forearm.R": 92, "upper_arm.L": 24, "forearm.L": 100})
    return pose


def bottle_in(pose, facing=0):
    """Shows the bottle in the right fist, its neck pointing `facing` degrees."""
    pitch = lambda bone: (lambda v: v[0] if isinstance(v, tuple) else v)(pose.get(bone, 0))  # noqa: E731
    chain = sum(pitch(b) for b in ("hips", "spine", "upper_arm.R", "forearm.R"))
    return with_(pose, bottle_scale=1, bottle=facing - chain)


def cart_in(pose):
    return with_(pose, cart_scale=1)


S = hobo_guard()
CROUCH = with_(crouch(0.16), head=14)
AIR_S = with_(AIR, head=8, upper_arm_R=55, forearm_R=60, upper_arm_L=-30, forearm_L=90)
FLINCH_S = with_(FLINCH, head=24)
HOLD = with_(S, spine=-6, head=8, upper_arm_R=70, forearm_R=50, upper_arm_L=65, forearm_L=55)
STRUGGLE = with_(S, spine=15, head=12, upper_arm_R=40, forearm_R=90, upper_arm_L=-30, forearm_L=100)
HELPLESS = with_(AIR_S, spine=10, head=-12, upper_arm_R=150, forearm_R=30, upper_arm_L=140, forearm_L=40)
SIDESTEP = with_(crouch(0.08), spine=(-10, 70, 0), head=(0, -40, 0))
BALL = with_(crouch(0.3), spine=-60, head=40, upper_arm_R=60, forearm_R=130, upper_arm_L=60, forearm_L=130)
AIRDODGE = with_(AIR_S, spine=-10, upper_arm_R=60, forearm_R=120, upper_arm_L=55, forearm_L=125, thigh_R=70, shin_R=-120)
DIZZY = with_(S, spine=(-15, 0, 10), head=(-20, 0, 15), upper_arm_R=-5, forearm_R=10, upper_arm_L=-5, forearm_L=10)
SHIELD = with_(guard(drop=0.06, lean=-5), upper_arm_R=60, forearm_R=110, upper_arm_L=55, forearm_L=115)

# A few drunk-specific extremes.
SLAP = with_(S, spine=-12, head=14, upper_arm_R=120, forearm_R=20, upper_arm_L=10, forearm_L=110)
BACKHAND_SLAP = with_(S, spine=-10, head=14, upper_arm_L=120, forearm_L=20, upper_arm_R=15, forearm_R=105)
SHOVE = with_(S, hips_loc=(0.08, -0.06), spine=-22, head=18, upper_arm_R=95, forearm_R=0, upper_arm_L=90, forearm_L=0)
PUNCH = with_(S, hips_loc=(0.05, -0.05), spine=-16, head=12, upper_arm_R=88, forearm_R=0, upper_arm_L=-5, forearm_L=120)
UP_SWING = with_(S, spine=6, head=-8, upper_arm_R=160, forearm_R=20, upper_arm_L=40, forearm_L=60)
TRIP = planted(with_(crouch(0.18), spine=-28, head=22, upper_arm_R=-30, forearm_R=40, thigh_R=10, shin_R=-20), 0.55, -0.2)
STUMBLE = planted(with_(guard(drop=0.07, lean=-30), hips_loc=(0.06, -0.07), upper_arm_R=90, forearm_R=20, upper_arm_L=70, forearm_L=30), 0.3, -0.3)
BOTTLE_WIND = bottle_in(planted(with_(S, hips_loc=(-0.04, -0.07), spine=14, head=-10, upper_arm_R=-55, forearm_R=110), 0.2, -0.2), 160)
BOTTLE_SWING = bottle_in(planted(with_(S, hips_loc=(0.1, -0.08), spine=-24, head=18, upper_arm_R=98, forearm_R=0), 0.3, -0.22), -20)
HEAVE_WIND = bottle_in(with_(crouch(0.14), upper_arm_R=-15, forearm_R=40), 40)
HEAVE = bottle_in(planted(with_(S, hips_loc=(0, 0.02), spine=4, head=-12, upper_arm_R=172, forearm_R=0), 0.06, -0.06), 90)
SPIN_WIND = planted(with_(crouch(0.2), spine=-10, upper_arm_R=-30, forearm_R=20, upper_arm_L=40), 0.28, -0.28)
SPIN_FRONT = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=94, forearm_R=0, upper_arm_L=-60), 0.36, -0.3)
SPIN_BACK = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=-82, forearm_R=0, upper_arm_L=60), 0.3, -0.36)
AIR_TUCK = with_(AIR_S, thigh_R=80, shin_R=-120, thigh_L=60, shin_L=-110)
FLAIL = with_(AIR_S, spine=-8, upper_arm_R=110, forearm_R=30, upper_arm_L=-100, forearm_L=30)
HAYMAKER = with_(AIR_S, spine=-22, head=18, upper_arm_R=96, forearm_R=0, upper_arm_L=-60)
BACKHAND = with_(AIR_S, spine=-22, head=28, upper_arm_R=-78, forearm_R=0, upper_arm_L=70, forearm_L=30)
UP_FLAIL = with_(AIR_S, spine=14, head=-14, upper_arm_R=165, forearm_R=0)
STOMP = with_(AIR_S, spine=0, thigh_R=0, shin_R=0, foot_R=-50, thigh_L=0, shin_L=0, foot_L=-50, upper_arm_R=150, upper_arm_L=145)
THROW_WIND = bottle_in(planted(with_(S, hips_loc=(-0.04, -0.05), spine=14, head=-12, upper_arm_R=-55, forearm_R=95), 0.17, -0.2), 40)
THROW_RELEASE = planted(with_(S, hips_loc=(0.08, -0.07), spine=-18, head=12, upper_arm_R=95, forearm_R=5), 0.28, -0.2)
CART_LOW = cart_in(with_(crouch(0.2), spine=-22, head=16, upper_arm_R=30, forearm_R=90, upper_arm_L=30, forearm_L=90))
CART_CHARGE = cart_in(planted(with_(guard(drop=0.1, lean=-28), hips_loc=(0.1, -0.1), head=20, upper_arm_R=70, forearm_R=70, upper_arm_L=70, forearm_L=70), 0.32, -0.28))
FIZZ_SHAKE = with_(crouch(0.14), upper_arm_R=-20, forearm_R=60, upper_arm_L=-20, forearm_L=60)
FIZZ_UP = with_(AIR_S, spine=6, head=-14, upper_arm_R=175, forearm_R=0, upper_arm_L=40, forearm_L=30)
PASSED_OUT = planted(with_(crouch(0.28), spine=-70, head=30, upper_arm_R=90, forearm_R=60, upper_arm_L=-90, forearm_L=60), 0.25, -0.3)
JOLT_WIND = with_(S, spine=-6, upper_arm_R=150, forearm_R=30, upper_arm_L=20, forearm_L=100)
JOLT = with_(S, hips_loc=(0.06, -0.05), spine=-20, head=16, upper_arm_R=100, forearm_R=0, upper_arm_L=-30, forearm_L=60)
REACH = planted(with_(S, hips_loc=(0.06, -0.06), spine=-15, head=10, upper_arm_R=85, forearm_R=10, upper_arm_L=80, forearm_L=15))
DASH_REACH = planted(with_(guard(drop=0.08, lean=-28), hips_loc=(0.1, -0.08), upper_arm_R=95, forearm_R=5, upper_arm_L=90, forearm_L=10), 0.3, -0.25)
HILT_SHAKE = with_(HOLD, spine=-14, head=12, upper_arm_R=90, forearm_R=25)
PUSH = planted(with_(HOLD, hips_loc=(0.08, -0.06), spine=-20, head=12, upper_arm_R=95, forearm_R=0, upper_arm_L=90, forearm_L=0), 0.25, -0.15)
SLING = planted(with_(HOLD, spine=(-10, 90, 0), upper_arm_R=100, upper_arm_L=95, forearm_R=0, forearm_L=0), 0.1, -0.1)
LIFT = planted(with_(HOLD, hips_loc=(0, 0), spine=10, head=-15, upper_arm_R=175, forearm_R=0, upper_arm_L=170, forearm_L=0), 0.08, -0.08)
SLAM = planted(with_(crouch(0.15), spine=-35, head=25, upper_arm_R=60, upper_arm_L=55, forearm_R=0, forearm_L=0), 0.2, -0.2)


def walk(stride, lift, drop, swing, phase, run):
    pose = walk_key(stride, lift, drop, swing, phase)
    return with_(pose, head=10, upper_arm_R=-30 + (25 if run else 0), forearm_R=40, upper_arm_L=-30, forearm_L=40)


ANIMATIONS = {
    "idle": cycle(60, [S, with_(S, upper_arm_R=44, head=6)]),
    "walk": cycle(40, [walk(0.12, 0.06, d, 20, i, False) for i, d in enumerate((0.04, 0.025, 0.04, 0.025))]),
    "run": cycle(24, [walk(0.2, 0.12, d, 42, i, True) for i, d in enumerate((0.06, 0.03, 0.06, 0.03))]),
    "jumpsquat": [(1, guard(drop=0.07, lean=-12)), (5, CROUCH)],
    "air": cycle(40, [AIR_S, with_(AIR_S, thigh_R=60, shin_R=-100, upper_arm_R=50)]),
    "land": [(1, CROUCH), (5, S)],
    "crouch": cycle(60, [CROUCH, with_(CROUCH, hips_loc=(0, -0.165), head=10)]),
    "hitstun": cycle(20, [FLINCH_S, with_(FLINCH_S, spine=26, head=30)]),
    "shield": cycle(40, [SHIELD, with_(SHIELD, upper_arm_R=62, upper_arm_L=57)]),
    "dizzy": cycle(60, [DIZZY, with_(DIZZY, spine=(-15, 0, -10), head=(-20, 0, -15))]),
    "specialfall": cycle(30, [HELPLESS, with_(HELPLESS, upper_arm_R=165, upper_arm_L=125)]),
    "grab_hold": cycle(40, [HOLD, with_(HOLD, upper_arm_R=73, upper_arm_L=68, spine=-7)]),
    "grabbed": cycle(16, [STRUGGLE, with_(STRUGGLE, spine=20, head=15)]),
    # Slap chain: 20 / 20 / 32 frames.
    "hobo_slap": [(1, S), (3, SLAP), (4, with_(SLAP, upper_arm_R=70)), (6, SLAP), (12, with_(S, upper_arm_R=60)), (20, S)],
    "hobo_slap2": [(1, SLAP), (3, BACKHAND_SLAP), (5, BACKHAND_SLAP), (7, with_(BACKHAND_SLAP, upper_arm_L=70)), (12, S), (20, S)],
    "hobo_slap3": [(1, BACKHAND_SLAP), (3, with_(S, hips_loc=(-0.02, -0.04))), (7, SHOVE), (9, SHOVE), (20, SHOVE), (32, S)],
    # Punch (28), up swing (32), trip (24), stumble (40).
    "hobo_punch": [(1, S), (3, with_(S, spine=4, upper_arm_R=-10)), (8, PUNCH), (10, PUNCH), (18, with_(S, upper_arm_R=50)), (28, S)],
    "hobo_up_swing": [(1, S), (4, with_(S, upper_arm_R=60)), (7, UP_SWING), (14, UP_SWING), (22, with_(S, upper_arm_R=90)), (32, S)],
    "hobo_trip": [(1, CROUCH), (4, TRIP), (8, TRIP), (15, CROUCH), (24, CROUCH)],
    "hobo_stumble": [(1, walk(0.2, 0.12, 0.06, 42, 0, True)), (5, STUMBLE), (12, STUMBLE), (20, with_(S, spine=-14)), (40, S)],
    # Smashes: bottle swing (charge 12), up heave (charge 8), spin flail (charge 6).
    "hobo_bottle_swing": [(1, S), (8, BOTTLE_WIND), (12, BOTTLE_WIND), (16, BOTTLE_SWING), (18, BOTTLE_SWING), (30, with_(BOTTLE_SWING, upper_arm_R=70)), (50, S)],
    "hobo_up_heave": [(1, S), (5, HEAVE_WIND), (8, HEAVE_WIND), (12, HEAVE), (16, HEAVE), (28, with_(HEAVE, upper_arm_R=130)), (48, S)],
    "hobo_spin_flail": [(1, S), (4, SPIN_WIND), (6, SPIN_WIND), (10, SPIN_FRONT), (12, SPIN_FRONT), (14, with_(SPIN_FRONT, upper_arm_R=20)), (15, SPIN_BACK), (17, SPIN_BACK), (30, CROUCH), (46, S)],
    # Aerials.
    "hobo_flail": [(1, AIR_S), (3, with_(AIR_TUCK, upper_arm_R=60)), (5, FLAIL), (8, with_(FLAIL, upper_arm_R=140)), (16, with_(FLAIL, upper_arm_R=200)), (26, with_(AIR_S, spine=5)), (38, AIR_S)],
    "hobo_haymaker": [(1, AIR_S), (6, with_(AIR_S, upper_arm_R=175, forearm_R=25)), (10, HAYMAKER), (13, HAYMAKER), (24, with_(HAYMAKER, upper_arm_R=60)), (42, AIR_S)],
    "hobo_backhand": [(1, AIR_S), (5, with_(AIR_S, upper_arm_R=25, forearm_R=70)), (8, BACKHAND), (11, with_(BACKHAND, upper_arm_R=-58)), (22, BACKHAND), (36, AIR_S)],
    "hobo_up_flail": [(1, AIR_S), (3, with_(AIR_S, upper_arm_R=70)), (6, UP_FLAIL), (10, UP_FLAIL), (20, with_(AIR_S, spine=10)), (34, AIR_S)],
    "hobo_stomp": [(1, AIR_S), (8, with_(AIR_S, thigh_R=95, shin_R=-135, thigh_L=85, shin_L=-125)), (13, STOMP), (16, STOMP), (28, with_(AIR_S, spine=0)), (46, AIR_S)],
    # Specials.
    "hobo_bottle_throw": [(1, S), (4, bottle_in(with_(S, spine=-4, upper_arm_R=25, forearm_R=105), 70)), (10, THROW_WIND), (12, THROW_RELEASE), (22, THROW_RELEASE), (36, S)],
    "hobo_cart_charge": [(1, S), (5, CART_LOW), (7, CART_CHARGE), (20, CART_CHARGE), (28, cart_in(with_(S, spine=-10, upper_arm_R=40, forearm_R=80, upper_arm_L=40, forearm_L=80))), (44, S)],
    "hobo_fizz_rocket": [(1, S), (3, FIZZ_SHAKE), (4, FIZZ_SHAKE), (5, FIZZ_UP), (18, FIZZ_UP), (28, with_(HELPLESS, upper_arm_R=130)), (44, HELPLESS)],
    "hobo_passed_out": [(1, S), (6, PASSED_OUT), (8, PASSED_OUT), (28, PASSED_OUT), (38, with_(PASSED_OUT, spine=-40)), (46, S)],
    "hobo_jolt": [(1, JOLT_WIND), (4, with_(JOLT_WIND, upper_arm_R=120)), (5, JOLT), (8, JOLT), (18, with_(S, upper_arm_R=70)), (30, S)],
    # Grab / dash grab / pummel / throws.
    "hobo_grab": [(1, S), (6, REACH), (9, REACH), (18, HOLD), (30, S)],
    "hobo_dash_grab": [(1, walk(0.2, 0.12, 0.06, 42, 0, True)), (8, DASH_REACH), (11, DASH_REACH), (25, with_(HOLD, spine=-12)), (40, S)],
    "hobo_pummel": [(1, HOLD), (3, HILT_SHAKE), (6, HILT_SHAKE), (16, HOLD)],
    "hobo_throw_forward": [(1, HOLD), (8, with_(HOLD, spine=8)), (13, PUSH), (19, PUSH), (32, S)],
    "hobo_throw_back": [(1, HOLD), (9, with_(HOLD, spine=(0, 60, 0))), (16, SLING), (22, SLING), (38, S)],
    "hobo_throw_up": [(1, HOLD), (6, with_(crouch(0.1), upper_arm_R=60, upper_arm_L=60)), (12, LIFT), (18, LIFT), (34, S)],
    "hobo_throw_down": [(1, HOLD), (7, with_(HOLD, spine=-10, thigh_R=88, shin_R=-95)), (15, SLAM), (20, SLAM), (34, S)],
    # Dodges.
    "spotdodge": [(1, S), (3, SIDESTEP), (17, SIDESTEP), (26, S)],
    "roll_f": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "roll_b": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "airdodge": [(1, AIR_S), (4, AIRDODGE), (25, AIRDODGE), (34, AIR_S), (40, AIR_S)],
}


def apply_pose(rig, pose):
    for pb in rig.pose.bones:
        value = pose.get(pb.name, 0)
        pitch, twist, spread = value if isinstance(value, tuple) else (value, 0, 0)
        pb.rotation_euler = (math.radians(-pitch), math.radians(twist), math.radians(spread))
        pb.location = (0, 0, 0)
    fwd, up = pose.get("hips_loc", (0, 0))
    rig.pose.bones["hips"].location = (0, up, fwd)
    rig.pose.bones["bottle"].scale = (pose.get("bottle_scale", 0),) * 3
    rig.pose.bones["cart"].scale = (pose.get("cart_scale", 0),) * 3


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
            rig.pose.bones["bottle"].keyframe_insert("scale", frame=frame, group="bottle")
            rig.pose.bones["cart"].keyframe_insert("scale", frame=frame, group="cart")
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
    rig = build_rig(hobo_mesh())
    build_actions(rig)
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)


if __name__ == "__main__":
    main()
