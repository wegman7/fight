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
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

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
    root = Vector((0.37, s * 0.128, 0.785))
    tip = Vector((0.445, s * 0.162, 0.7))
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
    # A black pug's short coat: near-black with a warm undertone and a soft sheen.
    "Fur": ((0.022, 0.019, 0.018, 1), 0.7, 0.0),
    "Body": ((0.8, 0.15, 0.15, 1), 0.45, 0.0),
    "Accent": ((1.0, 0.72, 0.28, 1), 0.25, 1.0),
    "Nose": ((0.01, 0.008, 0.008, 1), 0.5, 0.0),  # moist nose leather
    "Skin": ((0.016, 0.013, 0.013, 1), 0.3, 0.0),  # eyelid rims, wet
    "Nail": ((0.035, 0.03, 0.028, 1), 0.3, 0.0),
    "Sclera": ((0.6, 0.5, 0.44, 1), 0.08, 0.0),
    "Iris": ((0.024, 0.011, 0.006, 1), 0.04, 0.0),
    "Eye": ((0.004, 0.003, 0.003, 1), 0.03, 0.0),  # the pupil
    "Catchlight": ((1, 1, 1, 1), 0.3, 0.0),
    "Tongue": ((0.6, 0.22, 0.26, 1), 0.3, 0.0),
    "Mouth": ((0.16, 0.025, 0.035, 1), 0.5, 0.0),
    "Pad": ((0.03, 0.027, 0.027, 1), 0.8, 0.0),  # paw pads: rough, leathery
    "Tooth": ((0.82, 0.78, 0.68, 1), 0.3, 0.0),
}


# --- Mesh -------------------------------------------------------------------
# The fur is one smooth surface made of metaballs (so the body, legs and head blend
# like flesh), converted to a mesh and skinned with automatic weights. Small parts
# (eyes, nose, ears, tail, nails, collar) are separate rigid pieces on one bone each.


def stiff_k(stiffness, threshold=0.6):
    """Fraction of a metaball's radius where its surface sits (alone)."""
    return math.sqrt(1 - (threshold / stiffness) ** (1 / 3))


def quat_x_to(direction):
    return Vector(direction).normalized().to_track_quat("X", "Z")


class Blob:
    """Metaballs, built `SCALE` times too big: Blender won't polygonize them finer
    than 5 mm, so `blob_mesh` shrinks the mesh back afterwards."""

    SCALE = 2.0

    def __init__(self, resolution):
        self.mb = bpy.data.metaballs.new("PugBlob")
        self.mb.resolution = resolution * self.SCALE
        self.mb.render_resolution = resolution * self.SCALE
        self.mb.threshold = 0.6

    def ell(self, center, semi, stiffness=2.5, rot=None, negative=False):
        """Ellipsoid with visible semi-axes `semi` (when alone)."""
        k = stiff_k(stiffness)
        r = max(semi) / k * self.SCALE
        e = self.mb.elements.new(type="ELLIPSOID")
        e.co, e.radius, e.stiffness, e.use_negative = Vector(center) * self.SCALE, r, stiffness, negative
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
        e.co = (a + b) / 2 * self.SCALE
        e.radius = radius / stiff_k(stiffness) * self.SCALE
        e.size_x = (b - a).length / 2 * self.SCALE
        e.rotation = quat_x_to(b - a)
        e.stiffness, e.use_negative = stiffness, negative
        return e


# Toes as (sideways offset, x): the middle two reach a little further forward.
FRONT_TOES = [(dy, WRIST[0] + 0.062 + (0.009 if abs(dy) < 0.01 else 0)) for dy in (-0.027, -0.0095, 0.0095, 0.027)]
HIND_TOES = [(dy, ANKLE[0] + 0.068 + (0.008 if abs(dy) < 0.01 else 0)) for dy in (-0.024, -0.0085, 0.0085, 0.024)]
FRONT_TOE_Z, HIND_TOE_Z = 0.023, 0.021

NOSE = (0.549, 0, 0.624)
# The nose roll's arch as (y, x, z) points: highest over the middle of the nose.
NOSE_ROLL = [(y, 0.558 - abs(y) * 0.45, 0.67 - 10 * y * y) for y in (-0.07 + 0.0175 * i for i in range(9))]
RESOLUTION = 0.003  # metaball grid (m); decimated afterwards, keeping the detail


def fur_blob():
    b = Blob(resolution=RESOLUTION)
    # Torso: a deep, broad barrel of a ribcage, a short loin and a round rump, the
    # forechest jutting between the front legs and the shoulder blades and buttocks
    # showing under the skin. Square: as long as it is tall.
    b.ell((0.12, 0, 0.405), (0.165, 0.172, 0.165))
    b.ell((0.215, 0, 0.37), (0.075, 0.105, 0.11), stiffness=3)  # forechest
    b.ell((-0.02, 0, 0.415), (0.16, 0.158, 0.15))
    b.ell((-0.155, 0, 0.425), (0.12, 0.152, 0.14))
    b.ell((-0.205, 0, 0.395), (0.075, 0.125, 0.115), stiffness=3)  # buttocks
    # Neck, thick and short, the loose skin of the throat hanging under it.
    b.cap((0.19, 0, 0.47), (0.31, 0, 0.585), 0.112)
    b.ell((0.275, 0, 0.452), (0.075, 0.09, 0.055), stiffness=3)
    # Head: a big round skull, broader than it is tall, on a flat face with full
    # cheeks and a muzzle so short the nose sits between the eyes.
    b.ell((0.37, 0, 0.668), (0.145, 0.162, 0.125))
    b.ell((0.452, 0, 0.632), (0.092, 0.15, 0.108))
    for s in (1, -1):
        # Flews: the heavy upper lips hanging past the lower jaw at each side,
        # squaring off the muzzle.
        b.ell((0.49, s * 0.07, 0.566), (0.062, 0.066, 0.052), stiffness=2.5)
        b.ell((0.452, s * 0.105, 0.556), (0.05, 0.05, 0.04), stiffness=3)  # lip corners
        b.ell((0.415, s * 0.13, 0.625), (0.07, 0.044, 0.078), stiffness=3)  # cheeks
        # Brows: heavy, the inner ends raised (the worried pug look).
        b.ell((0.482, s * 0.074, 0.737), (0.028, 0.044, 0.014), stiffness=3, rot=Quaternion((1, 0, 0), math.radians(-18 * s)))
        # Eye sockets, so the eyes sit in the face rather than on it.
        b.ball((0.5, s * 0.085, 0.672), 0.028, stiffness=4, negative=True)
        # Muzzle pads either side of the philtrum, under the nose.
        b.ell((0.536, s * 0.036, 0.584), (0.037, 0.043, 0.035), stiffness=3)
    b.ell((0.517, 0, 0.568), (0.04, 0.066, 0.03), stiffness=3)  # upper lip
    # The over-nose wrinkle: a thick roll of skin draped across the face over the
    # nose, its ends running down beside it (the creases come from `sculpt`).
    for y, x, z in NOSE_ROLL:
        b.ball((x, y, z), 0.027, stiffness=4.5)
    for side, s in (("L", 1), ("R", -1)):
        m = lambda p: (p[0], s * p[1], p[2])  # noqa: E731
        fore = tuple(a + (c - a) * 0.45 for a, c in zip(ELBOW, WRIST))
        # Front leg: shoulder blade, the big triceps behind the upper arm, the point of
        # the elbow, a forearm tapering to the wrist, a short pastern, a tight paw.
        b.ell(m((0.145, 0.104, 0.45)), (0.075, 0.034, 0.088), stiffness=3, rot=Quaternion((0, 1, 0), math.radians(25)))
        b.ell(m((0.15, 0.1, 0.37)), (0.085, 0.066, 0.1), stiffness=3)
        b.ell(m((0.112, 0.112, 0.305)), (0.058, 0.052, 0.07), stiffness=3)  # triceps
        b.cap(m(SHOULDER), m(ELBOW), 0.054)
        b.ball(m((0.112, 0.118, 0.232)), 0.034, stiffness=3.5)  # elbow
        b.cap(m(ELBOW), m(fore), 0.046, stiffness=3)
        b.cap(m(fore), m(WRIST), 0.038, stiffness=3)
        b.ball(m((WRIST[0] - 0.004, WRIST[1], WRIST[2] + 0.006)), 0.036, stiffness=3.5)  # carpus
        b.ell(m((WRIST[0] + 0.03, WRIST[1], 0.033)), (0.05, 0.044, 0.031), stiffness=3)
        for dy, x in FRONT_TOES:
            b.ell(m((x, WRIST[1] + dy, FRONT_TOE_Z)), (0.0175, 0.0135, 0.0155), stiffness=4.5)
        # Hind leg: a broad muscular thigh, the hamstrings behind it, the stifle, a
        # gaskin narrowing to the point of the hock, a short upright hock, the paw.
        b.ell(m((-0.135, 0.098, 0.355)), (0.105, 0.07, 0.125), stiffness=3, rot=Quaternion((0, 1, 0), math.radians(-12)))
        b.ell(m((-0.2, 0.086, 0.33)), (0.062, 0.056, 0.09), stiffness=3)  # hamstrings
        b.cap(m(HIP), m(STIFLE), 0.064)
        b.ell(m((-0.1, 0.085, 0.3)), (0.075, 0.06, 0.075), stiffness=3)  # flank, joining the stifle to the belly
        b.ball(m(STIFLE), 0.044, stiffness=3)
        gaskin = tuple(a + (c - a) * 0.4 for a, c in zip(STIFLE, HOCK))
        b.cap(m(STIFLE), m(gaskin), 0.051, stiffness=3)
        b.cap(m(gaskin), m(HOCK), 0.035, stiffness=3)
        b.ball(m((HOCK[0] - 0.017, HOCK[1], HOCK[2] + 0.006)), 0.024, stiffness=4)  # point of the hock
        b.cap(m(HOCK), m(ANKLE), 0.029, stiffness=3)
        b.ell(m((ANKLE[0] + 0.034, ANKLE[1], 0.031)), (0.048, 0.04, 0.03), stiffness=3)
        for dy, x in HIND_TOES:
            b.ell(m((x, ANKLE[1] + dy, HIND_TOE_Z)), (0.0165, 0.0125, 0.0145), stiffness=4.5)
    return b.mb


def catmull(points, samples):
    """`samples` points along a Catmull-Rom curve through `points`."""
    pts = [Vector(p) for p in points]
    pts = [2 * pts[0] - pts[1]] + pts + [2 * pts[-1] - pts[-2]]
    out = []
    for i in range(samples):
        u = i / (samples - 1) * (len(pts) - 3)
        k = min(int(u), len(pts) - 4)
        t = u - k
        p0, p1, p2, p3 = pts[k:k + 4]
        out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    return out


class Sculpt:
    """Wrinkles, folds and muscle lines cut into the dense fur surface before it is
    decimated: each is a curve laid on the surface, pushing the vertices near it in
    (a crease) or out (a ridge) along their normals."""

    def __init__(self, mesh):
        self.mesh = mesh
        n = len(mesh.vertices)
        self.co = np.empty(n * 3)
        self.no = np.empty(n * 3)
        mesh.vertices.foreach_get("co", self.co)
        mesh.vertices.foreach_get("normal", self.no)
        self.co.shape = self.no.shape = (n, 3)
        self.disp = np.zeros(n)
        self.surface = Surface(mesh)

    def line(self, points, width, depth, samples=40, taper=0.6):
        """depth > 0 cuts a crease `width` wide, < 0 raises a ridge. Fades out at the ends."""
        path = np.array([tuple(self.surface.nearest(p)[0]) for p in catmull(points, samples)])
        lo, hi = path.min(0) - 3 * width, path.max(0) + 3 * width
        idx = np.nonzero(np.all((self.co > lo) & (self.co < hi), axis=1))[0]
        q = self.co[idx]
        lengths = np.linalg.norm(np.diff(path, axis=0), axis=1)
        start = np.concatenate([[0], np.cumsum(lengths)])
        best, along = np.full(len(idx), np.inf), np.zeros(len(idx))
        for i in range(len(path) - 1):
            a, ab = path[i], path[i + 1] - path[i]
            t = np.clip((q - a) @ ab / max(ab @ ab, 1e-12), 0, 1)
            d = np.linalg.norm(q - (a + t[:, None] * ab), axis=1)
            closer = d < best
            best[closer], along[closer] = d[closer], (start[i] + t[closer] * lengths[i]) / start[-1]
        fade = np.sin(np.pi * np.clip(along, 0, 1)) ** taper
        self.disp[idx] -= depth * np.exp(-(best / width) ** 2) * fade

    def fold(self, points, width, depth, side, samples=40):
        """A skin fold: a crease with the skin rolled up beside it, toward `side`."""
        self.line(points, width, depth, samples)
        off = Vector(side) * width * 1.5
        self.line([Vector(p) + off for p in points], width * 1.6, -depth * 0.45, samples)

    def apply(self, smooth=4):
        """Moves the vertices, after blurring the displacement over `smooth` rings of
        neighbors so the creases come out soft-edged rather than stepped."""
        edges = np.empty(len(self.mesh.edges) * 2, dtype=np.int64)
        self.mesh.edges.foreach_get("vertices", edges)
        a, b = edges[0::2], edges[1::2]
        count = np.bincount(a, minlength=len(self.disp)) + np.bincount(b, minlength=len(self.disp))
        for _ in range(smooth):
            total = np.bincount(a, self.disp[b], len(self.disp)) + np.bincount(b, self.disp[a], len(self.disp))
            self.disp = 0.5 * self.disp + 0.5 * total / np.maximum(count, 1)
        self.mesh.vertices.foreach_set("co", (self.co + self.no * self.disp[:, None]).ravel())
        self.mesh.update()


def sculpt(mesh):
    """The pug's wrinkles. Returns how deep each vertex sits in a crease (0-1)."""
    sc = Sculpt(mesh)
    # The over-nose wrinkle: deep creases under the roll (against the nose) and above
    # it (under the eyes), running down beside the nose at the ends.
    under = [(x + 0.006, y, z - 0.03) for y, x, z in NOSE_ROLL]
    over = [(x - 0.012, y, z + 0.029) for y, x, z in NOSE_ROLL]
    sc.line(under, 0.006, 0.013, taper=0.3)
    sc.line(over, 0.0065, 0.011, taper=0.4)
    # Forehead: the "thumbprint", a diamond of furrows between the brows, and the
    # wavy folds across the forehead above it, running out over the eyes.
    sc.line([(0.53, 0, 0.73), (0.52, -0.02, 0.765), (0.49, -0.034, 0.8)], 0.0055, 0.006)
    sc.line([(0.53, 0, 0.73), (0.52, 0.02, 0.765), (0.49, 0.034, 0.8)], 0.0055, 0.006)
    sc.line([(0.53, 0, 0.71), (0.52, 0, 0.765), (0.49, 0, 0.81)], 0.005, 0.005)
    for k, (z, w) in enumerate(((0.772, 0.085), (0.795, 0.09), (0.815, 0.085))):
        wave = 0.006 * (-1) ** k
        pts = [(0.5 - 0.06 * abs(y) / w - 0.02 * k, y, z + wave * math.cos(math.pi * y / w) - 0.035 * (y / w) ** 2)
               for y in np.linspace(-w, w, 7)]
        sc.fold(pts, 0.005, 0.0055, (0, 0, -1))
    for s in (1, -1):
        # A fold from the brow curving down behind the eye onto the cheek.
        sc.fold([(0.47, s * 0.115, 0.735), (0.455, s * 0.135, 0.69), (0.46, s * 0.135, 0.635), (0.48, s * 0.12, 0.6)], 0.005, 0.006, (0.6, -s * 0.4, 0))
        # The mouth corner, and the crease where the flews meet the cheek.
        sc.line([(0.43, s * 0.122, 0.585), (0.445, s * 0.118, 0.56), (0.462, s * 0.108, 0.54)], 0.005, 0.006)
        sc.line([(0.5, s * 0.104, 0.605), (0.49, s * 0.118, 0.575), (0.475, s * 0.12, 0.55)], 0.0045, 0.004)
        # Neck rolls behind the jaw, and a fold of loose skin at the throat.
        neck0, neck1 = Vector((0.19, 0, 0.47)), Vector((0.31, 0, 0.585))
        throat = Vector((0, 1, 0)).cross(neck1 - neck0).normalized()
        for t, d in ((0.62, 0.008), (0.8, 0.007)):
            c = neck0.lerp(neck1, t)
            ring_pts = [c + 0.115 * (math.cos(a) * throat + s * math.sin(a) * Vector((0, 1, 0))) for a in np.linspace(0.1, 2.4, 8)]
            sc.fold(ring_pts, 0.006, d, -(neck1 - neck0).normalized())
        # Muscle lines: behind the shoulder blade, between triceps and forearm,
        # down the hamstrings.
        sc.line([(0.1, s * 0.13, 0.46), (0.085, s * 0.14, 0.39), (0.08, s * 0.135, 0.33)], 0.012, 0.003)
        sc.line([(-0.175, s * 0.13, 0.43), (-0.2, s * 0.125, 0.35), (-0.205, s * 0.11, 0.27)], 0.012, 0.003)
        # Grooves between the toes.
        for toes, (wx, wy, _), z in ((FRONT_TOES, WRIST, FRONT_TOE_Z), (HIND_TOES, ANKLE, HIND_TOE_Z)):
            for (dy0, x0), (dy1, x1) in zip(toes, toes[1:]):
                y = s * (wy + (dy0 + dy1) / 2)
                x = (x0 + x1) / 2
                sc.line([(x - 0.03, y, z + 0.02), (x - 0.012, y, z + 0.016), (x + 0.008, y, z + 0.004)], 0.0035, 0.004)
    # The philtrum: a groove down the middle of the upper lip from the nose.
    sc.line([(0.565, 0, 0.603), (0.562, 0, 0.59), (0.556, 0, 0.574)], 0.0045, 0.006, taper=0.3)
    sc.apply()
    return np.clip(np.maximum(sc.disp, -0.012) / -0.008, 0, 1)


def chin_blob():
    """The lower jaw, a separate piece so the mouth can open: tucked under the
    jowls, with a slight underbite."""
    b = Blob(resolution=0.005)
    b.ell((0.49, 0, 0.532), (0.062, 0.075, 0.03), stiffness=3)
    b.ell((0.43, 0, 0.535), (0.06, 0.08, 0.035), stiffness=3)
    return b.mb


def blob_mesh(mb, ratio, shape=None):
    """Metaballs -> mesh, then `shape(mesh)` (a sculpt pass returning a value per
    vertex), then decimated by `ratio`. With `shape`, returns (mesh, that value
    carried over to the decimated vertices)."""
    blob = bpy.data.objects.new("Blob", mb)
    bpy.context.scene.collection.objects.link(blob)
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(blob.evaluated_get(dg))
    bpy.data.objects.remove(blob)
    mesh.transform(Matrix.Scale(1 / Blob.SCALE, 4))
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    bm.to_mesh(mesh)
    bm.free()
    values = shape(mesh) if shape else None
    if values is not None:
        dense = KDTree(len(mesh.vertices))
        for v in mesh.vertices:
            dense.insert(v.co, v.index)
        dense.balance()
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
    if values is None:
        return mesh
    return mesh, np.array([values[dense.find(v.co)[1]] for v in mesh.vertices])


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


class Surface:
    """Nearest point and smooth normal on a mesh, to lay parts on the fur."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.tree = BVHTree.FromPolygons([v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons])

    def nearest(self, p):
        loc, _, index, _ = self.tree.find_nearest(p)
        normal = sum((self.mesh.vertices[i].normal for i in self.mesh.polygons[index].vertices), Vector()).normalized()
        return loc, normal


def ear(parts, s, surface):
    """A button ear: a thin, soft triangular flap set high on the skull and folded
    forward, its tip lying against the head toward the outer corner of the eye. Its
    widest edge is the fold, a rounded ridge along the top; the flap follows the
    skull, cupped so its edges meet it."""
    root, tip, _ = ear_frame(s)
    down = (tip - root).normalized()
    _, out = surface.nearest((root + tip) / 2)
    across = down.cross(out).normalized()
    length, half_width = (tip - root).length, 0.05
    rows, sides = 18, 16
    grid = []
    for i in range(rows + 1):
        u = -0.08 + 1.08 * i / rows  # below 0: rounding off the fold
        cap = math.sqrt(max(0.0, 1 - (u / 0.08) ** 2)) if u < 0 else 1.0
        width = half_width * (1 - u) ** 0.7 * (0.35 + 0.65 * cap) if u < 1 else 0.0
        thick = (0.0035 + 0.008 * (1 - u) ** 3) * cap
        row = []
        for j in range(sides):
            ang = 2 * math.pi * j / sides
            a, t = math.cos(ang), math.sin(ang)
            on, normal = surface.nearest(root + down * (length * u) + across * (width * a))
            lift = 0.003 + 0.012 * (1 - max(u, 0)) ** 2 + 0.007 * (1 - a * a) * (width / half_width)
            row.append(parts.bm.verts.new(on + normal * (lift + thick * t)))
        grid.append(row)
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(sides):
            parts.bm.faces.new((r0[j], r1[j], r1[(j + 1) % sides], r0[(j + 1) % sides]))
    for row, flip in ((grid[0], True), (grid[-1], False)):
        parts.bm.faces.new(row[::-1] if flip else row)
    verts = [v for r in grid for v in r]
    bmesh.ops.remove_doubles(parts.bm, verts=verts, dist=1e-6)
    verts = [v for v in verts if v.is_valid]
    bmesh.ops.recalc_face_normals(parts.bm, faces=list({f for v in verts for f in v.link_faces}))
    parts.assign(verts, f"ear.{'L' if s > 0 else 'R'}", "Fur")


def curled_tail(parts):
    """Rises off the rump and rolls into a tight double curl lying on the hip, each
    turn resting against the last."""
    base = Vector((-0.21, 0, 0.5))
    center = Vector((-0.17, -0.015, 0.59))
    normal = Vector((0.1, -0.4, 1)).normalized()  # the coil lies on the hip, tipped toward the camera
    u_axis = Vector((-1, 0, 0))
    u_axis = (u_axis - normal * u_axis.dot(normal)).normalized()
    v_axis = normal.cross(u_axis)
    r0, pitch, turns = 0.068, 0.046, 1.35

    def coil(u):
        ang = -2 * math.pi * turns * u
        r = r0 - pitch * turns * u
        return center + r * (math.cos(ang) * u_axis + math.sin(ang) * v_axis) + normal * (0.014 * u)

    start = coil(0)
    tangent = (coil(0.01) - start).normalized()
    pts, radii = [], []
    for i in range(12):  # root: up out of the rump, then over into the coil
        t = i / 12
        c1, c2 = base + Vector((0, 0, 0.06)), start - tangent * 0.05
        pts.append((1 - t) ** 3 * base + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t * t * c2 + t ** 3 * start)
        radii.append(0.034 - 0.003 * t)
    n = 70
    for i in range(n):
        u = i / (n - 1)
        pts.append(coil(u))
        radii.append(0.031 - 0.019 * u ** 1.3)
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
            # A flat band, its edges rounded off (a squarish superellipse section).
            cb, sb = math.cos(b), math.sin(b)
            r = 0.12 + 0.006 * math.copysign(abs(cb) ** 0.35, cb)
            z = 0.019 * math.copysign(abs(sb) ** 0.35, sb)
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


def ring(bm, points, radius, sides=8):
    """A closed tube through `points` (a loop), returns its verts."""
    n = len(points)
    rings = []
    for i, p in enumerate(points):
        t = (Vector(points[(i + 1) % n]) - Vector(points[i - 1])).normalized()
        out = (Vector(p) - sum((Vector(q) for q in points), Vector()) / n)
        out = (out - t * out.dot(t)).normalized()
        up = t.cross(out)
        rings.append([bm.verts.new(Vector(p) + radius * (math.cos(2 * math.pi * j / sides) * out + math.sin(2 * math.pi * j / sides) * up))
                      for j in range(sides)])
    for i in range(n):
        r0, r1 = rings[i], rings[(i + 1) % n]
        for j in range(sides):
            bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    return [v for r in rings for v in r]


def eye(parts, s):
    """A dark eye looking forward and a little out: the brown iris nearly fills the
    opening, with a sliver of white at the corners, framed by a black eyelid rim.
    The eyeball outside the opening is black skin, so no white shows past the lids."""
    center, radius = Vector((0.486, s * 0.085, 0.672)), 0.034
    gaze = Vector((1, s * 0.4, 0.02)).normalized()
    side = Vector((0, 0, 1)).cross(gaze).normalized()
    up = gaze.cross(side)

    def opening(c, n):
        """Degrees from the gaze to the lid edge in direction (c, n): an almond, the
        upper lid a little lower over the eye."""
        return 1 / math.hypot(c / 57, n / (42 if n > 0 else 48))

    verts = uv_ellipsoid(parts.bm, center, (radius,) * 3, gaze.to_track_quat("Z", "Y"), segments=(40, 26))
    for v in verts:  # the cornea: a clear dome bulging over the iris, so the eye catches light like a wet lens
        d = (v.co - center).normalized()
        angle = math.degrees(d.angle(gaze))
        if angle < 46:
            v.co = center + d * (radius + 0.0045 * math.cos(math.radians(angle / 46 * 90)) ** 2)
    parts.assign(verts, "head", "Sclera")
    for f in {f for v in verts for f in v.link_faces}:
        d = (f.calc_center_median() - center).normalized()
        angle = math.degrees(d.angle(gaze))
        lid = opening(*Vector((d.dot(side), d.dot(up))).normalized()) if angle > 1 else 90
        f.material_index = list(MATERIALS).index("Skin" if angle > lid else "Eye" if angle < 22 else "Iris" if angle < 50 else "Sclera")
    rim = []
    for i in range(28):
        a = 2 * math.pi * i / 28
        c, n = math.cos(a), math.sin(a)
        deg = opening(c, n)
        d = gaze * math.cos(math.radians(deg)) + math.sin(math.radians(deg)) * (c * side + n * up)
        rim.append(center + d * (radius + 0.002))
    parts.assign(ring(parts.bm, rim, 0.0045), "head", "Skin")
    glint = center + (gaze + 0.38 * up - 0.18 * side).normalized() * (radius + 0.0003)
    parts.assign(uv_ellipsoid(parts.bm, glint, (0.003, 0.003, 0.003), segments=(10, 6)), "head", "Catchlight")


def face_parts(parts):
    eye(parts, 1)
    eye(parts, -1)
    # Nose: broad and flat-fronted, a little wider at the top, with comma-shaped nostrils.
    nose = uv_ellipsoid(parts.bm, NOSE, (0.018, 0.047, 0.026), segments=(48, 24))
    for v in nose:
        x, y, z = v.co - Vector(NOSE)
        v.co.y = y * (1 + 0.25 * z / 0.026)
        if x > 0.006:  # a flat front face
            v.co.x = NOSE[0] + 0.006 + (x - 0.006) * 0.3
        # Comma-shaped nostrils, slanting up and out, and a groove down the middle.
        for s in (1, -1):
            u, w = (y - s * 0.024) / 0.013, (z + 0.004 + 0.25 * (abs(y) - 0.024)) / 0.0075
            d = u * u + w * w
            if x > 0 and d < 1:
                v.co.x -= 0.014 * (1 - d) ** 0.7
        if x > 0:
            v.co.x -= 0.003 * math.exp(-(y / 0.004) ** 2) * (1 if z < 0 else 0.5)
    parts.assign(nose, "head", "Nose")
    # Inside of the mouth, seen when the jaw drops.
    parts.assign(uv_ellipsoid(parts.bm, (0.475, 0, 0.553), (0.065, 0.058, 0.016)), "head", "Mouth")
    parts.assign(uv_ellipsoid(parts.bm, (0.47, 0, 0.545), (0.06, 0.055, 0.012)), "jaw", "Mouth")
    tongue = uv_ellipsoid(parts.bm, (0.515, 0.004, 0.547), (0.05, 0.034, 0.01), Quaternion((0, 1, 0), math.radians(12)))
    parts.assign(tongue, "jaw", "Tongue")
    # Teeth: six small lower incisors set in front of the upper ones (the pug's
    # underbite) between the lower canines, and the upper canines.
    for y in (-0.027, -0.017, -0.006, 0.006, 0.017, 0.027):
        tilt = Quaternion((0, 1, 0), math.radians(-15)) @ Quaternion((1, 0, 0), math.radians(-y * 400))
        tooth = uv_ellipsoid(parts.bm, (0.541 - 9 * y * y, y, 0.557), (0.0032, 0.0046, 0.0075), tilt, segments=(10, 6))
        parts.assign(tooth, "jaw", "Tooth")
    for s in (1, -1):
        for bone, x, y, z, up in (("jaw", 0.527, 0.037, 0.56, 1), ("head", 0.516, 0.04, 0.567, -1)):
            tip_dir = Vector((0.15, s * 0.1, up)).normalized()
            fang = bmesh.ops.create_cone(
                parts.bm, cap_ends=True, segments=10, radius1=0.0048, radius2=0.0008, depth=0.015,
                matrix=Matrix.Translation(Vector((x, s * y, z)) + tip_dir * 0.006) @ tip_dir.to_track_quat("Z", "Y").to_matrix().to_4x4(),
            )["verts"]
            parts.assign(fang, bone, "Tooth")
    # The lower jaw.
    chin = blob_mesh(chin_blob(), 0.3)
    verts = [parts.bm.verts.new(v.co) for v in chin.vertices]
    for poly in chin.polygons:
        parts.bm.faces.new([verts[i] for i in poly.vertices])
    parts.assign(verts, "jaw", "Fur")
    bpy.data.meshes.remove(chin)


def nails(parts):
    """A short black claw at the tip of every toe, and the pads under the paws: one
    under each toe, the big heart-shaped pad behind them, and the carpal pad high on
    the back of each front wrist."""
    for side, s in (("L", 1), ("R", -1)):
        for toes, (px, y0, _), bone in ((FRONT_TOES, WRIST, "hand"), (HIND_TOES, ANKLE, "foot")):
            for dy, x in toes:
                pad = uv_ellipsoid(parts.bm, (x - 0.003, s * (y0 + dy), 0.0068), (0.0115, 0.0095, 0.0068), segments=(14, 8))
                parts.assign(pad, f"{bone}.{side}", "Pad")
            for dy in (-0.011, 0.011):  # the two lobes of the heart
                pad = uv_ellipsoid(parts.bm, (px + 0.027, s * (y0 + dy), 0.0082), (0.019, 0.0145, 0.008),
                                   Quaternion((0, 0, 1), math.radians(-s * dy * 1400)), segments=(16, 8))
                parts.assign(pad, f"{bone}.{side}", "Pad")
        carpal = uv_ellipsoid(parts.bm, (WRIST[0] - 0.033, s * WRIST[1], 0.078), (0.007, 0.011, 0.0095), segments=(12, 8))
        parts.assign(carpal, f"forearm.{side}", "Pad")
    for side, s in (("L", 1), ("R", -1)):
        for toes, y0, radius, bone in ((FRONT_TOES, WRIST[1], 0.015, "hand"), (HIND_TOES, ANKLE[1], 0.014, "foot")):
            z = FRONT_TOE_Z if bone == "hand" else HIND_TOE_Z
            for dy, x in toes:
                tip_dir = Vector((1, s * dy * 4, -0.9)).normalized()
                base = Vector((x + radius * 0.6, s * (y0 + dy), z - radius * 0.15))
                cone = bmesh.ops.create_cone(
                    parts.bm, cap_ends=True, segments=10, radius1=0.0045, radius2=0.0008, depth=0.014,
                    matrix=Matrix.Translation(base + tip_dir * 0.005) @ tip_dir.to_track_quat("Z", "Y").to_matrix().to_4x4(),
                )["verts"]
                parts.assign(cone, f"{bone}.{side}", "Nail")


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
        if name == "Fur":
            bsdf.inputs["Sheen Weight"].default_value = 0.6
            bsdf.inputs["Sheen Roughness"].default_value = 0.4
        if name == "Catchlight":
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = 0.3
        mats.append(mat)

    # Fur: metaballs -> mesh -> automatic weights.
    fur_mesh, crease = blob_mesh(fur_blob(), 0.13, sculpt)
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
    surface = Surface(fur_mesh)
    ear(parts, 1, surface)
    ear(parts, -1, surface)
    curled_tail(parts)
    collar(parts)
    nails(parts)
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
    # For the fur shader: every vertex's rest position, and how sheltered it is.
    ao = occlusion([fur_mesh, parts_mesh])
    rest_uvs(fur_mesh, ao[:len(fur_mesh.vertices)] * (1 - 0.65 * crease))
    rest_uvs(parts_mesh, ao[len(fur_mesh.vertices):])
    return fur, obj


def occlusion(meshes, reach=0.06, rays=20):
    """Per vertex, 1 minus the share of the sky above it that nearby surfaces hide
    (ambient occlusion at rest, rays out to `reach`), for every vertex of `meshes`."""
    verts, polys = [], []
    for mesh in meshes:
        base = len(verts)
        verts += [v.co.copy() for v in mesh.vertices]
        polys += [[base + i for i in p.vertices] for p in mesh.polygons]
    tree = BVHTree.FromPolygons(verts, polys)
    golden = math.pi * (3 - math.sqrt(5))
    dirs = []  # cosine-weighted hemisphere around +Z
    for i in range(rays):
        r = math.sqrt((i + 0.5) / rays)
        dirs.append(Vector((r * math.cos(golden * i), r * math.sin(golden * i), math.sqrt(1 - r * r))))
    out = []
    for mesh in meshes:
        for v in mesh.vertices:
            rot = v.normal.to_track_quat("Z", "Y")
            start = v.co + v.normal * 0.0015
            hidden = 0.0
            for d in dirs:
                hit = tree.ray_cast(start, rot @ d, reach)[0]
                if hit is not None:
                    hidden += 1 - (hit - start).length / reach
            out.append(1 - hidden / rays)
    return np.array(out)


def rest_uvs(mesh, shade):
    """UV = rest (x, z), UV2 = (rest y, shade), for godot/shaders/fur.gdshader: the
    hair is laid out in rest space, so it stays put on the skin however the bones
    move, and `shade` darkens the creases."""
    vi = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", vi)
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)[vi]
    mesh.uv_layers.new(name="RestXZ").data.foreach_set("uv", co[:, [0, 2]].ravel())
    mesh.uv_layers.new(name="RestYShade").data.foreach_set("uv", np.stack([co[:, 1], np.asarray(shade)[vi]], 1).ravel())


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
        # The elbow points back; reaching up over a ledge, it points back and down.
        shoulder = fk(pose)[f"upper_arm.{side}"][0]
        turn = two_bone(pose, f"upper_arm.{side}", f"forearm.{side}", target, 1 if target[1] > shoulder[1] + 0.12 else -1)
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


# --- Ledge getups -------------------------------------------------------------
# The sim hangs the pug with its origin 0.1 m outside the edge and the top of its
# 0.9 m hurtbox level with the platform, then slides the origin in a straight line
# to standing `reach` m along on getups (sim/src/fighter.rs: ledge_getup_pos). Keys
# here are poses plus where their origin sits relative to the ledge corner ("corner
# space": x onto the stage, z up, the stage top at z = 0, the wall at x = 0), so paws
# stay planted on the ledge while the clip's origin moves under them.
H = 0.9
HANG_AT = (-0.1, -H)  # the hanging origin, corner space


def origin(frame, length, reach):
    """Corner-space position of the model's origin on `frame` of a getup."""
    t = frame / length if length else 0.0
    return HANG_AT[0] + reach * t, HANG_AT[1] + H * t


def flatten(pose):
    """Solved pose -> {bone: (a, b, c)} plus "loc"."""
    out = {name: (value if isinstance(value, tuple) else (value, 0, 0)) for name, value in pose.items() if name not in ("loc", "feet")}
    out["loc"] = pose.get("loc", (0, 0))
    return out


def spline(times, values, t):
    """Catmull-Rom through (times, values) at t; values are tuples or None (gaps
    end a curve). Returns None where the bracketing values are missing."""
    k = max(i for i in range(len(times)) if times[i] <= t)
    if k == len(times) - 1:
        return values[k]
    p1, p2 = values[k], values[k + 1]
    if p1 is None or p2 is None:
        return None
    t1, t2 = times[k], times[k + 1]
    p0, t0 = (values[k - 1], times[k - 1]) if k > 0 and values[k - 1] is not None else (p1, t1)
    p3, t3 = (values[k + 2], times[k + 2]) if k + 2 < len(times) and values[k + 2] is not None else (p2, t2)
    u, d = (t - t1) / (t2 - t1), t2 - t1
    h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    out = []
    for a0, a1, a2, a3 in zip(p0, p1, p2, p3):
        m1 = (a2 - a0) / (t2 - t0) * d if t2 > t0 else 0.0
        m2 = (a3 - a1) / (t3 - t1) * d if t3 > t1 else 0.0
        out.append(h00 * a1 + h10 * m1 + h01 * a2 + h11 * m2)
    return tuple(out)


def ledge_clip(keys, length=0, reach=0.0, first=None, last=None):
    """One key per frame from (frame, pose, at) keys: `pose` drawn with its origin at
    corner-space `at` (None: standing on the stage right under the clip's origin).
    Between keys every value follows a Catmull-Rom curve; a paw planted at both ends
    of a stretch keeps its corner-space spot (also curved), re-planted by IK."""
    frames, solved = [], []
    for frame, pose, at in keys:
        ox, oz = origin(frame, length, reach)
        ax, az = at if at is not None else (ox, 0.0)
        dx, dz = ax - ox, az - oz
        pose = dict(pose)
        fwd, up = pose.get("loc", (0, 0))
        pose["loc"] = (fwd + dx, up + dz)
        feet = {}
        for leg, spec in pose.get("feet", {}).items():
            spec = tuple(spec) + (0.0,) * (4 - len(spec))
            pose_feet = (spec[0] + dx, spec[1] + dz) + spec[2:]
            feet[leg] = pose_feet
        pose["feet"] = feet
        targets = {}
        for leg, spec in feet.items():
            if not any(b in pose for b in LEG_BONES[leg]):
                base = FRONT_PAW if leg[0] == "F" else HIND_PAW
                targets[leg] = (base[0] + spec[0] + ox, base[1] + spec[1] + oz, spec[2], spec[3])
        frames.append(frame)
        solved.append((flatten(solve(pose)), targets))
    names = sorted({n for flat, _ in solved for n in flat})
    out = []
    for f in range(first or frames[0], (last or frames[-1]) + 1):
        pose = {}
        for name in names:
            value = spline(frames, [flat.get(name, (0, 0, 0) if name != "loc" else (0, 0)) for flat, _ in solved], f)
            pose[name] = tuple(value) if name == "loc" else (value if any(abs(v) > 1e-9 for v in value[1:]) else value[0])
        ox, oz = origin(f, length, reach)
        for leg in ("FR", "FL", "HR", "HL"):
            target = spline(frames, [tg.get(leg) for _, tg in solved], f)
            if target is not None:
                base = FRONT_PAW if leg[0] == "F" else HIND_PAW
                for b in LEG_BONES[leg]:
                    pose.pop(b, None)
                plant(pose, leg, target[0] - ox - base[0], target[1] - oz - base[1], target[2], target[3])
        out.append((f, pose))
    return out


def hang_feet(fr=(0.03, 0.0), fl=(0.05, 0.0), hr=(0.04, 0.12, 70, 40), hl=(0.0, 0.05, 60, 30)):
    """Hang-frame paw targets: the front wrists just over the corner (x, z offsets
    from it), the hind ankles at model-space (x, z, paw, hock) against the wall."""
    feet = {}
    for leg, (x, z) in (("FR", fr), ("FL", fl)):
        feet[leg] = (0.1 + x - FRONT_PAW[0], H + z, -5)
    for leg, (x, z, paw, hock) in (("HR", hr), ("HL", hl)):
        feet[leg] = (x - HIND_PAW[0], z - HIND_PAW[1], paw, hock)
    return feet


# Hanging: front paws hooked over the corner, chest against the wall, head peeking
# over the edge, hind legs dangling and scrabbling at the wall.
HANG = P(loc=(-0.1, 0.13), body=72, chest=-4, neck=-30, head=-36, jaw=-8, ears=(20, 0, 0), tail=(-25, 0, 0), feet=hang_feet())
HANG_B = P(HANG, loc=(-0.104, 0.118), body=75, neck=-28, head=-40, jaw=-14, ears=(30, 0, 0), tail=(-25, 20, 0),
           feet=hang_feet(hr=(0.05, 0.3, 80, 45), hl=(-0.04, 0.0, 40, 20)))
HANG_C = P(HANG, loc=(-0.096, 0.124), body=70, neck=-32, head=-32, jaw=-6, ears=(15, 0, 0), tail=(-25, -20, 0),
           feet=hang_feet(hr=(-0.02, 0.03, 40, 20), hl=(0.05, 0.28, 80, 45)))
# Hauling up: elbows bend, chest rises over the corner, a hind paw pushes off the wall.
HOIST = P(loc=(-0.02, 0.33), body=50, chest=-6, neck=-14, head=-26, jaw=-14, ears=(35, 0, 0), tail=(-20, 0, 0),
          feet=hang_feet(hr=(0.07, 0.45, 85, 50), hl=(-0.04, 0.2, 40, 20)))
OVER = P(loc=(0.14, 0.68), body=14, chest=-4, neck=-8, head=-4, jaw=-10, ears=(25, 0, 0), tail=(0, 20, 0),
         feet={**hang_feet(fr=(0.17, 0.0), fl=(0.02, 0.0)), "HR": (0.22, H, 10, 0), "HL": (0.22, 0.42, 70, 30)})
STEP_UP = stand(drop=0.03, chest=-3, neck=2, head=-2, jaw=-4, feet={"HL": (0.04, 0.07, 25)}, tail=(0, -20, 0))
# Getup attack: a low lunging bite at the ankles.
LEDGE_HOP = flying(0.6, body=8, neck=6, head=4, jaw=-20, ears=(50, 0, 0))
LEDGE_CROUCH = stand(fwd=-0.04, drop=0.1, front=0.04, hind=-0.04, chest=-4, pelvis=10, neck=-6, head=-2, jaw=-24, ears=(-20, 0, 0), tail=(0, 40, 0))
LEDGE_BITE = stand(fwd=0.15, drop=0.08, front=0.16, hind=-0.06, chest=-12, neck=-16, head=-4, jaw=-34, ears=(45, 0, 0), tail=(0, -20, 0))
LEDGE_CHOMP = P(LEDGE_BITE, jaw=0, head=-8)


# Rolling: curled up tight, paws folded against the chest and belly, chin tucked.
TUCK = P(BALL, loc=(0, -0.1), neck=-35, head=-35, jaw=-4, upper_arm_R=115, forearm_R=-150, hand_R=-30, upper_arm_L=110, forearm_L=-145,
         hand_L=-30, thigh_R=75, shin_R=-115, hock_R=70, foot_R=20, thigh_L=70, shin_L=-110, hock_L=70, foot_L=20, ears=(-20, 0, 0), tail=(-30, 0, 0))


def ledge_hang():
    """Loops on the world clock: a slow sway, the hind legs pedaling in turn."""
    keys = [(1, HANG), (21, HANG_B), (41, HANG), (61, HANG_C), (81, HANG)]
    keys = [(-19, HANG_C, HANG_AT)] + [(f, k, HANG_AT) for f, k in keys] + [(101, HANG_B, HANG_AT)]
    return ledge_clip(keys, first=1, last=81)


def ledge_climb():
    """20 frames; the origin slides 0.9 m in and 0.9 m up."""
    return ledge_clip([(1, HANG, HANG_AT), (6, HOIST, HANG_AT), (11, OVER, HANG_AT), (15, STEP_UP, (0.62, 0.0)), (20, G, None)], 20, 0.9)


def ledge_roll():
    """25 frames, 1.6 m in: hoist, then a tucked forward roll that pops up into idle."""
    keys = [(1, HANG, HANG_AT), (5, HOIST, HANG_AT), (8, P(TUCK, body=10), (0.12, 0.06))]
    for i, f in enumerate((10, 13, 16, 19)):
        keys.append((f, P(TUCK, body=-50 - 90 * i), (0.3 + 0.26 * i, 0.0)))
    return ledge_clip(keys + [(22, P(CROUCH, body=-360), (1.38, 0.0)), (25, P(G, body=-360), None)], 25, 1.6)


def ledge_attack():
    """30 frames, 1.1 m in: hops up and lunges, biting low on 15-18 around (0.6, 0.6)
    from the origin (the sim's LEDGE_ATTACK_HITBOX, radius 0.6)."""
    return ledge_clip([(1, HANG, HANG_AT), (5, HOIST, HANG_AT), (9, LEDGE_HOP, (0.2, 0.1)), (12, LEDGE_CROUCH, (0.45, 0.0)),
                       (15, LEDGE_BITE, (0.45, 0.0)), (17, LEDGE_CHOMP, (0.47, 0.0)), (19, LEDGE_CHOMP, (0.47, 0.0)),
                       (23, P(LEDGE_CROUCH, jaw=-4), (0.5, 0.0)), (26, P(LEDGE_HOP, loc=(0.0, 0.06)), (0.78, 0.0)), (30, G, None)], 30, 1.1)


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
    # Ledge: the hang loops; getups are keyed on their sim frames (see ledge_clip).
    "ledge_hang": ledge_hang(),
    "ledge_climb": ledge_climb(),
    "ledge_roll": ledge_roll(),
    "ledge_attack": ledge_attack(),
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
