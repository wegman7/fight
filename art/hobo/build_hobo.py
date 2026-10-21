"""Builds the drunk hobo: a weathered, bearded drifter in a knit beanie, a layered,
tattered overcoat over a sweater, saggy patched trousers held up with rope, fingerless
gloves and worn-out shoes, with a bottle in his near hand and a shopping cart he pulls
out for one move. Then his armature and one action per pose name the sim reports
(`Fighter::anim()`). Saves `hobo.blend` next to this script and exports
`godot/models/hobo.glb`.

    blender --background --factory-startup --python art/hobo/build_hobo.py

He stands on the chef's skeleton (same joints, same 1.2 m), so the shapes, pose helpers
and conventions come from `art/fighter/build_fighter.py` (see its README). On top of it
are two props, each scaled to 0 except in the moves that use them: `bottle` (the right
fist) and `cart` (in front of his hips).

His cloth and skin get their look from seeded, script-generated textures (`make_textures`)
wired as image textures, so they survive the glTF export: albedo, roughness and normal
maps for the coat, albedo and pore/wrinkle normals for the skin, knit stitches for the
beanie and gloves, a twill for the trousers and a plaid for the patches. Every textured
material tiles them through one Mapping node, which exports as KHR_texture_transform.
The `Body` material is the sweater under the coat, which gets the player's colour in game.

Besides the shared poses there are four ledge actions, timed and positioned against the
sim's ledge getups (see "Ledge actions" below): `ledge_hang`, `ledge_climb`, `ledge_roll` and
`ledge_attack`.
"""

import math
import os
import random
import struct
import sys
import zlib

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "hobo.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "hobo.glb")

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
H = 1.2  # his sim hurtbox height (FighterParams::HOBO.height 12 x SCALE 0.1)

# The chef's bones, minus the pie, plus the bottle (right fist) and the shopping cart
# (in front of the hips).
GRIP = Vector((0.0, -SHOULDER[0], WRIST[1] - FIST))
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONES.append(("bottle", "forearm.R", tuple(GRIP), tuple(GRIP + Vector((0.14, 0, 0))), FWD))
CART_PIVOT = Vector((0.34, 0.0, 0.52))
BONES.append(("cart", "hips", tuple(CART_PIVOT), tuple(CART_PIVOT + Vector((0.0, 0, 0.24))), UP))
BONE_NAMES = [b[0] for b in BONES]
SEGMENTS = {b[0]: (Vector(b[2]), Vector(b[3])) for b in BONES}

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the
# sweater) with the player's color; the rest keep their own. Textured materials (see
# TEXTURES) take their colour and detail from the maps instead of the base colour.
MATERIALS = {
    "Body": ((0.42, 0.50, 0.32, 1), 0.92, 0.0),
    "Coat": ((0.13, 0.095, 0.06, 1), 0.92, 0.0),
    "Lining": ((0.025, 0.02, 0.016, 1), 1.0, 0.0),
    "Patch": ((0.2, 0.1, 0.08, 1), 0.9, 0.0),
    "Thread": ((0.5, 0.44, 0.33, 1), 0.85, 0.0),
    "Skin": ((0.6, 0.38, 0.27, 1), 0.55, 0.0),
    "Ruddy": ((0.62, 0.27, 0.22, 1), 0.5, 0.0),
    "Lip": ((0.2, 0.09, 0.075, 1), 0.5, 0.0),
    "Hair": ((0.07, 0.055, 0.04, 1), 0.55, 0.0),
    "Beard": ((0.075, 0.058, 0.045, 1), 0.62, 0.0),
    "Grey": ((0.2, 0.185, 0.17, 1), 0.65, 0.0),
    "Eye": ((0.72, 0.62, 0.52, 1), 0.08, 0.0),
    "Iris": ((0.12, 0.08, 0.04, 1), 0.15, 0.0),
    "Pupil": ((0.005, 0.005, 0.005, 1), 0.05, 0.0),
    "Beanie": ((0.2, 0.04, 0.035, 1), 0.95, 0.0),
    "Glove": ((0.06, 0.055, 0.05, 1), 0.95, 0.0),
    "Pants": ((0.05, 0.045, 0.035, 1), 0.9, 0.0),
    "Rope": ((0.36, 0.27, 0.15, 1), 0.9, 0.0),
    "Shoe": ((0.035, 0.022, 0.014, 1), 0.62, 0.0),
    "Sole": ((0.02, 0.018, 0.016, 1), 0.85, 0.0),
    "Lace": ((0.3, 0.26, 0.2, 1), 0.85, 0.0),
    "Sock": ((0.22, 0.2, 0.17, 1), 0.95, 0.0),
    "Button": ((0.04, 0.025, 0.015, 1), 0.35, 0.0),
    "Brass": ((0.55, 0.4, 0.16, 1), 0.38, 0.9),
    "Bottle": ((0.06, 0.2, 0.08, 1), 0.06, 0.0),
    "Label": ((0.6, 0.5, 0.3, 1), 0.75, 0.0),
    "Cap": ((0.45, 0.08, 0.06, 1), 0.38, 0.75),
    "Cart": ((0.55, 0.55, 0.58, 1), 0.35, 0.95),
    "CartWheel": ((0.03, 0.03, 0.03, 1), 0.92, 0.0),
    "CartTrim": ((0.55, 0.08, 0.06, 1), 0.45, 0.4),
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


def by_dist(*bones, sharpness=5):
    """`chef.by_distance` on this skeleton's segments."""

    def weights(p):
        ws = sorted(((b, 1 / (chef.seg_dist(p, *SEGMENTS[b]) + 0.012) ** sharpness) for b in bones), key=lambda bw: -bw[1])[:3]
        total = sum(w for _, w in ws)
        return {b: w / total for b, w in ws if w / total > 0.02}

    return weights


# --- Procedural textures ------------------------------------------------------
# Seeded, tileable value noise (numpy), baked to PNGs next to this script. Every map
# tiles, so the Mapping node can repeat it across the body. Albedo PNGs are sRGB.

TEX = 512
# The UVs (smart project) run about 3.6 m of surface per UV unit, so a map tiled
# `tile` times repeats every 3.6 / tile m: 0.45 m for the coat, 0.3 m for the knit.
TEXTURES = {
    # material: {"tile": repeats per UV unit, "albedo": file, "rough": file, "normal": (file, strength)}
    "Coat": {"tile": 8, "albedo": "hobo_coat.png", "rough": "hobo_coat_rough.png", "normal": ("hobo_coat_normal.png", 1.0)},
    "Skin": {"tile": 12, "albedo": "hobo_skin.png", "normal": ("hobo_skin_normal.png", 0.25)},
    "Ruddy": {"tile": 12, "albedo": "hobo_ruddy.png", "normal": ("hobo_skin_normal.png", 0.25)},
    "Beard": {"tile": 16, "albedo": "hobo_beard.png", "normal": ("hobo_hair_normal.png", 0.8)},
    "Hair": {"tile": 16, "albedo": "hobo_hair.png", "normal": ("hobo_hair_normal.png", 0.8)},
    "Beanie": {"tile": 12, "albedo": "hobo_beanie.png", "normal": ("hobo_knit_normal.png", 1.0)},
    "Glove": {"tile": 14, "albedo": "hobo_glove.png", "normal": ("hobo_knit_normal.png", 1.0)},
    "Pants": {"tile": 8, "albedo": "hobo_pants.png", "normal": ("hobo_pants_normal.png", 1.0)},
    "Patch": {"tile": 5, "albedo": "hobo_patch.png", "normal": ("hobo_pants_normal.png", 0.7)},
}
_M32 = np.uint64(0xFFFFFFFF)


def _lattice(cx, cy, seed):
    x = np.arange(cx, dtype=np.uint64)[None, :]
    y = np.arange(cy, dtype=np.uint64)[:, None]
    n = (x * np.uint64(374761393) + y * np.uint64(668265263) + np.uint64((seed * 1442695040888963407) & 0xFFFFFFFF)) & _M32
    n = ((n ^ (n >> np.uint64(13))) * np.uint64(1274126177)) & _M32
    return ((n ^ (n >> np.uint64(16))) & _M32).astype(np.float64) / 0xFFFFFFFF


def _vnoise(cx, cy, seed, size=TEX):
    """Tileable value noise with cx by cy cells, in [0, 1]."""
    lat = _lattice(cx, cy, seed)

    def axis(c):
        p = np.arange(size) * c / size
        i0 = np.floor(p).astype(np.int64)
        t = p - i0
        return i0 % c, (i0 + 1) % c, t * t * (3 - 2 * t)

    x0, x1, tx = axis(cx)
    y0, y1, ty = axis(cy)
    a, b = lat[np.ix_(y0, x0)], lat[np.ix_(y0, x1)]
    c, d = lat[np.ix_(y1, x0)], lat[np.ix_(y1, x1)]
    tx, ty = tx[None, :], ty[:, None]
    return a + (b - a) * tx + (c - a) * ty + (a - b - c + d) * tx * ty


def _fbm(cells, octaves, seed, size=TEX, stretch=1):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        c = cells * 2**o
        total = total + amp * _vnoise(c * stretch, c, seed + 17 * o, size)
        norm += amp
        amp *= 0.5
    return total / norm


def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _grid(size=TEX):
    return np.arange(size)[None, :], np.arange(size)[:, None]


def _png(name, img, half=False):
    """Writes a float image (h, w, channels) in [0, 1] as an 8-bit PNG, `half` at half
    the resolution (for maps whose detail is coarse)."""
    img = np.asarray(img)
    if half:
        img = (img[0::2, 0::2] + img[1::2, 0::2] + img[0::2, 1::2] + img[1::2, 1::2]) / 4
    img = np.clip(img * 255 + 0.5, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        img = img[:, :, None]
    h, w, ch = img.shape

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))
    with open(os.path.join(HERE, name), "wb") as f:
        f.write(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, {1: 0, 3: 2}[ch], 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )


def _normal_png(name, height, strength):
    """A tangent-space normal map (OpenGL convention, +Y = up the image) from a
    tileable height field, `strength` texels of slope per unit of height."""
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * 0.5 * strength
    drow = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * 0.5 * strength
    n = np.stack([-dx, drow, np.ones_like(dx)], -1)  # image rows run down, V runs up
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    _png(name, n * 0.5 + 0.5)


def _tint(base, *layers):
    """Starts from colour `base` and blends in (colour, amount-array) layers."""
    img = np.ones((TEX, TEX, 3)) * np.array(base)
    for color, amount in layers:
        a = np.asarray(amount)[:, :, None]
        img = img * (1 - a) + np.array(color) * a
    return img


def make_textures():
    x, y = _grid()
    # Coat: a heavy wool twill, faded in places, with greasy grime stains (darker and
    # shinier) and fibre fuzz.
    stain, fade = _fbm(6, 4, 7), _fbm(4, 4, 31)
    fibre = _vnoise(256, 256, 5)
    twill = 0.5 + 0.5 * np.sin(2 * np.pi * (x + 2 * y) / 8)
    weft = 0.5 + 0.5 * np.sin(2 * np.pi * x / 4)
    grime = _smoothstep(0.5, 0.75, stain)
    worn = _smoothstep(0.55, 0.78, fade)
    coat = _tint((0.33, 0.27, 0.2), ((0.43, 0.38, 0.3), worn * 0.6), ((0.16, 0.13, 0.1), grime * 0.6))
    coat *= (0.86 + 0.1 * twill + 0.04 * weft + 0.1 * (fibre - 0.5))[:, :, None]
    _png("hobo_coat.png", coat)
    _png("hobo_coat_rough.png", np.clip(0.93 - 0.15 * grime + 0.06 * (fibre - 0.5), 0, 1), half=True)
    _normal_png("hobo_coat_normal.png", 0.7 * twill + 0.25 * weft + 0.5 * fibre + 6 * _fbm(8, 3, 13), 1.6)

    # Skin: weathered and sunburnt, blotchy with broken veins, sun spots and dirt;
    # pores under fine creases.
    blotch = _smoothstep(0.4, 0.85, _fbm(16, 3, 41)) * 0.6
    spots = _smoothstep(0.82, 0.95, _vnoise(64, 64, 43)) * 0.45
    dirt = _smoothstep(0.55, 0.85, _fbm(12, 3, 47)) * 0.3
    veins = _smoothstep(0.9, 0.98, 1 - np.abs(_fbm(24, 3, 49) - 0.5) * 2) * 0.35
    pores = _vnoise(170, 170, 53)
    creases = _fbm(4, 3, 59, stretch=1) * 0.3 + _vnoise(6, 70, 61) * 0.7
    shade = (0.92 + 0.08 * pores)[:, :, None]
    layers = (((0.68, 0.44, 0.36), blotch * 0.5), ((0.62, 0.3, 0.27), veins), ((0.45, 0.31, 0.22), spots), ((0.45, 0.39, 0.32), dirt))
    _png("hobo_skin.png", _tint((0.72, 0.53, 0.41), *layers) * shade)
    _png("hobo_ruddy.png", _tint((0.72, 0.43, 0.36), ((0.66, 0.32, 0.29), blotch), ((0.6, 0.22, 0.2), veins * 2), *layers[2:]) * shade)
    _normal_png("hobo_skin_normal.png", -0.9 * _smoothstep(0.55, 0.95, pores) + 0.25 * creases + 0.15 * _vnoise(256, 256, 63), 1.0)

    # Hair and beard: fine streaks of strands, the beard salted with grey.
    streak = _vnoise(160, 5, 85) * 0.6 + _vnoise(320, 9, 87) * 0.4
    strand = (0.55 + 0.6 * streak)[:, :, None]
    grey = _smoothstep(0.62, 0.8, _vnoise(90, 4, 89))
    _png("hobo_beard.png", np.clip(_tint((0.17, 0.13, 0.1), ((0.5, 0.47, 0.43), grey * 0.75)) * strand, 0, 1))
    _png("hobo_hair.png", np.clip(_tint((0.13, 0.1, 0.075), ((0.36, 0.33, 0.3), grey * 0.4)) * strand, 0, 1))
    _normal_png("hobo_hair_normal.png", 1.4 * streak + 0.2 * _vnoise(256, 256, 91), 2.0)

    # Knit: stocking stitch, columns of little V-shaped loops, 8 texels a stitch, with
    # fuzz and pilling.
    u, v = (x % 8) / 8, (y % 8) / 8
    lean = 0.24 * (v - 0.5)
    legs = np.maximum(np.exp(-(((u - 0.27 - lean) / 0.16) ** 2)), np.exp(-(((u - 0.73 + lean) / 0.16) ** 2)))
    loop = legs * (0.35 + 0.65 * np.sin(np.pi * v) ** 0.7)
    fuzz = _vnoise(256, 256, 67)
    pill = _smoothstep(0.85, 0.95, _vnoise(64, 64, 69))
    _normal_png("hobo_knit_normal.png", 1.6 * loop + 0.35 * fuzz + 0.8 * pill, 2.5)
    yarn = (0.62 + 0.38 * loop + 0.08 * (fuzz - 0.5))[:, :, None]
    dye = _fbm(3, 3, 71)
    _png("hobo_beanie.png", _tint((0.5, 0.17, 0.13), ((0.56, 0.3, 0.24), _smoothstep(0.5, 0.8, dye) * 0.7), ((0.2, 0.1, 0.08), grime * 0.4)) * yarn)
    _png("hobo_glove.png", _tint((0.3, 0.29, 0.27), ((0.4, 0.37, 0.33), _smoothstep(0.5, 0.8, dye) * 0.6), ((0.12, 0.1, 0.08), grime * 0.6)) * yarn)

    # Trousers: a dark cotton drill, worn pale in patches and darkened with dirt.
    drill = 0.5 + 0.5 * np.sin(2 * np.pi * (x - y) / 4)
    wear = _smoothstep(0.55, 0.8, _fbm(3, 4, 73))
    soil = _smoothstep(0.5, 0.78, _fbm(4, 4, 79))
    pants = _tint((0.25, 0.23, 0.19), ((0.38, 0.35, 0.29), wear * 0.8), ((0.1, 0.09, 0.07), soil * 0.7))
    _png("hobo_pants.png", pants * (0.88 + 0.12 * drill + 0.08 * (fibre - 0.5))[:, :, None])
    _normal_png("hobo_pants_normal.png", 0.6 * drill + 0.4 * fibre + 5 * _fbm(8, 3, 83), 1.4)

    # Patches: a faded red and green plaid flannel.
    check = lambda p, w: (np.abs(((p % 32) / 32) - 0.5) < w).astype(float)  # noqa: E731
    bands_x, bands_y = check(x, 0.12) + 0.5 * check(x + 9, 0.04), check(y, 0.12) + 0.5 * check(y + 9, 0.04)
    plaid = _tint((0.42, 0.12, 0.1), ((0.14, 0.2, 0.12), np.clip(bands_x * 0.6, 0, 1)), ((0.12, 0.16, 0.1), np.clip(bands_y * 0.6, 0, 1)),
                  ((0.6, 0.5, 0.36), (check(x + 16, 0.02) + check(y + 16, 0.02)).clip(0, 1) * 0.6), ((0.15, 0.12, 0.09), grime * 0.5))
    _png("hobo_patch.png", plaid * (0.9 + 0.1 * drill)[:, :, None], half=True)


# --- Shapes -----------------------------------------------------------------
# Hand frame: hanging hands, thumbs forward (+X), palms toward the body.


def head_blob():
    """A gaunt, weathered face: long and bony, hollow-cheeked, a drinker's nose."""
    b = Blob(resolution=0.0026)
    b.ell((-0.012, 0, 1.086), (0.085, 0.071, 0.088))  # cranium
    b.ell((0.03, 0, 1.03), (0.061, 0.055, 0.07))  # face
    b.ell((0.063, 0, 0.972), (0.024, 0.03, 0.019), stiffness=3)  # chin
    b.cap((-0.014, 0, 0.84), (0.0, 0, 0.99), 0.046)  # neck
    b.ball((0.036, 0, 0.94), 0.011, stiffness=4)  # Adam's apple
    for s in (1, -1):
        b.ell((0.058, s * 0.046, 1.054), (0.016, 0.018, 0.011), stiffness=3)  # cheekbones
        b.ell((0.06, s * 0.05, 1.012), (0.016, 0.012, 0.017), stiffness=5, negative=True)  # hollow cheeks
        b.ell((0.018, s * 0.066, 1.098), (0.02, 0.01, 0.02), stiffness=5, negative=True)  # sunken temples
        b.cap((-0.02, s * 0.053, 1.02), (0.057, s * 0.025, 0.973), 0.014, stiffness=3)  # jawline
        b.cap((0.083, s * 0.011, 1.098), (0.071, s * 0.052, 1.103), 0.0105, stiffness=3)  # brow ridge
        b.ball((0.075, s * 0.031, 1.074), 0.0135, stiffness=4, negative=True)  # eye socket
        b.ell((0.081, s * 0.032, 1.058), (0.006, 0.012, 0.0045), stiffness=4)  # bags under the eyes
        b.ell((0.097, s * 0.0145, 1.035), (0.009, 0.008, 0.0078), stiffness=4)  # nostril wings
        b.ell((0.101, s * 0.0085, 1.028), (0.0045, 0.003, 0.003), stiffness=6, negative=True)  # nostrils
        b.cap((0.093, s * 0.025, 1.036), (0.088, s * 0.031, 1.008), 0.0026, stiffness=6, negative=True)  # nose-to-mouth creases
        # Ears: a flat shell with a hollow and a lobe; the rim is a tube (`face`).
        b.ell((-0.012, s * 0.077, 1.062), (0.017, 0.01, 0.027), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-12 * s)))
        b.ell((-0.008, s * 0.086, 1.064), (0.009, 0.007, 0.015), stiffness=5, negative=True)
        b.ell((-0.008, s * 0.08, 1.036), (0.007, 0.005, 0.008), stiffness=4)  # lobe
    b.cap((0.085, 0, 1.09), (0.103, 0, 1.05), 0.0085, stiffness=3)  # nose bridge
    b.ball((0.107, 0, 1.04), 0.0145, stiffness=3)  # bulbous tip
    b.cap((0.094, -0.019, 1.007), (0.094, 0.019, 1.007), 0.003, stiffness=6, negative=True)  # mouth
    b.ell((0.093, 0, 1.014), (0.006, 0.019, 0.005), stiffness=4)  # upper lip
    b.ell((0.09, 0, 1.0), (0.008, 0.017, 0.0065), stiffness=4)  # lower lip
    return b


def hair_blob():
    """Lank, greasy hair under the beanie: the back of the head and over the ears."""
    b = Blob(resolution=0.004)
    b.ell((-0.035, 0, 1.08), (0.072, 0.074, 0.075))
    b.ell((-0.06, 0, 1.03), (0.04, 0.06, 0.05), stiffness=3)  # down the nape
    for s in (1, -1):
        b.ell((-0.01, s * 0.09, 1.06), (0.026, 0.02, 0.036), stiffness=4, negative=True)  # ears
    b.ell((0.05, 0, 1.05), (0.06, 0.09, 0.08), stiffness=4, negative=True)  # clear of the face
    return b


def beard_blob():
    """A full, unkempt beard: thick on the jaw, straggling down onto the chest."""
    b = Blob(resolution=0.003)
    b.ell((0.055, 0, 0.985), (0.048, 0.064, 0.048), stiffness=3)  # jaw and chin
    b.ell((0.058, 0, 0.945), (0.044, 0.054, 0.042), stiffness=3)  # under the chin
    b.ell((0.066, 0, 0.91), (0.034, 0.042, 0.036), stiffness=3)  # falling onto the chest
    for s in (1, -1):
        b.ell((0.024, s * 0.05, 1.016), (0.03, 0.017, 0.032), stiffness=3)  # cheeks
        b.cap((0.1, s * 0.004, 1.021), (0.093, s * 0.03, 0.996), 0.0085, stiffness=3)  # moustache, drooping
        b.ell((0.084, s * 0.04, 1.054), (0.032, 0.026, 0.022), stiffness=3, negative=True)  # clear of the cheekbones
    b.ell((0.1, 0, 1.003), (0.011, 0.016, 0.0055), stiffness=4, negative=True)  # the mouth shows
    b.ell((0.06, 0, 1.03), (0.042, 0.048, 0.02), stiffness=3, negative=True)  # behind the lips
    rng = random.Random(3)
    for _ in range(11):  # ragged clumps hanging off the bottom
        y = rng.uniform(-0.04, 0.04)
        top = Vector((0.06 + rng.uniform(-0.01, 0.015), y, 0.93))
        tip = top + Vector((rng.uniform(0.0, 0.02), y * 0.3 + rng.uniform(-0.01, 0.01), -rng.uniform(0.04, 0.07)))
        b.cap(top, tip, rng.uniform(0.007, 0.011), stiffness=3)
    return b


def coat_blob():
    """The overcoat's body: broad, hunched shoulders and an open front."""
    b = Blob(resolution=0.0055)
    b.ell((0.0, 0, 0.79), (0.105, 0.153, 0.112))  # chest
    b.ell((0.0, 0, 0.64), (0.108, 0.142, 0.12))  # waist
    b.ell((0.0, 0, 0.56), (0.11, 0.146, 0.1))  # hips, under the skirt's top
    b.ell((-0.07, 0, 0.82), (0.045, 0.09, 0.06))  # hunched back
    for s in (1, -1):
        b.ell((-0.005, s * 0.09, 0.86), (0.06, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.155, 0.84), (0.058, 0.045, 0.045))  # shoulder seam
        b.ell((-0.06, s * 0.06, 0.79), (0.045, 0.06, 0.07))  # shoulder blades
        b.ell((0.04, s * 0.11, 0.72), (0.04, 0.03, 0.06), stiffness=4, negative=True)  # drag folds under the arms
    b.ell((0.13, 0, 0.71), (0.05, 0.052, 0.23), stiffness=3, negative=True)  # open front
    return b


def sleeve_blob(s):
    """A baggy coat sleeve, bunched at the elbow, sagging under the arm."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.005)
    b.ell((0.0, y - s * 0.005, 0.84), (0.06, 0.06, 0.062))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.055)
    b.ell((0.012, y, 0.73), (0.04, 0.04, 0.06), stiffness=3)  # biceps fold
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.08), 0.051)
    b.ell((-0.012, y, 0.6), (0.042, 0.042, 0.055), stiffness=3)  # forearm
    b.ell((-0.05, y, 0.58), (0.05, 0.045, 0.1), stiffness=3)  # the hanging fold
    for z in (0.67, 0.625):  # bunched creases at the elbow
        b.ell((0.045, y, z), (0.012, 0.05, 0.006), stiffness=5, negative=True)
    return b


def sweater_blob():
    """The sweater (`Body`) showing where the coat hangs open."""
    b = Blob(resolution=0.005)
    b.ell((0.035, 0, 0.78), (0.08, 0.105, 0.055), stiffness=3)  # chest
    b.ell((0.05, 0, 0.64), (0.066, 0.095, 0.064), stiffness=3)  # belly
    b.cap((0.05, 0, 0.9), (0.045, 0, 0.56), 0.056)  # down the front opening
    for z in (0.74, 0.69, 0.62):  # slack folds
        b.ell((0.11, 0, z), (0.01, 0.06, 0.005), stiffness=5, negative=True)
    return b


def _hand_frame(s):
    y = s * SHOULDER[0]
    wrist = Vector((0, y, WRIST[1]))
    down, thumb, palm = Vector((0, 0, -1)), Vector((1, 0, 0)), Vector((0, -s, 0))

    def at(d, f, m):
        return wrist + down * d + thumb * f + palm * m

    return at, down, palm


FINGERS = (  # knuckle (down, across), segment lengths, radius
    (0.083, 0.025, (0.026, 0.017, 0.015), 0.0074),
    (0.085, 0.0085, (0.029, 0.019, 0.016), 0.0077),
    (0.083, -0.008, (0.027, 0.018, 0.015), 0.0072),
    (0.078, -0.0235, (0.021, 0.014, 0.013), 0.0063),
)
THUMB = ((0.012, 0.022, 0.004), (0.045, 0.037, 0.013), (0.067, 0.043, 0.019), (0.087, 0.042, 0.025))


def _finger_joints(s, finger):
    at, down, palm = _hand_frame(s)
    d, f, lengths, r = finger
    p = at(d, f, 0.0)
    joints, curl = [p], 0.0
    for i, length in enumerate(lengths):
        curl += (12, 20, 18)[i]
        p = p + (down * math.cos(math.radians(curl)) + palm * math.sin(math.radians(curl))) * length
        joints.append(p)
    return joints, r


def hand_blob(s):
    """A bony, weathered hand: three-jointed fingers, a little curled, and a thumb."""
    at, down, palm = _hand_frame(s)
    b = Blob(resolution=0.002)
    b.cap(at(-0.03, 0, 0), at(0.012, 0, 0), 0.018)  # wrist
    b.ell(at(0.046, 0.002, 0.0), (0.034, 0.014, 0.038), stiffness=3)  # palm
    b.ell(at(0.04, 0.02, 0.008), (0.012, 0.011, 0.02), stiffness=3)  # ball of the thumb
    for finger in FINGERS:
        joints, r = _finger_joints(s, finger)
        b.ball(joints[0] - palm * 0.004, r * 0.95, stiffness=3)  # knuckle
        for i, (a, c) in enumerate(zip(joints, joints[1:])):
            b.cap(a, c, r * (1, 0.9, 0.8)[i], stiffness=4)
    for i, (a, c) in enumerate(zip(THUMB, THUMB[1:])):
        b.cap(at(*a), at(*c), (0.0105, 0.0085, 0.0075)[i], stiffness=4)
    return b


def glove_blob(s):
    """Fingerless knit gloves: over the palm and the first joint of each finger."""
    at, down, palm = _hand_frame(s)
    b = Blob(resolution=0.0022)
    b.cap(at(-0.04, 0, 0), at(0.012, 0, 0), 0.022)  # cuff
    b.ell(at(0.046, 0.002, 0.0), (0.037, 0.017, 0.041), stiffness=3)
    b.ell(at(0.04, 0.02, 0.008), (0.014, 0.013, 0.022), stiffness=3)
    for finger in FINGERS:
        joints, r = _finger_joints(s, finger)
        b.cap(joints[0], joints[0].lerp(joints[1], 0.62), r + 0.0026, stiffness=4)
    b.cap(at(*THUMB[0]), at(*THUMB[1]).lerp(at(*THUMB[2]), 0.4), 0.0128, stiffness=4)
    return b


def pants_blob(s, tear):
    """One leg of saggy, baggy trousers: a low seat, a bagged knee and the slack
    pooled in folds over the shoe. `tear` rips the knee open."""
    y = s * HIP[0]
    b = Blob(resolution=0.0055)
    b.ell((-0.03, s * 0.05, 0.47), (0.095, 0.072, 0.078))  # sagging seat
    b.ell((0.0, s * 0.03, 0.445), (0.07, 0.05, 0.055))  # low crotch
    b.cap((0, y, HIP[1] - 0.05), (0, y, KNEE[1]), 0.067)
    b.ell((0.012, y + s * 0.004, 0.42), (0.07, 0.067, 0.1), stiffness=3)  # thigh
    b.ell((0.028, y, KNEE[1] + 0.005), (0.03, 0.05, 0.04), stiffness=3)  # bagged knee
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.02), 0.056)
    b.ell((-0.012, y, 0.21), (0.052, 0.054, 0.08), stiffness=3)  # calf
    b.ell((-0.058, y, KNEE[1] + 0.012), (0.018, 0.05, 0.006), stiffness=5, negative=True)  # crease behind the knee
    for z, dx, tilt in ((0.11, 0.006, 8), (0.155, -0.004, -10)):  # slack pooled in folds at the ankle
        b.ell((dx, y, z), (0.062, 0.06, 0.013), stiffness=4, rot=Quaternion((0, 1, 0), math.radians(tilt * s)))
    b.ell((0.012, y, 0.082), (0.07, 0.064, 0.018), stiffness=4)  # hem, breaking over the shoe
    if tear:
        b.ell((0.06, y + s * 0.006, KNEE[1] - 0.01), (0.03, 0.04, 0.028), stiffness=4, negative=True)
    return b


def shoe_blob(s, toe_hole):
    """A worn-out shoe upper, creased across the toes. `toe_hole` wears through it."""
    y = s * HIP[0]
    b = Blob(resolution=0.0035)
    b.ell((0.045, y, 0.047), (0.085, 0.044, 0.035), stiffness=3)  # vamp
    b.ell((0.118, y, 0.038), (0.054, 0.046, 0.026), stiffness=3)  # toe box, flattened
    b.ell((-0.028, y, 0.052), (0.04, 0.04, 0.045), stiffness=3)  # heel counter
    b.cap((0, y, 0.06), (0, y, 0.12), 0.042)  # ankle collar
    b.ell((0.05, y, -0.08), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat bottom, on the sole
    for x in (0.08, 0.1):  # flex creases
        b.cap((x, y - 0.045, 0.064 - (x - 0.08) * 0.4), (x + 0.012, y + 0.045, 0.064 - (x - 0.08) * 0.4), 0.0035, stiffness=6, negative=True)
    if toe_hole:
        b.ball((0.165, y - s * 0.012, 0.042), 0.014, stiffness=5, negative=True)
    return b


# --- Details built in bmesh ---------------------------------------------------


def decal(m, piece, hit, normal, outline, mat, lift, on, thickness=0.0, rows=5):
    """A patch conforming to `piece` around `hit`: `outline(angle)` gives its radius
    (in m) in the surface's tangent plane. Projected onto the surface by ray casts, lifted
    `lift` off it, with `thickness` of cloth. Returns the outer rim's points."""
    t1 = normal.cross(Vector((0, 0, 1)))
    t1 = (t1 if t1.length > 1e-3 else normal.cross(Vector((1, 0, 0)))).normalized()
    t2 = normal.cross(t1).normalized()
    sides = 20
    bm = m.bm
    grid, rim = [], []
    for i in range(rows + 1):
        ring = []
        for j in range(sides):
            a = 2 * math.pi * j / sides
            r = outline(a) * i / rows
            p = hit + (t1 * math.cos(a) + t2 * math.sin(a)) * r
            loc, n = m.hit(piece, p + normal * 0.05, -normal)
            loc = loc if loc is not None else p
            ring.append(loc + normal * lift)
            if i == rows:
                rim.append(loc + normal * (lift + 0.001))
        grid.append([bm.verts.new(p) for p in ring])
    center = grid[0][0]
    faces = []
    for v in grid[0][1:]:
        bm.verts.remove(v)
    for j in range(sides):
        faces.append(bm.faces.new((center, grid[1][j], grid[1][(j + 1) % sides])))
    for r0, r1 in zip(grid[1:], grid[2:]):
        for j in range(sides):
            faces.append(bm.faces.new((r0[j], r1[j], r1[(j + 1) % sides], r0[(j + 1) % sides])))
    verts = [center] + [v for r in grid[1:] for v in r]
    if thickness:
        solid = bmesh.ops.solidify(bm, geom=faces, thickness=thickness)
        verts += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
    m.weigh(verts, on)
    m.paint(verts, mat)
    return rim


def stitches(m, points, on, mat="Thread", every=2, r=0.0011):
    """A running stitch: short thread dashes along a closed loop of points."""
    for i in range(0, len(points), every):
        a, b = points[i], points[(i + 1) % len(points)]
        verts = tube(m.bm, [a, b], [r, r], sides=5)
        m.weigh(verts, on)
        m.paint(verts, mat)


def strands(m, roots, on, mat, rng, length=(0.015, 0.03), r0=0.0018, droop=0.5, out=None):
    """Loose tapered strands (frayed threads, stray hairs) from `roots`, each a
    (point, direction) pair, curling down under gravity."""
    for p, d in roots:
        d = d.normalized()
        length_ = rng.uniform(*length)
        pts, radii = [], []
        for k in range(5):
            t = k / 4
            bend = Vector((0, 0, -droop * t * t * length_)) + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * 0.15 * length_ * t
            pts.append(p + d * length_ * t + bend)
            radii.append(r0 * (1 - 0.8 * t))
        verts = tube(m.bm, pts, radii, sides=4)
        m.weigh(verts, on)
        m.paint(verts, mat)


def face(m):
    def on_skin(y, z, lift):
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.031, 1.074, 0)
        r = 0.0112
        eye = socket - Vector((r - 0.0045, 0, 0))
        m.part(uv_ellipsoid(m.bm, eye, (r,) * 3, segments=(18, 12)), "head", "Eye")
        gaze = Quaternion((0, 1, 0), math.radians(6))  # bleary, looking a little down
        iris_at = eye + gaze @ Vector((r - 0.0012, 0, 0))
        m.part(uv_ellipsoid(m.bm, iris_at, (0.0016, 0.0058, 0.0058), gaze, segments=(16, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + gaze @ Vector((r + 0.0002, 0, 0)), (0.0006, 0.0024, 0.0024), gaze, segments=(12, 6)), "head", "Pupil")
        # Lids: a shell round the eyeball with an almond-shaped opening, heavy and
        # drooping, and soft rims along its edges.
        lr = r + 0.0012
        upper = lambda yaw: 19 * math.cos(math.radians(yaw) * 90 / 46) - 1  # noqa: E731
        lower = lambda yaw: -17 * math.cos(math.radians(yaw) * 90 / 46) - 3  # noqa: E731
        shell = uv_ellipsoid(m.bm, eye, (lr,) * 3, segments=(28, 18))
        cut = []
        for f in {f for v in shell for f in v.link_faces}:
            d = (f.calc_center_median() - eye).normalized()
            yaw = math.degrees(math.atan2(d.y * s, d.x)) * s
            pitch = math.degrees(math.asin(max(-1, min(1, d.z))))
            if d.x < -0.2 or (abs(yaw) < 46 and lower(yaw) < pitch < upper(yaw)):
                cut.append(f)
        bmesh.ops.delete(m.bm, geom=cut, context="FACES")
        m.part([v for v in shell if v.is_valid], "head", "Skin")
        for edge, lift, rad in ((upper, 0.0011, 0.0011), (lower, 0.0008, 0.0009)):
            pts = []
            for k in range(9):
                yaw = -46 + 92 * k / 8
                p = math.radians(edge(yaw))
                d = Vector((math.cos(p) * math.cos(math.radians(yaw)), math.cos(p) * math.sin(math.radians(yaw)), math.sin(p)))
                pts.append(eye + d * (lr + lift))
            m.part(tube(m.bm, pts, [rad * (0.6 + 0.4 * math.sin(math.pi * k / 8)) for k in range(9)], sides=6, caps=False), "head", "Skin")
            if edge is upper:  # lashes
                m.part(tube(m.bm, [p + Vector((0.0008, 0, 0.0004)) for p in pts[1:-1]], [0.0005] * 7, sides=4), "head", "Hair")
        # Bushy, unkempt brows.
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.011, 1.097), (0.03, 1.104), (0.051, 1.099))]
        m.part(tube(m.bm, brow, [0.0024, 0.0034, 0.002], sides=8), "head", "Beard")
        rng = random.Random(10 + s)
        strands(m, [(brow[1].lerp(brow[k % 2 * 2], rng.random()), Vector((1, s * 0.6, 0.4))) for k in range(14)], "head", "Beard", rng, length=(0.006, 0.013), r0=0.0008, droop=0.3)
        # The ear's rim.
        c = Vector((-0.012, s * 0.083, 1.062))
        rim = [c + Vector((0.016 * math.cos(math.radians(a)), s * 0.003, 0.027 * math.sin(math.radians(a)))) for a in range(70, 251, 20)]
        m.part(tube(m.bm, rim, [0.0028] * len(rim), sides=6), "head", "Skin")
    lip = on_skin(0, 1.0, -0.002)
    m.part(uv_ellipsoid(m.bm, lip, (0.007, 0.015, 0.0045), segments=(14, 8)), "head", "Lip")


def ruddy_nose(m, head):
    """Reddens the skin of the bulbous drinker's nose."""
    spots = [(Vector((0.107, 0, 1.04)), 0.021)]
    for f in {f for v in head for f in v.link_faces}:
        c = f.calc_center_median()
        if any((c - p).length < r for p, r in spots) and c.x > 0.06:
            f.material_index = MAT["Ruddy"]


def beard_strands(m):
    """Stray hairs sticking out of the beard and hair, so its outline isn't smooth."""
    rng = random.Random(21)
    roots = []
    for _ in range(140):
        y, z = rng.uniform(-0.06, 0.06), rng.uniform(0.87, 1.02)
        loc, n = m.hit("beard", (0.4, y, z), (-1, 0, 0))
        if loc is not None:
            roots.append((loc - n * 0.002, n + Vector((0, 0, -0.8))))
    for i, root in enumerate(roots):
        strands(m, [root], "head", "Grey" if i % 3 == 0 else "Beard", rng, length=(0.012, 0.03), r0=0.0009, droop=0.5)
    roots = []
    for _ in range(26):  # lank locks hanging from under the beanie
        a = rng.uniform(math.radians(70), math.radians(290))
        d = Vector((math.cos(a), math.sin(a), 0))
        loc, n = m.hit("hair", Vector((-0.02, 0, 1.075)) + d * 0.3, -d)
        if loc is not None:
            roots.append((loc - n * 0.004, n * 0.25 + Vector((0, 0, -1))))
    for root in roots:
        strands(m, [root], "head", "Hair", rng, length=(0.035, 0.06), r0=0.0042, droop=0.4)


def beanie(m):
    """A slouchy knit beanie pulled low: a thick rolled, ribbed cuff and a ribbed crown,
    fitted over the head and hair by ray casts and sagging toward the back."""
    sides, rows, ribs = 120, 18, 30
    c0 = Vector((-0.016, 0, 1.098))

    def brim(a):  # the bottom edge, as an angle up from c0: low at the back, tilted
        return math.radians(12 * math.cos(a) - 6 + 4 * math.sin(a))

    def surface(d):
        hits = [m.hit(p, c0 + d * 0.4, -d)[0] for p in ("head", "hair")]
        return max([(h - c0).length for h in hits if h is not None] + [0.06])

    grid = []
    for i in range(rows + 1):
        t = i / rows
        ring = []
        for j in range(sides):
            a = 2 * math.pi * j / sides
            phi0 = brim(a)
            phi = phi0 + (math.radians(84) - phi0) * t
            d = Vector((math.cos(phi) * math.cos(a), math.cos(phi) * math.sin(a), math.sin(phi)))
            r = surface(d) + 0.004
            cuff = min(1.0, t / 0.3)
            r += 0.011 * math.sin(math.pi * cuff) ** 0.6 if t < 0.3 else 0.004 + 0.022 * ((t - 0.3) / 0.7) ** 2
            r += 0.0014 * math.cos(ribs * a) * (1 - t)  # ribbing
            p = c0 + d * r
            p.x -= 0.03 * t**3  # slouch
            p.z -= 0.012 * t**3
            ring.append(m.bm.verts.new(p))
        grid.append(ring)
    top = m.bm.verts.new(sum((v.co for v in grid[-1]), Vector()) / sides + Vector((0, 0, 0.004)))
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(sides):
            m.bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    for j in range(sides):
        m.bm.faces.new((grid[-1][j], grid[-1][(j + 1) % sides], top))
    # The cuff's fold: an inner lip tucking back to the head.
    lip = [m.bm.verts.new(c0 + (v.co - c0) * 0.93 + Vector((0, 0, 0.004))) for v in grid[0]]
    for j in range(sides):
        m.bm.faces.new((lip[j], lip[(j + 1) % sides], grid[0][(j + 1) % sides], grid[0][j]))
    m.part([v for r in grid for v in r] + lip + [top], "head", "Beanie")


def coat_skirt(m):
    """The coat below the waist: a heavy sheet hanging open at the front to the knees,
    split at the back, with a frayed, tattered hem, moth holes and a patched tear. The
    top follows the hips; lower down each side follows its thigh."""
    top, open_a = 0.6, math.radians(26)
    cols, rows = 84, 22
    rng = random.Random(5)
    hem = []
    for j in range(cols + 1):  # ragged hem: an uneven length, with torn tongues
        z = 0.31 + rng.uniform(-0.02, 0.012)
        if j % 7 == 3:
            z -= rng.uniform(0.02, 0.045)
        hem.append(z)
    holes = ((math.radians(-128), 0.43, 0.024), (math.radians(115), 0.37, 0.02), (math.radians(-35), 0.355, 0.015), (math.radians(175), 0.47, 0.018))
    reach = [0.0] * (cols + 1)
    grid = []
    for i in range(rows + 1):
        t = i / rows
        row = []
        for j in range(cols + 1):
            a = open_a + (2 * math.pi - 2 * open_a) * j / cols
            z = top + (hem[j] - top) * t
            o = Vector((0.0, 0, z))
            reach[j] = max(reach[j], m.fit(("coat", "leg.L", "leg.R", "sweater"), o, a))
            r = reach[j] + 0.006 + 0.03 * min(1, t * 2.5) + 0.009 * t * math.sin(7 * a + 1)
            gap = 0.008 * (1 - t) if abs(a - math.pi) < 0.06 else 0.0  # the back vent
            row.append(m.bm.verts.new(o + Vector((math.cos(a), math.sin(a), 0)) * r + Vector((0, 0, gap))))
        grid.append(row)

    def holed(a, z, rr):
        for ha, hz, hr in holes:
            da = (a - ha + math.pi) % (2 * math.pi) - math.pi
            if math.hypot(da * rr, z - hz) < hr * (0.8 + 0.4 * math.sin(5 * da / max(hr, 1e-3) + 9 * z)):
                return True
        return False

    faces = []
    vent = cols // 2
    for i in range(rows):
        for j in range(cols):
            if j == vent and i > rows * 0.55:
                continue  # the split at the back
            a = open_a + (2 * math.pi - 2 * open_a) * (j + 0.5) / cols
            z = top + ((hem[j] + hem[j + 1]) / 2 - top) * (i + 0.5) / rows
            if holed(a, z, reach[j] + 0.03):
                continue
            faces.append(m.bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1])))
    verts = [v for r in grid for v in r]
    solid = bmesh.ops.solidify(m.bm, geom=faces, thickness=0.006)
    verts += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
    verts = [v for v in verts if v.is_valid and v.link_faces]

    def weights(p):
        t = max(0.0, min(1.0, (top - 0.03 - p.z) / 0.16))
        left = max(0.0, min(1.0, 0.5 + p.y / 0.14))
        return {"hips": 1 - 0.8 * t, "thigh.L": 0.8 * t * left, "thigh.R": 0.8 * t * (1 - left)}

    m.weigh(verts, weights)
    m.paint(verts, "Coat")
    # Frayed threads off the hem.
    roots = []
    for j in range(0, cols + 1, 2):
        p = grid[rows][j].co
        roots.append((p.copy(), Vector((p.x, p.y, 0)).normalized() * 0.3 + Vector((0, 0, -1))))
    strands(m, roots, weights, "Coat", rng, length=(0.01, 0.025), r0=0.0014, droop=0.3)

    def at(a, z, lift):
        a = (a - open_a) % (2 * math.pi) + open_a
        j = (a - open_a) / (2 * math.pi - 2 * open_a) * cols
        jj = max(0, min(cols - 1, int(j)))
        i = (top - z) / (top - (hem[jj] + hem[jj + 1]) / 2) * rows
        ii = max(0, min(rows - 1, int(i)))
        fj, fi = j - jj, i - ii
        p = grid[ii][jj].co.lerp(grid[ii][jj + 1].co, fj).lerp(grid[ii + 1][jj].co.lerp(grid[ii + 1][jj + 1].co, fj), fi)
        return p + Vector((math.cos(a), math.sin(a), 0)) * lift

    # A plaid patch sewn over a tear on each side, and a pocket flap hanging torn.
    for ac, zc, w, h, tilt in ((math.radians(-62), 0.42, 0.075, 0.065, 0.2), (math.radians(70), 0.45, 0.065, 0.07, -0.15)):
        rr = reach[int(((ac - open_a) % (2 * math.pi)) / (2 * math.pi - 2 * open_a) * cols) % cols] + 0.03
        n_u, n_v = 6, 6
        pg = []
        for vi in range(n_v + 1):
            row = []
            for ui in range(n_u + 1):
                du, dv = (ui / n_u - 0.5) * w, (vi / n_v - 0.5) * h
                du, dv = du * math.cos(tilt) - dv * math.sin(tilt), du * math.sin(tilt) + dv * math.cos(tilt)
                row.append(m.bm.verts.new(at(ac + du / rr, zc + dv, 0.009)))
            pg.append(row)
        pf = [m.bm.faces.new((pg[vi][ui], pg[vi][ui + 1], pg[vi + 1][ui + 1], pg[vi + 1][ui])) for vi in range(n_v) for ui in range(n_u)]
        pv = [v for r in pg for v in r]
        solid = bmesh.ops.solidify(m.bm, geom=pf, thickness=0.003)
        pv += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
        m.weigh(pv, weights)
        m.paint(pv, "Patch")
        border = [pg[0][u].co for u in range(n_u)] + [pg[v][n_u].co for v in range(n_v)] + [pg[n_v][u].co for u in range(n_u, 0, -1)] + [pg[v][0].co for v in range(n_v, 0, -1)]
        dense = [p.lerp(border[(k + 1) % len(border)], f) for k, p in enumerate(border) for f in (0.0, 0.5)]
        stitches(m, [p + Vector((math.cos(ac), math.sin(ac), 0)) * 0.002 for p in dense], weights)
    # Mismatched buttons down the left front edge, one gone (just its thread left).
    a_edge = 2 * math.pi - open_a - 0.07
    for z, mat, gone in ((0.56, "Button", False), (0.48, "Brass", False), (0.4, "Button", True)):
        p = at(a_edge, z, 0.012)
        n = Vector((math.cos(a_edge), math.sin(a_edge), 0))
        if gone:
            strands(m, [(p - n * 0.004, n + Vector((0, 0, -1.5)))], weights, "Thread", rng, length=(0.02, 0.025), r0=0.0009, droop=0.6)
            continue
        verts = uv_ellipsoid(m.bm, p, (0.012, 0.012, 0.004), n.to_track_quat("Z", "Y"), segments=(14, 6))
        m.weigh(verts, weights)
        m.paint(verts, mat)


def coat_details(m, pieces):
    """The turned-up collar, rolled lapels, frayed cuffs with the sweater's peeking out,
    patched elbows and moth holes."""
    on_coat = m.weights_near(pieces["coat"])
    bm = m.bm
    # Collar: turned up round the back of the neck, open at the front.
    cols, rows, span = 40, 5, math.radians(62)
    grid = []
    for i in range(rows + 1):
        t = i / rows
        row = []
        for j in range(cols + 1):
            a = span + (2 * math.pi - 2 * span) * j / cols
            back = 0.5 - 0.5 * math.cos(a)  # 1 at the back
            z = 0.86 + (0.055 + 0.035 * back) * t
            r = 0.078 + 0.028 * t + 0.01 * (1 - back)
            row.append(bm.verts.new(Vector((-0.012, 0, z)) + Vector((math.cos(a), math.sin(a), 0)) * r))
        grid.append(row)
    faces = [bm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j])) for i in range(rows) for j in range(cols)]
    verts = [v for r in grid for v in r]
    solid = bmesh.ops.solidify(bm, geom=faces, thickness=0.006)
    verts += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
    m.part(verts, "spine", "Coat")
    # Lapels: the coat's front edges rolled back over the sweater.
    for s in (1, -1):
        edge = []
        for k in range(12):
            t = k / 11
            y, z = s * (0.07 - 0.018 * t), 0.86 - 0.3 * t
            loc, n = m.hit("coat", (0.5, y, z), (-1, 0, 0))
            if loc is not None:
                edge.append(loc + n * 0.003)
        verts = tube(bm, edge, [0.013 - 0.008 * k / max(1, len(edge) - 1) for k in range(len(edge))], sides=8)
        for v in verts:  # flatten against the chest
            v.co.x -= 0.004
        m.weigh(verts, on_coat)
        m.paint(verts, "Coat")
    rng = random.Random(9)
    for side, s in (("L", 1), ("R", -1)):
        y = s * SHOULDER[0]
        sleeve = f"sleeve.{side}"
        on_sleeve = m.weights_near(pieces[sleeve])
        # A frayed, flared cuff past the end of the sleeve.
        center = lambda z: Vector((-0.002, y, z))  # noqa: E731
        reach = [m.fit((sleeve,), center(WRIST[1] + 0.1), 2 * math.pi * j / 36) for j in range(36)]
        jag = [rng.uniform(0.0, 0.014) for _ in range(36)]

        def cuff_r(a, z, reach=reach):
            j = round(a / (2 * math.pi) * 36) % 36
            return reach[j] + 0.002 + 0.06 * (WRIST[1] + 0.1 - z) ** 1

        band = ring_band(bm, center, cuff_r, WRIST[1] + 0.04, WRIST[1] + 0.105, rows=4, sides=36)
        for v in band[:36]:  # tatter the bottom row
            a = math.atan2(v.co.y - y, v.co.x)
            v.co.z -= jag[round(a / (2 * math.pi) * 36) % 36]
        solid = bmesh.ops.solidify(bm, geom=list({f for v in band for f in v.link_faces}), thickness=0.004)
        band += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
        m.part(band, f"forearm.{side}", "Coat")
        strands(m, [(band[j].co.copy(), Vector((0, 0, -1)) + (band[j].co - center(band[j].co.z)).normalized() * 0.3) for j in range(0, 36, 3)],
                f"forearm.{side}", "Coat", rng, length=(0.008, 0.018), r0=0.0012, droop=0.2)
        # The sweater's ribbed cuff, peeking out.
        rib = ring_band(bm, center, lambda a, z: 0.03 + 0.0012 * math.cos(16 * a), WRIST[1] + 0.008, WRIST[1] + 0.06, rows=3, sides=48)
        m.part(rib, f"forearm.{side}", "Body")
        # A plaid elbow patch, stitched on.
        loc, n = m.hit(sleeve, (-0.4, y, ELBOW[1] - 0.01), (1, 0, 0))
        rim = decal(m, sleeve, loc, n, lambda a: 0.032 + 0.006 * math.cos(2 * a), "Patch", 0.0025, on_sleeve, thickness=0.002)
        stitches(m, rim, on_sleeve)
    # Moth holes, frayed round the edges: on the chest, the back and the near sleeve.
    for piece, origin, direction, size in (("coat", (0.5, 0.1, 0.66), (-1, 0, 0), 0.016), ("coat", (-0.5, -0.06, 0.74), (1, 0, 0), 0.022),
                                           ("sleeve.R", (0.0, -0.5, 0.74), (0, 1, 0), 0.012), ("sleeve.L", (0.0, 0.5, 0.58), (0, -1, 0), 0.012)):
        loc, n = m.hit(piece, origin, direction)
        if loc is None:
            continue
        on = m.weights_near(pieces[piece])
        k = rng.uniform(0, 6)
        rim = decal(m, piece, loc, n, lambda a, k=k, size=size: size * (0.75 + 0.25 * math.sin(3 * a + k) + 0.12 * math.sin(7 * a)), "Lining", 0.0015, on, rows=3)
        strands(m, [(p, n * 0.6 + (p - loc).normalized()) for p in rim[::2]], on, "Coat", rng, length=(0.004, 0.009), r0=0.001, droop=0.2)


def rope_belt(m):
    """A length of rope for a belt, knotted at the front, showing under the open coat."""
    z = 0.575
    fit = [m.fit(("sweater", "leg.L", "leg.R"), Vector((0, 0, z)), 2 * math.pi * j / 48) + 0.007 for j in range(48)]
    for phase in (0.0, math.pi):  # two twisted strands
        pts = []
        for k in range(97):
            a = 2 * math.pi * k / 96
            r = fit[round(a / (2 * math.pi) * 48) % 48]
            twist = 0.003 * math.cos(30 * a + phase)
            pts.append(Vector((math.cos(a) * (r + twist), math.sin(a) * (r + twist), z + 0.003 * math.sin(30 * a + phase))))
        m.part(tube(m.bm, pts, [0.0034] * len(pts), sides=6), "hips", "Rope")
    knot = Vector((fit[0] + 0.004, -0.02, z))
    m.part(uv_ellipsoid(m.bm, knot, (0.01, 0.013, 0.011)), "hips", "Rope")
    for dy, length in ((0.01, 0.07), (-0.012, 0.055)):
        end = [knot + Vector((0.004, dy * 0.5, -0.008)), knot + Vector((0.008, dy, -length * 0.5)), knot + Vector((0.006, dy * 1.4, -length))]
        m.part(tube(m.bm, end, [0.0045, 0.0042, 0.004], sides=6), "hips", "Rope")


def knees(m, pieces):
    """A plaid patch on the near knee; the far knee torn open on the skin."""
    loc, n = m.hit("leg.R", (0.5, -HIP[0], KNEE[1] - 0.01), (-1, 0, 0))
    on = m.weights_near(pieces["leg.R"])
    rim = decal(m, "leg.R", loc, n, lambda a: 0.032 + 0.004 * math.cos(4 * a), "Patch", 0.002, on, thickness=0.002)
    stitches(m, rim, on)
    knee = Vector((0.045, HIP[0] + 0.006, KNEE[1] - 0.01))
    on = by_dist("thigh.L", "shin.L", sharpness=8)
    verts = uv_ellipsoid(m.bm, knee, (0.02, 0.04, 0.03), segments=(14, 10))
    m.weigh(verts, on)
    m.paint(verts, "Skin")
    rng = random.Random(12)
    roots = []
    for k in range(10):
        a = 2 * math.pi * k / 10
        p = knee + Vector((0.026, 0.034 * math.cos(a), 0.024 * math.sin(a)))
        loc, n = m.hit("leg.L", p + Vector((0.1, 0, 0)), (-1, 0, 0))
        if loc is not None:
            roots.append((loc, n + (loc - knee).normalized() * -0.5))
    strands(m, roots, on, "Pants", rng, length=(0.006, 0.014), r0=0.0014, droop=0.1)


def shoe_details(m, s, side, frayed):
    """The worn sole with its welt, criss-cross laces (one trailing, untied), and on
    one shoe a sock-covered toe through the hole."""
    y0 = s * HIP[0]
    bm = m.bm
    outline = []
    for k in range(32):
        a = 2 * math.pi * k / 32
        x = 0.05 + 0.123 * math.cos(a)
        w = 0.05 if math.cos(a) > -0.2 else 0.043
        outline.append((x, y0 + w * math.sin(a)))
    rings = [[bm.verts.new((x, y, z)) for x, y in outline] for z in (0.0, 0.006, 0.024)]
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(32):
            bm.faces.new((r0[j], r0[(j + 1) % 32], r1[(j + 1) % 32], r1[j]))
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        c = bm.verts.new(sum((v.co for v in ring), Vector()) / 32)
        for j in range(32):
            a, b = ring[j], ring[(j + 1) % 32]
            bm.faces.new((b, a, c) if flip else (a, b, c))
        ring.append(c)
    for v in rings[1][:32]:  # the welt, a lip round the sole
        v.co = Vector((0.05, y0, v.co.z)) + (v.co - Vector((0.05, y0, v.co.z))) * 1.03
    verts = [v for r in rings for v in r]
    m.part(verts, f"foot.{side}", "Sole", smooth=False)
    # Laces over the instep.
    eyelets = []
    for x in (0.02, 0.045, 0.07):
        pair = []
        for dy in (0.02, -0.02):
            loc, n = m.hit(f"boot.{side}", (x, y0 + dy, 0.3), (0, 0, -1))
            pair.append(loc + n * 0.002)
        eyelets.append(pair)
    for (a0, b0), (a1, b1) in zip(eyelets, eyelets[1:]):
        for p, q in ((a0, b1), (b0, a1)):
            m.part(tube(bm, [p, (p + q) / 2 + Vector((0, 0, 0.003)), q], [0.0017] * 3, sides=5), f"foot.{side}", "Lace")
    for p, q in eyelets[:1]:
        m.part(tube(bm, [p, q], [0.0017] * 2, sides=5), f"foot.{side}", "Lace")
    top = eyelets[-1]
    if frayed:
        knot = (top[0] + top[1]) / 2 + Vector((0, 0, 0.004))
        for dy, length in ((0.012, 0.06), (-0.01, 0.075)):  # untied, trailing on the ground
            end = [knot, knot + Vector((0.012, dy, -0.02)), knot + Vector((0.03, dy * 1.5, -0.05)), Vector((knot.x + 0.04 + length * 0.4, knot.y + dy * 2, 0.003))]
            m.part(tube(bm, end, [0.0017] * 4, sides=5), f"foot.{side}", "Lace")
        toe = Vector((0.158, y0 - s * 0.012, 0.04))
        m.part(uv_ellipsoid(bm, toe, (0.016, 0.018, 0.014), segments=(14, 8)), f"foot.{side}", "Sock")


def bottle(m):
    """A multi-part bottle along +X from the grip: glass body, paper label, red cap."""
    bm = m.bm

    def at(x):
        return GRIP + Vector((x, 0, 0))

    def rod(x0, x1, r0, r1, mat, sides=16):
        m.part(tube(bm, [at(x0), at(x1)], [r0, r1], sides=sides), "bottle", mat)

    rod(0.004, 0.02, 0.016, 0.016, "Cap")  # the cap
    rod(0.02, 0.05, 0.012, 0.013, "Bottle")  # the neck
    rod(0.05, 0.09, 0.013, 0.026, "Bottle")  # the shoulder
    rod(0.09, 0.16, 0.026, 0.026, "Bottle")  # the body
    m.part(tube(bm, [at(0.097), at(0.153)], [0.0268, 0.0268], sides=20, caps=False), "bottle", "Label")  # the paper label
    base = bmesh.ops.create_circle(bm, cap_ends=True, segments=16, radius=0.026, matrix=Matrix.Translation(at(0.16)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))["verts"]
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

    ring((0.0, 0.0), 0.22, 0.30, "Cart")
    ring((0.0, 0.0), 0.17, 0.10, "Cart")
    for i in range(8):
        a = 2 * math.pi * i / 8
        bar((0.17 * math.cos(a), 0.17 * math.sin(a), 0.10), (0.22 * math.cos(a), 0.22 * math.sin(a), 0.30), 0.004, "Cart")
        bar((0.0, 0.0, 0.30), (0.22 * math.cos(a), 0.22 * math.sin(a), 0.30), 0.004, "Cart")
    for side in (-1, 1):
        bar((side * 0.22, 0.0, 0.30), (side * 0.20, 0.0, 0.06), 0.006, "Cart")
    bar((-0.2, 0.0, 0.06), (0.2, 0.0, 0.06), 0.008, "CartTrim")
    for x in (-0.2, 0.2):
        for y in (-0.16, 0.16):
            bar((x, y, 0.06), (x, y, -0.04), 0.007, "Cart")
            wheel = bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.035, radius2=0.035, depth=0.012,
                                          matrix=Matrix.Translation(at(x, y, -0.05)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))["verts"]
            m.weigh(wheel, "cart")
            m.paint(wheel, "CartWheel", smooth=False)
    bar((-0.16, -0.12, 0.02), (0.16, -0.12, 0.02), 0.004, "Cart")
    bar((-0.16, 0.12, 0.02), (0.16, 0.12, 0.02), 0.004, "Cart")


def hobo_mesh():
    m = Model()
    pieces = {}
    head = m.blob("head", head_blob(), 0.4, "Skin", by_dist("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    m.blob("beard", beard_blob(), 0.25, "Beard", "head")
    pieces["sweater"] = m.blob("sweater", sweater_blob(), 0.25, "Body", by_dist("hips", "spine"))
    pieces["coat"] = m.blob("coat", coat_blob(), 0.2, "Coat", by_dist("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        pieces[f"sleeve.{side}"] = m.blob(f"sleeve.{side}", sleeve_blob(s), 0.22, "Coat", by_dist("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", hand_blob(s), 0.25, "Skin", f"forearm.{side}")
        m.blob(f"glove.{side}", glove_blob(s), 0.22, "Glove", f"forearm.{side}")
        pieces[f"leg.{side}"] = m.blob(f"leg.{side}", pants_blob(s, tear=side == "L"), 0.2, "Pants", by_dist("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"boot.{side}", shoe_blob(s, toe_hole=side == "R"), 0.3, "Shoe", f"foot.{side}")
    ruddy_nose(m, head)
    face(m)
    beard_strands(m)
    beanie(m)
    coat_skirt(m)
    coat_details(m, pieces)
    rope_belt(m)
    knees(m, pieces)
    for side, s in (("L", 1), ("R", -1)):
        shoe_details(m, s, side, frayed=side == "R")
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
        tree = mat.node_tree
        bsdf = tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        maps = TEXTURES.get(name)
        if maps:
            # One Mapping node tiles every map (exported as KHR_texture_transform,
            # which Godot applies to the material's UV1).
            coords = tree.nodes.new("ShaderNodeTexCoord")
            mapping = tree.nodes.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = (maps["tile"], maps["tile"], 1)
            tree.links.new(coords.outputs["UV"], mapping.inputs["Vector"])

            def image(file, colorspace):
                tex = tree.nodes.new("ShaderNodeTexImage")
                tex.image = bpy.data.images.get(file) or bpy.data.images.load(os.path.join(HERE, file))
                tex.image.colorspace_settings.name = colorspace
                tree.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
                return tex

            tree.links.new(image(maps["albedo"], "sRGB").outputs["Color"], bsdf.inputs["Base Color"])
            if "rough" in maps:
                tree.links.new(image(maps["rough"], "Non-Color").outputs["Color"], bsdf.inputs["Roughness"])
            file, strength = maps["normal"]
            normal = tree.nodes.new("ShaderNodeNormalMap")
            normal.inputs["Strength"].default_value = strength
            tree.links.new(image(file, "Non-Color").outputs["Color"], normal.inputs["Color"])
            tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
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

    # UVs for the tiled textures: islands at an even texel density.
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.002)
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


# --- Ledge actions ------------------------------------------------------------
# Timed and placed against the sim (`try_grab_ledge`, `ledge_getup_pos`, the LEDGE_*
# constants in sim/src/fighter.rs and LEDGE_ATTACK_HITBOX in sim/src/world.rs). While
# hanging, the model's origin is 0.1 m outside the edge and H below the stage's top, so
# the ledge's corner is at model (0.1, H). A getup of N frames slides the origin
# linearly to `inward` m onto the stage: on frame f it has moved (inward + 0.1, H) * f/N.
# The keys below are written in that "hang frame" (model space while hanging, so the
# corner stays put) and converted to model space frame by frame; arms and legs are
# solved onto their targets with IK, so hands stay planted on the corner while the body
# is moved under them.

UPPER_ARM = SHOULDER[1] - ELBOW[1]
FOREARM = ELBOW[1] - WRIST[1] + FIST  # elbow to the grip
CORNER = (0.1, H)
GRIP_AT = (0.105, H + 0.012)  # the fist on the corner, fingers over the top
GETUPS = {"ledge_climb": (20, 0.8), "ledge_roll": (25, 1.5), "ledge_attack": (30, 1.0)}  # frames, inward (sim LEDGE_*_FRAMES / _IN)


def _p(v):
    return v[0] if isinstance(v, tuple) else v


def _rot(v, deg):
    a = math.radians(deg)
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _limb(pitch, length):
    a = math.radians(pitch)
    return (length * math.sin(a), -length * math.cos(a))


def fk(pose):
    """The joints of `pose` in model space, side view: {name: (x, z)}."""
    fwd, up = pose.get("hips_loc", (0, 0))
    hp = _p(pose.get("hips", 0))
    hips = (fwd, 0.55 + up)
    spine = _add(hips, _rot((0, 0.13), hp))
    sp = hp + _p(pose.get("spine", 0))
    neck = _add(spine, _rot((0, 0.22), sp))
    out = {"hips": hips, "shoulder": _add(spine, _rot((0, 0.17), sp)), "head": _add(neck, _rot((0.02, 0.15), sp + _p(pose.get("head", 0))))}
    for side in "RL":
        ua = sp + _p(pose.get(f"upper_arm.{side}", 0))
        out[f"elbow.{side}"] = _add(out["shoulder"], _limb(ua, UPPER_ARM))
        out[f"grip.{side}"] = _add(out[f"elbow.{side}"], _limb(ua + _p(pose.get(f"forearm.{side}", 0)), FOREARM))
        th = hp + _p(pose.get(f"thigh.{side}", 0))
        out[f"knee.{side}"] = _add(_add(hips, _rot((0, -0.02), hp)), _limb(th, chef.THIGH_LEN))
        sh = th + _p(pose.get(f"shin.{side}", 0))
        out[f"ankle.{side}"] = _add(out[f"knee.{side}"], _limb(sh, chef.SHIN_LEN))
        ft = sh + _p(pose.get(f"foot.{side}", 0))
        out[f"toe.{side}"] = _add(out[f"ankle.{side}"], _rot((0.15, -0.055), ft))
        out[f"heel.{side}"] = _add(out[f"ankle.{side}"], _rot((-0.06, -0.06), ft))
    return out


def arm_ik(pose, side, target):
    """Puts the grip of the `side` arm on `target` (model space), elbow bending down."""
    sh = fk(pose)["shoulder"]
    dx, dz = target[0] - sh[0], target[1] - sh[1]
    dist = max(abs(UPPER_ARM - FOREARM) + 1e-3, min(math.hypot(dx, dz), UPPER_ARM + FOREARM - 1e-3))
    aim = math.degrees(math.atan2(dx, -dz))
    alpha = math.degrees(math.acos((UPPER_ARM**2 + dist**2 - FOREARM**2) / (2 * UPPER_ARM * dist)))
    beta = math.degrees(math.acos((FOREARM**2 + dist**2 - UPPER_ARM**2) / (2 * FOREARM * dist)))
    chain = _p(pose.get("hips", 0)) + _p(pose.get("spine", 0))
    pose[f"upper_arm.{side}"] = (aim - alpha - chain + 90) % 360 - 90
    pose[f"forearm.{side}"] = alpha + beta
    return pose


def _turn(a, b, t):
    """Lerps between two joint angles the short way round."""
    return a + ((b - a + 180) % 360 - 180) * t


def _lerp(a, b, t):
    if isinstance(a, tuple) or isinstance(b, tuple):
        a = a if isinstance(a, tuple) else (a, 0, 0)
        b = b if isinstance(b, tuple) else (b, 0, 0)
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def _spline(keys, field, f, default=0):
    """Catmull-Rom through the keys' `field` (numbers or tuples) at frame f."""
    i = max(k for k in range(len(keys)) if keys[k]["f"] <= f)
    i = min(i, len(keys) - 2)
    p = [keys[max(0, min(len(keys) - 1, i + d))].get(field, default) for d in (-1, 0, 1, 2)]
    tup = any(isinstance(v, tuple) for v in p)
    p = [(v if isinstance(v, tuple) else (v, 0, 0)) if tup else v for v in p]
    t = (f - keys[i]["f"]) / (keys[i + 1]["f"] - keys[i]["f"])
    w = (-0.5 * t**3 + t**2 - 0.5 * t, 1.5 * t**3 - 2.5 * t**2 + 1, -1.5 * t**3 + 2 * t**2 + 0.5 * t, 0.5 * t**3 - 0.5 * t**2)
    if tup:
        return tuple(sum(w[k] * p[k][c] for k in range(4)) for c in range(len(p[0])))
    return sum(w[k] * p[k] for k in range(4))


def _limb_angles(pose, key, limb, root):
    """The angles one key gives an arm or leg, on the body of `pose`: solved onto the
    key's target ("ik", hang-frame point) or given directly ("ang", angles)."""
    mode, value = key[limb]
    side = limb[-1]
    if limb.startswith("arm"):
        bones = (f"upper_arm.{side}", f"forearm.{side}")
        if mode == "ik":
            p = arm_ik(dict(pose), side, (value[0] - root[0], value[1] - root[1]))
            return {b: p[b] for b in bones}
    else:
        bones = (f"thigh.{side}", f"shin.{side}", f"foot.{side}")
        if mode == "ik":
            p = leg_ik(dict(pose), side, value[0] - root[0], value[1] - root[1] - ANKLE[1])
            return {b: p[b] for b in bones}
    return dict(zip(bones, value))


# Points that mustn't sink into the stage while rolling, with their padding (m).
SOLID = {"head": 0.12, "hips": 0.11, "shoulder": 0.1, "knee.R": 0.06, "knee.L": 0.06, "ankle.R": 0.06, "ankle.L": 0.06,
         "toe.R": 0.02, "toe.L": 0.02, "heel.R": 0.02, "heel.L": 0.02, "elbow.R": 0.06, "elbow.L": 0.06, "grip.R": 0.04, "grip.L": 0.04}


def getup(keys, root_at, frames):
    """A key per frame from sparse hang-frame control keys. Each key has "f", "P" (the
    hips' pivot), optional "hips"/"spine"/"head" angles, an "arm.R"/"arm.L"/"leg.R"/
    "leg.L" mode each, and optionally "bottle" (its facing, see `bottle_in`),
    "bottle_scale" and "ground" (keep the body above the stage)."""
    out = []
    for f in frames:
        i = min(max(k for k in range(len(keys)) if keys[k]["f"] <= f), len(keys) - 2)
        a, b = keys[i], keys[i + 1]
        t = (f - a["f"]) / (b["f"] - a["f"])
        t = t * t * (3 - 2 * t)
        root = root_at(f)
        lift = 0.0
        for _ in range(4):
            P = _spline(keys, "P", f)
            pose = {"hips_loc": (P[0] - root[0], P[1] + lift - root[1] - 0.55)}
            for bone in ("hips", "spine", "head"):
                pose[bone] = _spline(keys, bone, f)
            for limb in ("arm.R", "arm.L", "leg.R", "leg.L"):
                va, vb = _limb_angles(pose, a, limb, root), _limb_angles(pose, b, limb, root)
                for bone in va:
                    pose[bone] = _turn(va[bone], vb[bone], t)
            if not (a.get("ground") and b.get("ground")):
                break
            # Rolling: the lowest point of the tucked body rests on the stage.
            joints = fk(pose)
            sink = max(H + pad - (joints[j][1] + root[1]) for j, pad in SOLID.items() if joints[j][0] + root[0] > CORNER[0] - 0.05)
            if abs(sink) < 1e-4:
                break
            lift += sink
        pose["bottle_scale"] = _lerp(a.get("bottle_scale", 0), b.get("bottle_scale", 0), t)
        if pose["bottle_scale"] > 0:
            facing = _lerp(a.get("bottle", 0), b.get("bottle", 0), t)
            pose["bottle"] = facing - sum(_p(pose.get(k, 0)) for k in ("hips", "spine", "upper_arm.R", "forearm.R"))
        out.append((f, pose))
    return out


def from_pose(f, pose, root, **extra):
    """A control key holding `pose` exactly, with the origin at `root` (hang frame)."""
    fwd, up = pose.get("hips_loc", (0, 0))
    key = {"f": f, "P": (fwd + root[0], 0.55 + up + root[1])}
    key.update({b: pose.get(b, 0) for b in ("hips", "spine", "head")})
    for side in "RL":
        key[f"arm.{side}"] = ("ang", (pose[f"upper_arm.{side}"], pose[f"forearm.{side}"]))
        key[f"leg.{side}"] = ("ang", (pose[f"thigh.{side}"], pose[f"shin.{side}"], pose[f"foot.{side}"]))
    key.update(extra)
    return key


def _root(name):
    total, inward = GETUPS[name]
    return lambda f: ((CORNER[0] + inward) * f / total, H * f / total)


def _ang(*v):
    return ("ang", v)


def _ik(x, z):
    return ("ik", (x, z))


def _foot(x, lift=0.0):
    """An ankle target on the stage (hang frame)."""
    return _ik(x, H + ANKLE[1] + lift)


# Hanging: a dead hang with straight arms, hands over the corner, legs dangling.
HANG = {"f": 0, "P": (-0.03, 0.49), "spine": -4, "head": (14, 0, 0), "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT),
        "leg.R": _ang(18, -35, -25), "leg.L": _ang(-4, -12, -30)}


def ledge_hang():
    """A drunk's hang, looping over 72 frames: the body sways from the hands like a
    pendulum, the legs kick lazily and the head lolls."""
    keys = []
    for f in range(1, 74, 4):
        w = 2 * math.pi * (f - 1) / 72
        sway = 3.5 * math.sin(w)
        P = _add(GRIP_AT, _rot((HANG["P"][0] - GRIP_AT[0], HANG["P"][1] - GRIP_AT[1]), sway))
        key = dict(HANG, f=f, P=P, hips=sway, spine=-4 + 1.5 * math.sin(2 * w), head=(14 + 4 * math.sin(w + 1), 8 * math.sin(w), 6 * math.cos(w)))
        key["leg.R"] = _ang(18 + 10 * math.sin(w + 0.5), -35 - 14 * math.sin(w + 0.5), -25)
        key["leg.L"] = _ang(-4 + 8 * math.sin(w + 2.5), -12 - 10 * math.sin(w + 2.5), -30)
        keys.append(key)
    out = getup(keys + [dict(keys[0], f=keys[-1]["f"] + 4)], lambda f: (0.0, 0.0), range(1, 74, 4))
    out[-1] = (73, out[0][1])  # loops exactly
    return out


def ledge_climb():
    """20 frames: hauls himself up with his feet scrabbling at the wall, gets a foot onto
    the stage, shoves himself up and lurches two steps in before he catches his balance."""
    root = _root("ledge_climb")
    keys = [
        HANG,
        {"f": 4, "P": (-0.06, 0.78), "spine": -12, "head": 20, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(20, -50, -20), "leg.L": _ang(5, -35, -20)},
        {"f": 6, "P": (-0.08, 1.06), "spine": -36, "head": 30, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(10, -60, -10), "leg.L": _ang(0, -40, -10)},
        {"f": 8, "P": (0.0, 1.3), "spine": -45, "head": 30, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(0, -40, 0), "leg.L": _ang(-10, -30, -10)},
        {"f": 9, "P": (0.04, 1.37), "spine": -45, "head": 30, "arm.R": _ik(0.12, H + 0.012), "arm.L": _ik(0.13, H + 0.012), "leg.R": _ik(0.14, H + 0.16), "leg.L": _ang(-10, -50, -10)},
        {"f": 10, "P": (0.08, 1.4), "spine": -42, "head": 30, "arm.R": _ik(0.13, H + 0.012), "arm.L": _ik(0.14, H + 0.012), "leg.R": _foot(0.28), "leg.L": _ang(-10, -70, -10)},
        {"f": 11, "P": (0.15, 1.45), "spine": -38, "head": 28, "arm.R": _ik(0.17, H + 0.012), "arm.L": _ik(0.18, H + 0.012), "leg.R": _foot(0.3), "leg.L": _ik(0.12, H + 0.16)},
        {"f": 12, "P": (0.25, 1.5), "spine": -35, "head": 26, "arm.R": _ik(0.2, H + 0.012), "arm.L": _ik(0.21, H + 0.012), "leg.R": _foot(0.3), "leg.L": _foot(0.32, 0.12)},
        {"f": 13, "P": (0.42, 1.6), "spine": (-25, 0, 6), "head": (22, 0, -8), "arm.R": _ang(70, 40), "arm.L": _ang(-25, 50), "leg.R": _foot(0.32), "leg.L": _foot(0.5, 0.12)},
        {"f": 16, "P": (0.72, 1.65), "spine": (-18, 0, -5), "head": (18, 0, 8), "arm.R": _ang(85, 30), "arm.L": _ang(-40, 60), "leg.R": _foot(0.65, 0.1), "leg.L": _foot(0.8)},
        {"f": 18, "P": (0.9, 1.67), "spine": -10, "head": 12, "arm.R": _ang(50, 80), "arm.L": _ang(10, 100), "leg.R": _foot(1.01), "leg.L": _foot(0.79)},
        from_pose(20, S, root(20)),
    ]
    return getup(keys, root, range(1, 21))


def ledge_roll():
    """25 frames: a quick hoist, then a sloppy, wobbling forward roll across the stage
    (a full turn round the hips, tucked), popping up in a stagger."""
    root = _root("ledge_roll")
    tuck = {"leg.R": _ang(120, -140, 0), "leg.L": _ang(115, -140, 0), "arm.R": _ang(60, 120), "arm.L": _ang(55, 125), "head": 45, "ground": True}
    keys = [
        HANG,
        {"f": 3, "P": (-0.06, 0.8), "spine": -14, "head": 22, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(30, -70, -10), "leg.L": _ang(20, -60, -10)},
        {"f": 6, "P": (-0.06, 1.12), "spine": -40, "head": 35, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(40, -100, 0), "leg.L": _ang(30, -95, 0)},
        dict(tuck, f=8, P=(0.2, 1.42), hips=-50, spine=(-45, 0, 0), **{"arm.R": _ik(0.22, H + 0.03), "arm.L": _ik(0.24, H + 0.03)}),
        dict(tuck, f=11, P=(0.52, H + 0.24), hips=-140, spine=(-45, 0, 12)),
        dict(tuck, f=14, P=(0.84, H + 0.24), hips=-230, spine=(-45, 0, -6)),
        dict(tuck, f=17, P=(1.14, H + 0.26), hips=-315, spine=(-40, 0, -12)),
        {"f": 20, "P": (1.45, H + 0.38), "hips": -360, "spine": (-30, 0, 6), "head": 25, "arm.R": _ang(40, 90), "arm.L": _ang(30, 90),
         "leg.R": _foot(1.71), "leg.L": _foot(1.49), "ground": True},
        {"f": 22, "P": (1.58, H + 0.47), "hips": -360, "spine": (-22, 0, -8), "head": (18, 0, 10), "arm.R": _ang(110, 20), "arm.L": _ang(-50, 40),
         "leg.R": _foot(1.71), "leg.L": _foot(1.49)},
        from_pose(25, S, root(25), hips=-360),
    ]
    return getup(keys, root, range(1, 26))


def ledge_attack():
    """30 frames: hauls himself up, pulls out the bottle and brings it down in a wild
    overhand smash across the stage in front of him (the sim's hitbox, frames 15-18, is
    0.6 m ahead and up from the origin, 0.6 m across), then staggers into his stance."""
    root = _root("ledge_attack")
    keys = [
        HANG,
        {"f": 4, "P": (-0.05, 0.72), "spine": -10, "head": 18, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(20, -50, -20), "leg.L": _ang(5, -35, -20)},
        {"f": 7, "P": (-0.08, 1.06), "spine": -36, "head": 30, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(10, -60, -10), "leg.L": _ang(0, -40, -10)},
        {"f": 9, "P": (0.0, 1.3), "spine": -45, "head": 30, "arm.R": _ik(*GRIP_AT), "arm.L": _ik(*GRIP_AT), "leg.R": _ang(0, -40, 0), "leg.L": _ang(-10, -30, -10)},
        {"f": 10, "P": (0.04, 1.37), "spine": -45, "head": 30, "arm.R": _ik(0.12, H + 0.012), "arm.L": _ik(0.13, H + 0.012), "leg.R": _ik(0.14, H + 0.16), "leg.L": _ang(-10, -50, -10)},
        {"f": 11, "P": (0.1, 1.42), "spine": -40, "head": 28, "arm.R": _ik(0.14, H + 0.03), "arm.L": _ik(0.13, H + 0.012), "leg.R": _foot(0.3), "leg.L": _ang(-10, -70, -10),
         "bottle": 60},
        {"f": 12, "P": (0.22, 1.5), "spine": -32, "head": 20, "arm.R": _ang(120, 60), "arm.L": _ik(0.18, H + 0.012), "leg.R": _foot(0.3), "leg.L": _ik(0.14, H + 0.16),
         "bottle": 90, "bottle_scale": 0.6},
        {"f": 13, "P": (0.38, 1.6), "spine": (-5, 35, 0), "head": 10, "arm.R": _ang(200, 50), "arm.L": _ang(70, 20), "leg.R": _foot(0.32), "leg.L": _foot(0.55, 0.15),
         "bottle": 160, "bottle_scale": 1},
        {"f": 14, "P": (0.5, 1.6), "spine": (-15, 25, 0), "head": 14, "arm.R": _ang(215, 10), "arm.L": _ang(40, 30), "leg.R": _foot(0.34), "leg.L": _foot(0.75),
         "bottle": 120, "bottle_scale": 1},
        {"f": 15, "P": (0.62, 1.54), "spine": (-38, -15, 0), "head": 25, "arm.R": _ang(102, 0), "arm.L": _ang(-40, 30), "leg.R": _foot(0.4), "leg.L": _foot(0.78),
         "bottle": -30, "bottle_scale": 1},
        {"f": 18, "P": (0.66, 1.48), "spine": (-55, -30, 0), "head": 35, "arm.R": _ang(70, 0), "arm.L": _ang(-70, 40), "leg.R": _foot(0.4), "leg.L": _foot(0.78),
         "bottle": -80, "bottle_scale": 1},
        {"f": 21, "P": (0.75, 1.55), "spine": (-40, -20, 8), "head": 25, "arm.R": _ang(40, 30), "arm.L": _ang(-30, 60), "leg.R": _foot(0.8, 0.12), "leg.L": _foot(0.78),
         "bottle": -60, "bottle_scale": 1},
        {"f": 24, "P": (0.95, 1.62), "spine": (-20, 0, -6), "head": (14, 0, 8), "arm.R": _ang(60, 60), "arm.L": _ang(10, 80), "leg.R": _foot(1.21), "leg.L": _foot(0.82),
         "bottle": 0, "bottle_scale": 1},
        {"f": 26, "P": (1.03, 1.66), "spine": -12, "head": 12, "arm.R": _ang(50, 80), "arm.L": _ang(16, 95), "leg.R": _foot(1.21), "leg.L": _foot(0.92, 0.04)},
        from_pose(30, S, root(30)),
    ]
    return getup(keys, root, range(1, 31))


ANIMATIONS.update({"ledge_hang": ledge_hang(), "ledge_climb": ledge_climb(), "ledge_roll": ledge_roll(), "ledge_attack": ledge_attack()})


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
