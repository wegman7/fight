"""Builds the chef: a portly cook in chef's whites, toque and apron, its armature,
and one action per pose name the sim reports (`Fighter::anim()`), then saves
`fighter.blend` next to this script and exports `godot/models/fighter.glb`, plus the
flying pie for the pie throw (`godot/models/pie.glb`).

    blender --background --factory-startup --python art/fighter/build_fighter.py

Conventions (see README.md):
- Meters, feet at the origin, facing +X, character's left = +Y. The body is 1.2 m
  tall, matching the sim hurtbox (height 12 units, SCALE 0.1); the toque rises above it.
- 60 fps. Attack actions are keyed on the sim's 1-based move frames, so Blender
  frame 5 of `ftilt` is sim frame 5 of FTilt.
- Pose angles are degrees, counter-clockwise as seen by the game camera with the
  fighter facing right: + swings a hanging limb forward, tips an upright bone
  back, and raises the toes. Child angles are relative to the parent.
"""

import math
import os
import random

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "fighter.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "fighter.glb")
PIE_GLB_PATH = os.path.join(ROOT, "godot", "models", "pie.glb")

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
FIST = 0.055  # center of the fist, this far past the wrist
for side, s in (("L", 1), ("R", -1)):
    BONES += [
        (f"upper_arm.{side}", "spine", (0, s * SHOULDER[0], SHOULDER[1]), (0, s * ELBOW[0], ELBOW[1]), DOWN),
        (f"forearm.{side}", f"upper_arm.{side}", (0, s * ELBOW[0], ELBOW[1]), (0, s * WRIST[0], WRIST[1]), DOWN),
        (f"thigh.{side}", "hips", (0, s * HIP[0], HIP[1]), (0, s * KNEE[0], KNEE[1]), DOWN),
        (f"shin.{side}", f"thigh.{side}", (0, s * KNEE[0], KNEE[1]), (0, s * ANKLE[0], ANKLE[1]), DOWN),
        (f"foot.{side}", f"shin.{side}", (0, s * HIP[0], ANKLE[1]), (0.13, s * HIP[0], ANKLE[1]), FWD),
    ]
# The pie in the right (near) fist. Scaled to 0 except while the pie throw shows it.
PIE_PIVOT = (0, -SHOULDER[0], WRIST[1] - FIST)
BONES.append(("pie", "forearm.R", PIE_PIVOT, (0, -SHOULDER[0], WRIST[1] - FIST - 0.1), DOWN))
BONE_NAMES = [b[0] for b in BONES]
SEGMENTS = {b[0]: (Vector(b[2]), Vector(b[3])) for b in BONES}

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the apron
# and neckerchief) with the player's color; the rest keep their own.
MATERIALS = {
    "Body": ((0.70, 0.12, 0.12, 1), 0.75, 0.0),
    "Jacket": ((0.92, 0.92, 0.90, 1), 0.85, 0.0),
    "Pants": ((0.045, 0.045, 0.055, 1), 0.8, 0.0),
    "Skin": ((0.85, 0.62, 0.50, 1), 0.55, 0.0),
    "Lip": ((0.70, 0.40, 0.36, 1), 0.45, 0.0),
    "Hair": ((0.17, 0.11, 0.07, 1), 0.6, 0.0),
    "Shoe": ((0.02, 0.018, 0.017, 1), 0.28, 0.0),
    "Button": ((0.025, 0.025, 0.03, 1), 0.2, 0.0),
    "Sole": ((0.04, 0.03, 0.025, 1), 0.8, 0.0),
    "Lace": ((0.02, 0.02, 0.02, 1), 0.8, 0.0),
    "Towel": ((0.78, 0.77, 0.72, 1), 0.95, 0.0),
    "Nail": ((0.78, 0.6, 0.55, 1), 0.3, 0.0),
    "Eye": ((0.93, 0.91, 0.87, 1), 0.12, 0.0),
    "Iris": ((0.28, 0.17, 0.08, 1), 0.15, 0.0),
    "Pupil": ((0.01, 0.01, 0.01, 1), 0.1, 0.0),
    "Tin": ((0.78, 0.78, 0.80, 1), 0.3, 1.0),
    "Crust": ((0.80, 0.52, 0.24, 1), 0.65, 0.0),
    "Cream": ((0.98, 0.96, 0.90, 1), 0.4, 0.0),
    "Cherry": ((0.62, 0.02, 0.05, 1), 0.12, 0.0),
}
MAT = {name: i for i, name in enumerate(MATERIALS)}


# --- Shapes -------------------------------------------------------------------
# Flesh and cloth are metaball surfaces (so a chest, belly and shoulders blend into
# one jacket), polygonized, decimated and skinned by distance to their bones. Each
# piece is its own metaball family, so the arms and legs don't fuse to the torso.
# Small hard parts (buttons, eyes, hat, pie) are modeled directly in bmesh.


def stiff_k(stiffness, threshold=0.6):
    """Fraction of a metaball's radius where its surface sits (alone)."""
    return math.sqrt(1 - (threshold / stiffness) ** (1 / 3))


class Blob:
    def __init__(self, resolution):
        self.mb = bpy.data.metaballs.new("Blob")
        self.mb.resolution = resolution
        self.mb.render_resolution = resolution
        self.mb.threshold = 0.6

    def ell(self, center, semi, stiffness=2.5, rot=None, negative=False):
        """Ellipsoid with visible semi-axes `semi` (when alone)."""
        r = max(semi) / stiff_k(stiffness)
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
        e.rotation = (b - a).normalized().to_track_quat("X", "Z")
        e.stiffness, e.use_negative = stiffness, negative
        return e

    def mesh(self, ratio):
        """Polygonizes the blob, decimated to `ratio` of its faces."""
        obj = bpy.data.objects.new("Blob", self.mb)
        bpy.context.scene.collection.objects.link(obj)
        dg = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
        bpy.data.objects.remove(obj)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
        # Irons out the polygonizer's grid ripples, which show up in the shading.
        for _ in range(4):
            bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        bm.to_mesh(mesh)
        bm.free()
        if ratio < 1:
            obj = bpy.data.objects.new("Decimating", mesh)
            bpy.context.scene.collection.objects.link(obj)
            obj.modifiers.new("Decimate", "DECIMATE").ratio = ratio
            dg = bpy.context.evaluated_depsgraph_get()
            out = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
            mesh = out
        return mesh


def uv_ellipsoid(bm, center, semi, rot=Quaternion(), segments=(20, 12)):
    matrix = Matrix.Translation(center) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal((*semi, 1))
    return bmesh.ops.create_uvsphere(bm, u_segments=segments[0], v_segments=segments[1], radius=1.0, matrix=matrix)["verts"]


def tube(bm, points, radii, sides=10, caps=True):
    """A tube along `points` with a radius per point, closed with fans at both ends."""
    rings = []
    n = None
    for i, p in enumerate(points):
        p = Vector(p)
        t = (Vector(points[min(i + 1, len(points) - 1)]) - Vector(points[max(i - 1, 0)])).normalized()
        n = t.orthogonal().normalized() if n is None else (n - t * n.dot(t)).normalized()
        b = t.cross(n)
        rings.append([bm.verts.new(p + radii[i] * (math.cos(2 * math.pi * j / sides) * n + math.sin(2 * math.pi * j / sides) * b)) for j in range(sides)])
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(sides):
            bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    verts = [v for r in rings for v in r]
    if caps:
        for ring, tip, flip in ((rings[0], points[0], True), (rings[-1], points[-1], False)):
            center = bm.verts.new(Vector(tip))
            verts.append(center)
            for j in range(sides):
                a, b = ring[j], ring[(j + 1) % sides]
                bm.faces.new((b, a, center) if flip else (a, b, center))
    return verts


def ring_band(bm, center_at, radius_at, z0, z1, rows=4, sides=40):
    """A closed vertical band (no caps): `radius_at(angle, z)` and `center_at(z)`
    give its outline. Faces point outward."""
    grid = []
    for i in range(rows + 1):
        z = z0 + (z1 - z0) * i / rows
        c = center_at(z)
        grid.append([bm.verts.new(c + Vector((math.cos(a), math.sin(a), 0)) * radius_at(a, z) + Vector((0, 0, z - c.z)))
                     for a in (2 * math.pi * j / sides for j in range(sides))])
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(sides):
            bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    return [v for r in grid for v in r]


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (a + ab * t - p).length


def by_distance(*bones, sharpness=5):
    """Skin weights from distance to each bone's segment: smooth at the joints."""

    def weights(p):
        ws = sorted(((b, 1 / (seg_dist(p, *SEGMENTS[b]) + 0.012) ** sharpness) for b in bones), key=lambda bw: -bw[1])[:3]
        total = sum(w for _, w in ws)
        return {b: w / total for b, w in ws if w / total > 0.02}

    return weights


class Model:
    """Collects every part into one skinned bmesh."""

    def __init__(self):
        self.bm = bmesh.new()
        self.deform = self.bm.verts.layers.deform.verify()
        self.surfaces = {}  # piece name -> BVHTree, for placing details on it

    def weigh(self, verts, weights):
        """`weights` is a bone name or a function of position -> {bone: weight}."""
        for v in verts:
            ws = {weights: 1.0} if isinstance(weights, str) else weights(v.co)
            for bone, w in ws.items():
                v[self.deform][BONE_NAMES.index(bone)] = w

    def paint(self, verts, mat, smooth=True):
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = MAT[mat]
            f.smooth = smooth

    def part(self, verts, bone, mat, smooth=True):
        self.weigh(verts, bone)
        self.paint(verts, mat, smooth)
        return verts

    def blob(self, name, blob, ratio, mat, weights):
        mesh = blob.mesh(ratio)
        verts = [self.bm.verts.new(v.co) for v in mesh.vertices]
        for poly in mesh.polygons:
            try:
                self.bm.faces.new([verts[i] for i in poly.vertices])
            except ValueError:
                pass
        self.surfaces[name] = BVHTree.FromPolygons([v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons])
        bpy.data.meshes.remove(mesh)
        self.weigh(verts, weights)
        self.paint(verts, mat)
        return verts

    def hit(self, piece, origin, direction):
        """First point on `piece` along a ray, and its normal."""
        loc, normal, _, _ = self.surfaces[piece].ray_cast(Vector(origin), Vector(direction).normalized())
        return loc, normal

    def fit(self, pieces, center, angle):
        """How far out from `center` the outermost of `pieces` is, horizontally at `angle`."""
        d = Vector((math.cos(angle), math.sin(angle), 0))
        hits = [self.hit(p, center + d * 0.5, -d)[0] for p in pieces]
        return max([(h - center).xy.length for h in hits if h is not None] + [0.0])

    def weights_near(self, verts):
        """A function giving each point the weights of the nearest vertex in `verts`,
        so a detail sewn onto a surface moves with it."""
        tree = KDTree(len(verts))
        for i, v in enumerate(verts):
            tree.insert(v.co, i)
        tree.balance()

        def weights(p):
            _, i, _ = tree.find(p)
            d = verts[i][self.deform]
            return {BONE_NAMES[g]: w for g, w in d.items() if w > 0}

        return weights


# --- The chef -----------------------------------------------------------------


def head_blob():
    """Round, ruddy face: full cheeks and jowls, a big fleshy nose with wings and
    nostrils, smile lines, a soft double chin and properly folded ears."""
    b = Blob(resolution=0.0024)
    b.ell((-0.005, 0, 1.085), (0.093, 0.079, 0.09))  # cranium
    b.ell((0.025, 0, 1.03), (0.075, 0.07, 0.072))  # face and jaw
    b.ell((0.05, 0, 0.982), (0.045, 0.05, 0.026), stiffness=3)  # chin
    b.ell((0.02, 0, 0.972), (0.05, 0.06, 0.03), stiffness=3)  # double chin
    b.cap((-0.012, 0, 0.84), (0.0, 0, 0.99), 0.054)  # thick neck, down into the collar
    b.ell((0.04, 0, 0.93), (0.012, 0.012, 0.016), stiffness=4)  # Adam's apple
    for s in (1, -1):
        b.ell((0.058, s * 0.045, 1.033), (0.026, 0.027, 0.024), stiffness=3)  # cheeks
        b.ell((0.06, s * 0.056, 1.058), (0.02, 0.016, 0.011), stiffness=4)  # cheekbones
        b.ell((0.045, s * 0.052, 0.997), (0.022, 0.02, 0.018), stiffness=4)  # jowls
        b.cap((-0.02, s * 0.058, 1.02), (0.06, s * 0.03, 0.978), 0.016, stiffness=3)  # jawline
        b.cap((0.085, s * 0.012, 1.097), (0.08, s * 0.052, 1.1), 0.011, stiffness=3)  # brow ridge
        b.ball((0.078, s * 0.033, 1.072), 0.014, stiffness=4, negative=True)  # eye socket
        b.ell((0.03, s * 0.074, 1.093), (0.018, 0.01, 0.018), stiffness=5, negative=True)  # temples
        # Smile lines, from the nose's wings down past the mouth.
        b.cap((0.1, s * 0.024, 1.04), (0.088, s * 0.036, 0.998), 0.0028, stiffness=6, negative=True)
        b.ball((0.085, s * 0.023, 1.006), 0.003, stiffness=6, negative=True)  # mouth corners
        # Ears: shell, rolled rim (helix), lobe, tragus and the bowl (concha).
        tilt = Quaternion((1, 0, 0), math.radians(-10 * s))
        b.ell((-0.012, s * 0.08, 1.06), (0.018, 0.011, 0.03), stiffness=4, rot=tilt)
        rim = [Vector((-0.012 + 0.018 * math.cos(a), s * 0.088, 1.062 + 0.029 * math.sin(a))) for a in (math.radians(d) for d in range(70, 271, 25))]
        for p0, p1 in zip(rim, rim[1:]):
            b.cap(p0, p1, 0.0042, stiffness=4)
        b.ball((-0.006, s * 0.086, 1.034), 0.0075, stiffness=4)  # lobe
        b.ball((0.006, s * 0.084, 1.057), 0.0042, stiffness=5)  # tragus
        b.ell((-0.008, s * 0.09, 1.063), (0.009, 0.007, 0.017), stiffness=5, negative=True)  # bowl
        b.cap((-0.018, s * 0.092, 1.08), (-0.022, s * 0.092, 1.055), 0.003, stiffness=6, negative=True)  # scapha
    # A big round nose: bridge, bulb, wings, and nostrils hollowed underneath.
    b.cap((0.088, 0, 1.09), (0.104, 0, 1.052), 0.0105, stiffness=3)
    b.ball((0.106, 0, 1.045), 0.0135, stiffness=3)
    for s in (1, -1):
        b.ball((0.095, s * 0.0155, 1.036), 0.008, stiffness=3.5)  # wings
        b.ball((0.101, s * 0.0088, 1.0295), 0.0042, stiffness=5, negative=True)  # nostrils
    # Mouth: a crease between the lips, a cupid's-bow upper lip and a full lower lip.
    b.cap((0.092, -0.02, 1.006), (0.092, 0.02, 1.006), 0.004, stiffness=6, negative=True)
    b.ell((0.093, 0, 1.0125), (0.007, 0.019, 0.0055), stiffness=4)
    b.ell((0.089, 0, 0.998), (0.012, 0.021, 0.008), stiffness=4)
    b.cap((0.1, 0, 1.026), (0.096, 0, 1.016), 0.0018, stiffness=6, negative=True)  # philtrum
    return b


def hair_blob():
    """Short hair under the toque: back and sides, with sideburns."""
    b = Blob(resolution=0.004)
    b.ell((-0.02, 0, 1.095), (0.093, 0.085, 0.082))
    for s in (1, -1):
        b.ell((0.03, s * 0.077, 1.07), (0.014, 0.008, 0.03), stiffness=4)  # sideburns
        b.ell((-0.01, s * 0.09, 1.06), (0.028, 0.02, 0.036), stiffness=4, negative=True)  # room for the ears
    b.ell((0.06, 0, 1.06), (0.05, 0.08, 0.06), stiffness=4, negative=True)  # clear of the face
    return b


def jacket_blob():
    """The double-breasted jacket's body: broad chest, a proud belly, square shoulders."""
    b = Blob(resolution=0.0042)
    b.ell((0.005, 0, 0.775), (0.105, 0.15, 0.11))  # chest
    b.ell((0.04, 0, 0.625), (0.13, 0.135, 0.13))  # belly
    b.ell((0.0, 0, 0.52), (0.11, 0.14, 0.08))  # hips
    for s in (1, -1):
        b.ell((-0.005, s * 0.095, 0.845), (0.06, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.155, 0.83), (0.055, 0.045, 0.045))  # shoulder seam
        b.ell((-0.06, s * 0.06, 0.78), (0.04, 0.06, 0.07))  # shoulder blades
    b.ell((0.0, 0, 0.45), (0.12, 0.142, 0.02), stiffness=4)  # hem
    # Cloth pulled taut over the belly: drag folds from the buttons out to the sides,
    # a fold under the chest, and the bunching at the small of the back.
    for s in (1, -1):
        for z0, z1 in ((0.705, 0.665), (0.655, 0.62), (0.6, 0.575)):
            b.cap((0.135, s * 0.07, z0), (0.07, s * 0.135, z1), 0.0045, stiffness=6, negative=True)
        b.cap((0.1, s * 0.03, 0.722), (0.06, s * 0.125, 0.73), 0.004, stiffness=6, negative=True)
        b.cap((-0.115, s * 0.02, 0.56), (-0.09, s * 0.11, 0.545), 0.004, stiffness=6, negative=True)
    return b


def sleeve_blob(s):
    """A sleeve, creased in the crook of the elbow and behind the arm."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0036)
    b.ell((0.0, y - s * 0.005, 0.825), (0.055, 0.055, 0.06))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.046)
    b.ell((0.012, y, 0.73), (0.035, 0.038, 0.06), stiffness=3)  # biceps
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.05), 0.043)
    b.ell((-0.008, y, 0.6), (0.036, 0.038, 0.05), stiffness=3)  # forearm
    for i, z in enumerate((0.672, 0.648, 0.624)):  # elbow creases, fanning out
        t = (i - 1) * 0.012
        b.cap((0.047, y - s * 0.034, z + 0.012 + t), (0.047, y + s * 0.03, z - 0.008 - t), 0.0042, stiffness=6, negative=True)
    b.cap((-0.05, y + s * 0.02, 0.72), (-0.046, y - s * 0.02, 0.705), 0.0035, stiffness=6, negative=True)  # back of the arm
    return b


def hand_blob(s):
    """A loose fist, thumb forward, palm facing the body (a vertical fist when punching)."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0025)
    b.cap((0, y, WRIST[1] + 0.03), (0, y, WRIST[1] - 0.02), 0.021)  # wrist
    b.ell((0.0, y - s * 0.002, WRIST[1] - 0.04), (0.036, 0.019, 0.04), stiffness=3)  # palm
    for i, x in enumerate((0.026, 0.009, -0.008, -0.024)):
        knuckle = Vector((x, y, WRIST[1] - 0.075 + 0.003 * abs(i - 1.2)))
        r = 0.0095 if i < 3 else 0.0082
        # Curled: down to the knuckle, across toward the palm, then back up it.
        b.cap(knuckle + Vector((0, 0, 0.02)), knuckle, r, stiffness=4)
        b.cap(knuckle, knuckle + Vector((0, -s * 0.026, -0.002)), r, stiffness=4)
        b.cap(knuckle + Vector((0, -s * 0.027, -0.002)), knuckle + Vector((0, -s * 0.03, 0.022)), r * 0.95, stiffness=4)
    # Thumb, wrapped over the curled fingers.
    b.cap((0.03, y - s * 0.006, WRIST[1] - 0.02), (0.038, y - s * 0.016, WRIST[1] - 0.048), 0.011, stiffness=4)
    b.cap((0.038, y - s * 0.016, WRIST[1] - 0.048), (0.018, y - s * 0.032, WRIST[1] - 0.058), 0.0095, stiffness=4)
    return b


def chef_hand_blob(s):
    """The chef's own fist (`hand_blob`, shared with the samurai, is the simpler one):
    a meaty palm, three-segment fingers with knuckles standing out across the back of
    the hand and at the finger joints, the thumb wrapped over them, tendons at the
    wrist."""
    y = s * SHOULDER[0]
    w = WRIST[1]
    b = Blob(resolution=0.0016)
    b.cap((0, y, w + 0.03), (0, y, w - 0.02), 0.0205)  # wrist
    b.ell((0.0, y - s * 0.002, w - 0.04), (0.036, 0.019, 0.04), stiffness=3)  # palm
    b.ell((0.024, y - s * 0.012, w - 0.03), (0.014, 0.012, 0.022), stiffness=4)  # ball of the thumb
    b.ell((-0.026, y - s * 0.01, w - 0.045), (0.01, 0.011, 0.028), stiffness=4)  # heel of the hand
    for dx in (0.008, -0.008):  # tendons over the back of the wrist
        b.cap((dx, y + s * 0.016, w + 0.01), (dx * 1.6, y + s * 0.016, w - 0.045), 0.0032, stiffness=6)
    for i, x in enumerate((0.026, 0.009, -0.008, -0.024)):
        joint = Vector((x, y, w - 0.075 + 0.003 * abs(i - 1.2)))
        r = 0.0092 if i < 3 else 0.008
        mcp = joint + Vector((0, 0, 0.021))
        pip = joint
        dip = joint + Vector((0, -s * 0.025, -0.002))
        tip = joint + Vector((0, -s * 0.029, 0.02))
        b.cap(mcp, pip, r, stiffness=4)  # proximal
        b.cap(pip, dip, r * 0.93, stiffness=4)  # middle
        b.cap(dip + Vector((0, -s * 0.002, 0.002)), tip, r * 0.85, stiffness=4)  # distal, tucked in
        b.ball(mcp + Vector((0, s * 0.006, 0.003)), r * 0.85, stiffness=5)  # knuckle
        b.ball(pip + Vector((0, s * 0.002, -0.003)), r * 0.8, stiffness=5)  # finger joint
        if i < 3:  # creases between the fingers
            b.cap(pip + Vector((-0.0085, s * 0.004, 0.0)), pip + Vector((-0.0085, -s * 0.024, -0.002)), 0.0012, stiffness=7, negative=True)
    # Thumb, wrapped over the curled fingers, with a knuckle.
    t0, t1, t2 = Vector((0.03, y - s * 0.006, w - 0.02)), Vector((0.038, y - s * 0.016, w - 0.048)), Vector((0.018, y - s * 0.033, w - 0.058))
    b.cap(t0, t1, 0.0112, stiffness=4)
    b.cap(t1, t2, 0.0098, stiffness=4)
    b.ball(t1 + Vector((0.004, 0, 0)), 0.0085, stiffness=5)
    return b


def thumbnail(m, side, s):
    """A nail on the wrapped thumb, found by ray casting onto the fist."""
    y = s * SHOULDER[0]
    loc, normal = m.hit(f"hand.{side}", (0.1, y - s * 0.03, WRIST[1] - 0.055), (-1, 0, 0))
    if loc is None:
        return
    along = Vector((-0.9, -s * 0.5, -0.3)).normalized()  # down the thumb, toward its tip
    along = (along - normal * along.dot(normal)).normalized()
    rot = Matrix((along, normal.cross(along), normal)).transposed().to_quaternion()
    verts = uv_ellipsoid(m.bm, loc + normal * 0.0006, (0.0062, 0.0055, 0.0012), rot, segments=(12, 6))
    m.part(verts, f"forearm.{side}", "Nail")


def leg_blob(s):
    """One leg of the baggy chef's trousers, with half of the seat."""
    y = s * HIP[0]
    b = Blob(resolution=0.0042)
    b.ell((-0.025, s * 0.05, 0.48), (0.09, 0.07, 0.07))  # seat
    b.cap((0, y, HIP[1] - 0.05), (0, y, KNEE[1]), 0.066)
    b.ell((0.01, y + s * 0.004, 0.43), (0.07, 0.066, 0.1), stiffness=3)  # thigh
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.01), 0.054)
    b.ell((-0.012, y, 0.21), (0.052, 0.054, 0.08), stiffness=3)  # calf
    b.ell((0.0, y, 0.085), (0.06, 0.058, 0.02), stiffness=4)  # hem, breaking over the shoe
    # The break: the hem stacks in soft rolls over the shoe.
    for z, d in ((0.112, 0.004), (0.135, -0.003)):
        b.ell((0.004 + d, y, z), (0.056, 0.056, 0.007), stiffness=4)
    # Folds behind the knee and across its front, and a crease where the thigh meets the hip.
    for z in (0.315, 0.29):
        b.cap((-0.058, y - 0.03, z), (-0.058, y + 0.03, z + 0.006), 0.004, stiffness=6, negative=True)
    b.cap((0.062, y - 0.03, 0.345), (0.062, y + 0.03, 0.335), 0.0035, stiffness=6, negative=True)
    b.cap((0.075, y - s * 0.02, 0.5), (0.06, y + s * 0.05, 0.47), 0.004, stiffness=6, negative=True)
    return b


def shoe_blob(s):
    y = s * HIP[0]
    b = Blob(resolution=0.003)
    b.ell((0.04, y, 0.04), (0.09, 0.044, 0.04), stiffness=3)
    b.ell((0.115, y, 0.03), (0.05, 0.043, 0.03), stiffness=3)  # toe box
    b.ell((-0.025, y, 0.045), (0.042, 0.04, 0.045), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.1), 0.042)  # ankle, inside the trouser hem
    b.ell((0.05, y, -0.1), (0.4, 0.3, 0.1) , stiffness=4, negative=True)  # flat sole
    b.ell((0.05, y, -0.084), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # (the sole is its own part)
    b.cap((0.1, y - 0.04, 0.052), (0.1, y + 0.04, 0.052), 0.0025, stiffness=7, negative=True)  # flex crease
    b.cap((0.135, y - 0.04, 0.035), (0.135, y + 0.04, 0.04), 0.002, stiffness=7, negative=True)  # toe cap seam
    return b


def pie_parts(bm, matrix):
    """A cream pie in a tin: its cream faces local +Z, the tin's base at z = 0 and 0.26 m
    across. Returns {material: verts}."""
    out = {}

    def add(mat, verts):
        for v in verts:
            v.co = matrix @ v.co
        out.setdefault(mat, []).extend(verts)

    tin = bmesh.ops.create_cone(bm, cap_ends=True, segments=40, radius1=0.105, radius2=0.13, depth=0.03, matrix=Matrix.Translation((0, 0, 0.015)))["verts"]
    add("Tin", tin)
    # Crimped crust around the rim.
    rim = []
    sides, ring = 8, 64
    for i in range(ring):
        a = 2 * math.pi * i / ring
        crimp = 0.004 * math.cos(16 * a)
        rim.append([bm.verts.new(Vector((math.cos(a), math.sin(a), 0)) * (0.124 + (0.012 + crimp) * math.cos(2 * math.pi * j / sides))
                                 + Vector((0, 0, 0.034 + (0.011 + crimp) * math.sin(2 * math.pi * j / sides)))) for j in range(sides)])
    for i in range(ring):
        for j in range(sides):
            a, b = rim[i][j], rim[i][(j + 1) % sides]
            bm.faces.new((a, b, rim[(i + 1) % ring][(j + 1) % sides], rim[(i + 1) % ring][j]))
    add("Crust", [v for r in rim for v in r])
    add("Cream", uv_ellipsoid(bm, (0, 0, 0.03), (0.118, 0.118, 0.03), segments=(32, 12)))

    def dollop(center, size):
        """A piped swirl of whipped cream, coming to a point."""
        verts = uv_ellipsoid(bm, (0, 0, 0), (1, 1, 1), segments=(20, 10))
        for v in verts:
            x, y, z = v.co
            up = max(z, 0)
            twist = 1 + 0.14 * math.cos(6 * math.atan2(y, x) + 7 * z)
            shrink = (1 - 0.85 * up**1.4) * twist
            v.co = Vector((x * shrink * size, y * shrink * size, (z if z > 0 else 0.3 * z) * size * 1.4)) + Vector(center)
        add("Cream", verts)

    for i in range(10):
        a = 2 * math.pi * i / 10
        dollop((0.082 * math.cos(a), 0.082 * math.sin(a), 0.052), 0.021)
    dollop((0, 0, 0.06), 0.03)
    add("Cherry", uv_ellipsoid(bm, (0, 0, 0.108), (0.018, 0.018, 0.017), segments=(16, 10)))
    add("Crust", tube(bm, [(0, 0, 0.122), (0.006, 0.002, 0.14), (0.016, 0.004, 0.152)], [0.0022, 0.002, 0.0016], sides=6))
    return out


def chef_mesh():
    m = Model()
    m.blob("head", head_blob(), 0.55, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.4, "Hair", "head")
    jacket = m.blob("jacket", jacket_blob(), 0.4, "Jacket", by_distance("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        m.blob(f"sleeve.{side}", sleeve_blob(s), 0.4, "Jacket", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", chef_hand_blob(s), 0.45, "Skin", f"forearm.{side}")
        thumbnail(m, side, s)
        m.blob(f"leg.{side}", leg_blob(s), 0.4, "Pants", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"shoe.{side}", shoe_blob(s), 0.45, "Shoe", f"foot.{side}")
        shoe_details(m, side, s)
        # Rolled-back cuffs.
        y = s * SHOULDER[0]
        for z, r in ((WRIST[1] + 0.045, 0.036), (WRIST[1] + 0.068, 0.036)):
            loop = [Vector((0.003 + r * math.cos(a), y + r * math.sin(a), z)) for a in (2 * math.pi * j / 24 for j in range(25))]
            m.part(tube(m.bm, loop, [0.012] * len(loop), sides=10), f"forearm.{side}", "Jacket")
    on_jacket = m.weights_near(jacket)
    face(m)
    toque(m)
    collar_and_neckerchief(m)
    buttons(m, on_jacket)
    seams(m, on_jacket)
    pen_pocket(m)
    apron(m)
    towel(m)
    pie = pie_parts(m.bm, Matrix.Translation(Vector(PIE_PIVOT) + Vector((0, 0, -0.035))) @ Matrix.Rotation(math.pi, 4, "Y"))
    for mat, verts in pie.items():
        m.part(verts, "pie", mat)

    mesh = bpy.data.meshes.new("ChefMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.normal_update()
    m.bm.to_mesh(mesh)
    for mat in materials():
        mesh.materials.append(mat)
    surface_data(m.bm, m.deform, mesh)
    m.bm.free()
    return mesh


def sphere_patch(bm, center, frame, radius, theta, phi, rows, cols):
    """A grid on a sphere around `center`: `frame` = (forward, lateral, up) unit vectors,
    `theta` = (lo, hi) azimuth toward `lateral` and `phi(theta)` = (lo, hi) elevation,
    in radians. Faces point outward. Returns the grid of verts [row][col]."""
    fwd, lat, up = frame
    grid = []
    for i in range(rows + 1):
        row = []
        for j in range(cols + 1):
            t = theta[0] + (theta[1] - theta[0]) * j / cols
            lo, hi = phi(t)
            e = lo + (hi - lo) * i / rows
            d = fwd * (math.cos(e) * math.cos(t)) + lat * (math.cos(e) * math.sin(t)) + up * math.sin(e)
            row.append(bm.verts.new(center + d * radius))
        grid.append(row)
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(cols):
            bm.faces.new((r0[j], r0[j + 1], r1[j + 1], r1[j]))
    return grid


def eye_and_lids(m, eye, s):
    """An eyeball with an iris and pupil set into it, wrapped in upper and lower lids
    with rounded margins, a lid crease and lashes."""
    r = 0.012
    fwd, lat, up = Vector((1, 0, 0)), Vector((0, s, 0)), Vector((0, 0, 1))  # lat: toward the outer corner
    m.part(uv_ellipsoid(m.bm, eye, (r,) * 3, segments=(24, 16)), "head", "Eye")
    gaze = Quaternion((0, 0, 1), math.radians(-3 * s))  # a touch cross-eyed: focused ahead
    look = gaze @ fwd
    for mat, ang, lift in (("Iris", math.asin(0.0058 / r), 0.00025), ("Pupil", math.asin(0.0021 / r), 0.0004)):
        # A spherical cap facing `look`.
        side = look.cross(up).normalized()
        top = side.cross(look).normalized()
        cap = sphere_patch(m.bm, eye, (top, side, look), r + lift, (0, 2 * math.pi), lambda t, a=ang: (math.pi / 2 - a, math.pi / 2 - 1e-3), 3, 20)
        m.part([v for row in cap for v in row], "head", mat)
    # Lids: an almond opening, the outer corner a little higher, heavy upper lids.
    corner = math.radians(52)
    tilt = math.radians(3)

    def upper(t):
        k = max(0.0, 1 - (t / corner) ** 2) ** 0.8
        return math.radians(17) * k + tilt * t / corner if abs(t) < corner else tilt * math.copysign(1, t)

    def lower(t):
        k = max(0.0, 1 - (t / corner) ** 2) ** 0.8
        return -math.radians(25) * k + tilt * t / corner if abs(t) < corner else tilt * math.copysign(1, t)

    R = r + 0.0011
    span = (-math.radians(85), math.radians(85))
    frame = (fwd, lat, up)
    top = sphere_patch(m.bm, eye, frame, R, span, lambda t: (upper(t), math.radians(80)), 6, 24)
    bottom = sphere_patch(m.bm, eye, frame, R, span, lambda t: (-math.radians(80), lower(t)), 5, 24)
    lids = [v for g in (top, bottom) for row in g for v in row]
    m.part(lids, "head", "Skin")

    def along(curve, radius, t0, t1, n=14):
        out = []
        for i in range(n + 1):
            t = t0 + (t1 - t0) * i / n
            e = curve(t)
            out.append(eye + (fwd * (math.cos(e) * math.cos(t)) + lat * (math.cos(e) * math.sin(t)) + up * math.sin(e)) * radius)
        return out

    lim = corner * 0.98
    # Rounded lid margins and the fold of skin above the upper lid.
    m.part(tube(m.bm, along(upper, R, -lim, lim), [0.0011] * 15, sides=6), "head", "Skin")
    m.part(tube(m.bm, along(lower, R, -lim, lim), [0.0009] * 15, sides=6), "head", "Skin")
    crease = along(lambda t: upper(t) + math.radians(16), R + 0.0004, -lim * 0.9, lim * 1.05, 12)
    m.part(tube(m.bm, crease, [0.0008, 0.0014, 0.0018, 0.002, 0.0021, 0.0021, 0.0021, 0.0021, 0.002, 0.0019, 0.0017, 0.0013, 0.0008], sides=6), "head", "Skin")
    # Lashes: a dark fringe along the upper margin, flaring out at the outer corner.
    lash = along(lambda t: upper(t) + math.radians(3), R + 0.0012, -lim * 0.75, lim * 1.02, 12)
    m.part(tube(m.bm, lash, [0.0003] + [0.0006] * 11 + [0.0003], sides=5), "head", "Hair")
    m.part(tube(m.bm, along(lambda t: lower(t) - math.radians(3), R + 0.0007, -lim * 0.5, lim * 0.95, 8), [0.0002] + [0.0003] * 7 + [0.0002], sides=4), "head", "Hair")


def strands(m, rng, path, count, radius, spread, start=(0.0, 0.25), stop=(0.75, 1.0), lift=0.0):
    """`count` hairs laid along `path` (a polyline): each a thin tapered tube from a
    random start to a random stop fraction, offset sideways by up to `spread`."""
    path = [Vector(p) for p in path]
    lengths = [0.0]
    for a, b in zip(path, path[1:]):
        lengths.append(lengths[-1] + (b - a).length)

    def at(u):
        d = u * lengths[-1]
        i = max(k for k in range(len(path) - 1) if lengths[k] <= d) if d > 0 else 0
        i = min(i, len(path) - 2)
        f = (d - lengths[i]) / max(lengths[i + 1] - lengths[i], 1e-9)
        return path[i].lerp(path[i + 1], f), (path[i + 1] - path[i]).normalized()

    for _ in range(count):
        u0 = rng.uniform(*start)
        u1 = rng.uniform(*stop)
        off = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        pts, radii = [], []
        for i in range(6):
            u = u0 + (u1 - u0) * i / 5
            p, d = at(u)
            o = off - d * off.dot(d)
            pts.append(p + o * spread * (1 - 0.5 * u) + Vector((0, 0, lift)))
            radii.append(radius * (1 - 0.75 * i / 5))
        m.part(tube(m.bm, pts, radii, sides=4), "head", "Hair")


def face(m):
    rng = random.Random(7)

    def on_skin(y, z, lift):
        """The point on the face at height z and side offset y, lifted off the skin."""
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.033, 1.072, 0)
        eye = socket - Vector((0.012 - 0.0045, 0, 0))  # bulging 4.5 mm out of the socket
        EYES.append(eye)
        eye_and_lids(m, eye, s)
        # Bushy brows: a soft dark base with individual hairs combed outward over it.
        brow = [on_skin(s * y, z, 0.0012) for y, z in ((0.01, 1.096), (0.022, 1.101), (0.036, 1.103), (0.05, 1.099), (0.058, 1.094))]
        m.part(tube(m.bm, brow, [0.0016, 0.0024, 0.0024, 0.0018, 0.001], sides=8), "head", "Hair")
        strands(m, rng, brow, 80, 0.0009, 0.0042, start=(0.0, 0.7), stop=(0.3, 1.0), lift=0.0012)
        # Handlebar mustache: from under the nose out over the cheeks, curling up.
        root = [on_skin(s * y, z, lift) for y, z, lift in ((0.002, 1.022, 0.002), (0.02, 1.017, 0.003), (0.04, 1.015, 0.004))]
        tip = root[-1]
        curl = root + [tip + Vector((-0.01, s * 0.016, 0.004)), tip + Vector((-0.016, s * 0.023, 0.016)), tip + Vector((-0.014, s * 0.017, 0.026)),
                       tip + Vector((-0.01, s * 0.011, 0.024))]
        m.part(tube(m.bm, curl, [0.0075, 0.008, 0.006, 0.004, 0.003, 0.0023, 0.0016], sides=12), "head", "Hair")
        strands(m, rng, curl, 70, 0.0016, 0.0065, start=(0.0, 0.15), stop=(0.45, 1.0))
    lip = on_skin(0, 1.0095, -0.004)
    m.part(uv_ellipsoid(m.bm, lip, (0.009, 0.019, 0.005), segments=(18, 10)), "head", "Lip")


def toque(m):
    """The tall pleated chef's hat, its band fitted to the head."""
    center = lambda z: Vector((-0.012, 0, z))  # noqa: E731
    fit = [m.fit(("head", "hair"), center(1.125), 2 * math.pi * j / 48) + 0.006 for j in range(48)]

    def band_r(a, z):
        return fit[round(a / (2 * math.pi) * 48) % 48]

    band = ring_band(m.bm, center, band_r, 1.105, 1.155, rows=3, sides=48)
    m.part(band, "head", "Jacket")
    # Pleated crown: flares out above the band.
    def crown_r(a, z):
        t = (z - 1.155) / 0.15
        return band_r(a, z) * (1 + 0.14 * t) + 0.007 * math.cos(16 * a) * min(1, t * 4)

    m.part(ring_band(m.bm, center, crown_r, 1.15, 1.305, rows=8, sides=48), "head", "Jacket")
    # Puffed top, gathered into the pleats.
    top = uv_ellipsoid(m.bm, (0, 0, 0), (1, 1, 1), segments=(48, 16))
    for v in top:
        x, y, z = v.co
        a = math.atan2(y, x)
        r = crown_r(a, 1.305) * 1.1 + 0.006 * math.cos(16 * a)
        v.co = center(1.31) + Vector((x * r, y * r, z * (0.065 if z > 0 else 0.03)))
    m.part(top, "head", "Jacket")


def collar_and_neckerchief(m):
    """Mandarin collar, with the neckerchief knotted at the front above it."""
    center = lambda z: Vector((0.0, 0, z))  # noqa: E731
    collar = ring_band(m.bm, center, lambda a, z: 0.068 - 0.2 * (z - 0.86), 0.855, 0.915, rows=3, sides=40)
    solid = bmesh.ops.solidify(m.bm, geom=list({f for v in collar for f in v.link_faces}), thickness=0.004)
    collar += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
    m.part(collar, "spine", "Jacket")
    # The folded neckerchief: a soft band hugging the neck above the collar.
    band = ring_band(m.bm, center, lambda a, z: 0.06 + 0.012 * math.sin(math.pi * (z - 0.905) / 0.03), 0.905, 0.935, rows=4, sides=40)
    m.part(band, "spine", "Body")
    m.part(uv_ellipsoid(m.bm, (0.062, -0.006, 0.91), (0.017, 0.022, 0.019)), "spine", "Body")
    for s in (1, -1):
        tail = [(0.066, -0.006 + s * 0.008, 0.9), (0.078, s * 0.02, 0.875), (0.09, s * 0.03, 0.845)]
        verts = tube(m.bm, tail, [0.013, 0.015, 0.016], sides=10)
        for v in verts:  # flatten the tails into cloth against the chest
            v.co.x = 0.07 + (v.co.x - 0.07) * 0.45
        m.part(verts, "spine", "Body")


def buttons(m, on_jacket):
    """Two rows of black stud buttons, and the edge of the overlapping front panel."""
    for y in (0.052, -0.052):
        for z in (0.815, 0.755, 0.695, 0.635):
            loc, normal = m.hit("jacket", (0.5, y, z), (-1, 0, 0))
            rot = normal.to_track_quat("Z", "Y")
            verts = uv_ellipsoid(m.bm, loc + normal * 0.002, (0.009, 0.009, 0.0035), rot, segments=(14, 6))
            m.weigh(verts, on_jacket)
            m.paint(verts, "Button")
    edge = []
    for i in range(14):
        z = 0.86 - 0.3 * i / 13
        loc, normal = m.hit("jacket", (0.5, -0.088 - 0.01 * (i / 13), z), (-1, 0, 0))
        edge.append(loc + normal * 0.0015)
    verts = tube(m.bm, edge, [0.0035] * len(edge), sides=6)
    m.weigh(verts, on_jacket)
    m.paint(verts, "Jacket")


def surface_line(m, piece, points, direction, lift, radius, sides=6):
    """A tube laid on `piece` (a seam, a hem): each point is cast along `direction`
    onto the surface and lifted `lift` off it. Points that miss are dropped."""
    out = []
    for p in points:
        loc, normal = m.hit(piece, Vector(p) - Vector(direction) * 0.5, direction)
        if loc is not None:
            out.append(loc + normal * lift)
    return tube(m.bm, out, [radius] * len(out), sides=sides) if len(out) > 1 else []


def seams(m, on_jacket):
    """Stitched seams on the jacket: down each side, across the back yoke, and the
    princess seams curving over the chest."""
    for s in (1, -1):
        side = [(0.0 - 0.01 * i / 12, s * 0.0, 0.80 - 0.33 * i / 12) for i in range(13)]
        verts = surface_line(m, "jacket", side, (0, -s, 0), 0.0008, 0.0016)
        m.part(verts, on_jacket, "Jacket")
        princess = [(0.0, s * (0.115 - 0.03 * math.sin(math.pi * i / 12)), 0.83 - 0.36 * i / 12) for i in range(13)]
        verts = surface_line(m, "jacket", princess, (-1, 0, 0), 0.0008, 0.0014)
        m.part(verts, on_jacket, "Jacket")
    yoke = [(0.0, -0.13 + 0.26 * i / 16, 0.79 + 0.01 * math.cos(math.pi * (i / 8 - 1))) for i in range(17)]
    m.part(surface_line(m, "jacket", yoke, (1, 0, 0), 0.0008, 0.0016), on_jacket, "Jacket")


def pen_pocket(m):
    """The pen pocket stitched on the near sleeve, with a pen and a probe thermometer."""
    side, s = "R", -1
    y = s * SHOULDER[0]
    grid = []
    for i in range(7):
        z = 0.785 - 0.07 * i / 6
        row = []
        for j in range(6):
            a = math.radians(-35 + 70 * j / 5)  # around the arm, centered on its outside
            d = Vector((math.sin(a), s * math.cos(a), 0))
            loc, normal = m.hit(f"sleeve.{side}", Vector((0, y, z)) + d * 0.2, -d)
            row.append(m.bm.verts.new(loc + normal * (0.0025 + 0.0015 * math.sin(math.pi * j / 5))))
        grid.append(row)
    faces = [m.bm.faces.new((r0[j], r1[j], r1[j + 1], r0[j + 1])) for r0, r1 in zip(grid, grid[1:]) for j in range(5)]
    verts = [v for r in grid for v in r]
    solid = bmesh.ops.solidify(m.bm, geom=faces, thickness=0.002)
    verts += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]
    m.part(verts, "upper_arm.R", "Jacket")
    top = grid[0]
    m.part(tube(m.bm, [v.co for v in top], [0.0016] * len(top), sides=6), "upper_arm.R", "Jacket")  # hem
    for j, mat, r, h in ((1, "Button", 0.0042, 0.03), (3, "Tin", 0.0025, 0.045)):
        base = top[j].co.copy() + Vector((0, 0, -0.025))
        out = (top[j].co - Vector((0, y, top[j].co.z))).normalized() * 0.002
        pen = tube(m.bm, [base - out, base - out + Vector((0, 0, h))], [r, r * 0.9], sides=10)
        m.part(pen, "upper_arm.R", mat)
        if mat == "Button":  # the pen's clip
            m.part(tube(m.bm, [base + Vector((0, 0, h - 0.002)), base + out * 2.5 + Vector((0, 0, h - 0.004)), base + out * 2.5 + Vector((0, 0, h - 0.02))],
                        [0.0012] * 3, sides=4), "upper_arm.R", "Tin")
        else:  # the thermometer's dial
            dial = uv_ellipsoid(m.bm, base - out + Vector((0, 0, h + 0.005)), (0.009, 0.009, 0.004), Quaternion((1, 0, 0), math.radians(90)), segments=(14, 6))
            m.part(dial, "upper_arm.R", "Tin")


def shoe_details(m, side, s):
    """A stitched leather sole and laces over the instep."""
    y = s * HIP[0]
    center = Vector((0.045, y, 0.0))
    outline = []
    for j in range(48):
        a = 2 * math.pi * j / 48
        d = Vector((math.cos(a), math.sin(a), 0))
        loc, _ = m.hit(f"shoe.{side}", center + Vector((0, 0, 0.022)) + d * 0.4, -d)
        r = (loc - center - Vector((0, 0, 0.022))).xy.length if loc is not None else 0.04
        outline.append(r + 0.003)

    def r_at(a, z):
        return outline[round(a / (2 * math.pi) * 48) % 48]

    band = ring_band(m.bm, lambda z: center + Vector((0, 0, z)), r_at, 0.0, 0.019, rows=2, sides=48)
    bottom = band[:48]
    mid = m.bm.verts.new(center)
    for j in range(48):
        m.bm.faces.new((bottom[(j + 1) % 48], bottom[j], mid))
    m.part(band + [mid], f"foot.{side}", "Sole")
    # Welt stitching around the top of the sole.
    welt = [center + Vector((math.cos(a), math.sin(a), 0)) * (outline[j % 48] + 0.0005) + Vector((0, 0, 0.0185))
            for j, a in ((j, 2 * math.pi * j / 48) for j in range(49))]
    m.part(tube(m.bm, welt, [0.0012] * len(welt), sides=4), f"foot.{side}", "Sole")
    # Laces: crossing over the instep, cast onto the leather.
    for k in range(4):
        x = 0.03 + 0.017 * k
        for dy0, dy1 in ((-0.018, 0.018), (0.018, -0.018)):
            pts = [(x + 0.008 * t, y + dy0 + (dy1 - dy0) * t, 0.2) for t in (0, 0.5, 1)]
            m.part(surface_line(m, f"shoe.{side}", pts, (0, 0, -1), 0.0012, 0.0013, sides=4), f"foot.{side}", "Lace")
    bow = surface_line(m, f"shoe.{side}", [(0.03, y - 0.012, 0.2), (0.028, y, 0.2), (0.03, y + 0.012, 0.2)], (0, 0, -1), 0.003, 0.0035, sides=6)
    m.part(bow, f"foot.{side}", "Lace")


APRON_TOP = 0.545


def apron(m):
    """Bistro apron: tied at the waist, hanging straight to the knees in soft folds.
    The top follows the hips; lower down it follows the thighs halfway."""
    top, bottom, span, cols, rows = APRON_TOP, 0.27, math.radians(108), 56, 26
    axis = Vector((0.01, 0, 0))
    grid = []
    reach = [0.0] * (cols + 1)
    for i in range(rows + 1):
        z = top + (bottom - top) * i / rows
        t = i / rows
        row = []
        for j in range(cols + 1):
            a = -span + 2 * span * j / cols
            d = Vector((math.cos(a), math.sin(a), 0))
            o = axis + Vector((0, 0, z))
            reach[j] = max(reach[j], m.fit(("jacket", "leg.L", "leg.R"), o, a))  # hangs straight down from the widest point above
            r = reach[j] + 0.014 + 0.035 * min(1, t * 3) + 0.006 * t * math.sin(9 * a)
            row.append(m.bm.verts.new(o + d * r))
        grid.append(row)
    faces = []
    for r0, r1 in zip(grid, grid[1:]):
        for j in range(cols):
            faces.append(m.bm.faces.new((r0[j], r1[j], r1[j + 1], r0[j + 1])))
    verts = [v for r in grid for v in r]
    solid = bmesh.ops.solidify(m.bm, geom=faces, thickness=0.004)
    verts += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]

    def weights(p):
        t = max(0.0, min(1.0, (top - 0.015 - p.z) / 0.12))
        left = max(0.0, min(1.0, 0.5 + p.y / 0.12))
        return {"hips": 1 - 0.85 * t, "thigh.L": 0.85 * t * left, "thigh.R": 0.85 * t * (1 - left)}

    m.weigh(verts, weights)
    m.paint(verts, "Body")
    # Waist ties: a band all the way round, knotted at the front on the near side.
    fit = [m.fit(("jacket",), axis + Vector((0, 0, top - 0.004)), 2 * math.pi * j / 48) + 0.008 for j in range(48)]
    band = ring_band(m.bm, lambda z: axis + Vector((0, 0, z)), lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48], top - 0.015, top + 0.008, rows=1, sides=48)
    m.part(band, "hips", "Body")
    knot = m.hit("jacket", (0.01 + 0.5 * math.cos(-0.9), 0.5 * math.sin(-0.9), top - 0.004), (-math.cos(-0.9), -math.sin(-0.9), 0))[0]
    m.part(uv_ellipsoid(m.bm, knot + Vector((0.012, -0.012, 0)), (0.014, 0.014, 0.012)), "hips", "Body")
    for dz, dy in ((-0.1, 0.012), (-0.08, -0.014)):
        string = [knot + Vector((0.016, -0.014, 0)), knot + Vector((0.022, -0.02 + dy * 0.5, dz * 0.5)), knot + Vector((0.026, -0.02 + dy, dz))]
        m.part(tube(m.bm, string, [0.005, 0.005, 0.004], sides=6), "hips", "Body")


def towel(m):
    """A kitchen towel tucked into the apron strings at the near hip, folded over and
    hanging down the side in soft folds."""
    top, length, width = APRON_TOP + 0.004, 0.2, 0.075
    angle = math.radians(-62)  # around the waist, toward the near side
    rows, cols = 14, 8
    grid = []
    for i in range(rows + 1):
        t = i / rows
        z = top + 0.025 - length * t
        row = []
        for j in range(cols + 1):
            a = angle + (j / cols - 0.5) * width / 0.16
            d = Vector((math.cos(a), math.sin(a), 0))
            r = m.fit(("jacket", "leg.L", "leg.R"), Vector((0.01, 0, max(z, 0.3))), a)
            fold = 0.006 * math.sin(math.pi * 3 * j / cols) * t
            row.append(m.bm.verts.new(Vector((0.01, 0, z)) + d * (r + 0.03 + 0.012 * min(1, t * 4) + fold)))
        grid.append(row)
    faces = [m.bm.faces.new((r0[j], r1[j], r1[j + 1], r0[j + 1])) for r0, r1 in zip(grid, grid[1:]) for j in range(cols)]
    verts = [v for r in grid for v in r]
    solid = bmesh.ops.solidify(m.bm, geom=faces, thickness=0.004)
    verts += [v for v in solid["geom"] if isinstance(v, bmesh.types.BMVert)]

    def weights(p):
        t = max(0.0, min(1.0, (APRON_TOP - 0.02 - p.z) / 0.12))
        return {"hips": 1 - 0.8 * t, "thigh.R": 0.8 * t}

    m.weigh(verts, weights)
    m.paint(verts, "Towel")
    # The fold over the apron string.
    m.part(tube(m.bm, [v.co for v in grid[0]], [0.005] * (cols + 1), sides=8), "hips", "Towel")


# --- Surface data for the Godot shaders -----------------------------------------
# glTF keeps only flat material factors and image textures, so the chef's skin,
# cloth, hair and leather are shaded in Godot (`godot/shaders/chef_*.gdshader`,
# swapped in by `godot/models/fighter.glb.import`). They read, per vertex:
#   UV  = (rest x, rest z), UV2.x = rest y: the rest-pose position, so procedural
#         patterns stick to the cloth and skin as the mesh deforms (no UV unwrap).
#   COLOR.r = ambient occlusion baked in the rest pose, COLOR.g / COLOR.b = two
#         masks whose meaning depends on the material (see `masks`).
# Everything is deterministic: fixed ray sets, no randomness.

# Which occluders darken which vertices: a part is only shadowed by parts that stay
# put relative to it, so a raised arm doesn't carry a baked shadow off the torso.
AO_GROUP = {"hips": "core", "spine": "core", "head": "core", "pie": "pie"}
for _side in ("L", "R"):
    AO_GROUP.update({f"upper_arm.{_side}": f"arm.{_side}", f"forearm.{_side}": f"arm.{_side}"})
    AO_GROUP.update({f"thigh.{_side}": f"leg.{_side}", f"shin.{_side}": f"leg.{_side}", f"foot.{_side}": f"leg.{_side}"})
AO_OCCLUDERS = {"core": ("core",), "pie": ("pie",), "arm.L": ("arm.L",), "arm.R": ("arm.R",),
                "leg.L": ("leg.L", "core"), "leg.R": ("leg.R", "core")}
AO_REACH = 0.07  # meters: local creases and contact shadows, not whole-body shade


def hemisphere(n=48):
    """`n` fixed, evenly spread directions on the +Z hemisphere (a Fibonacci spiral)."""
    golden = math.pi * (3 - math.sqrt(5))
    out = []
    for i in range(n):
        z = 1 - (i + 0.5) / n
        r = math.sqrt(1 - z * z)
        out.append(Vector((r * math.cos(golden * i), r * math.sin(golden * i), z)))
    return out


def gauss(p, center, radius):
    return math.exp(-((p - Vector(center)).length / radius) ** 2)


def smooth(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


EYES = []  # eyeball centers, filled in by `face`
STAINS = [((0.17, 0.03, 0.64), 0.016), ((0.155, -0.075, 0.70), 0.011), ((0.12, 0.11, 0.58), 0.012)]


def masks(p, mat, bone):
    """(g, b) shader masks for a rest-pose point `p` of material `mat`."""
    if mat == "Skin" and bone in ("head", "spine"):
        flush = max(gauss(p, (0.07, 0.045, 1.035), 0.03), gauss(p, (0.07, -0.045, 1.035), 0.03),
                    gauss(p, (0.105, 0, 1.045), 0.022), 0.75 * gauss(p, (0.06, 0, 0.985), 0.03))
        if abs(p.y) > 0.074 and -0.035 < p.x < 0.015 and 1.02 < p.z < 1.1:  # ears
            flush = max(flush, 0.55 * smooth(0.074, 0.084, abs(p.y)))
        stubble = smooth(1.035, 1.0, p.z) * smooth(-0.04, 0.02, p.x) * smooth(0.93, 0.965, p.z)
        stubble = max(stubble, smooth(1.03, 1.02, p.z) * smooth(1.0, 1.012, p.z) * smooth(0.075, 0.09, p.x))  # upper lip
        return min(1.0, flush), stubble
    if mat == "Skin":  # hands: knuckles and fingertips flush a little
        return 0.5 * smooth(WRIST[1] - 0.05, WRIST[1] - 0.08, p.z), 0.0
    if mat == "Hair":
        gray = smooth(1.085, 1.05, p.z) * smooth(0.055, 0.075, abs(p.y))  # graying at the temples
        lateral = 1.0 if p.x > 0.06 else 0.0  # brows and mustache run sideways
        return gray, lateral
    if mat == "Jacket":
        stain = max(gauss(p, c, r) for c, r in STAINS)
        cuff = 0.15 * smooth(WRIST[1] + 0.1, WRIST[1] + 0.04, p.z) * smooth(0.12, 0.16, abs(p.y))
        return min(1.0, max(stain, cuff)), 0.0
    if mat == "Shoe":
        return smooth(0.03, 0.06, p.z) * gauss(p, (0.085, p.y, 0.07), 0.035), 0.0
    if mat == "Eye":
        for c in EYES:
            if (p - c).length < 0.02:
                d = p - c
                return smooth(0.35, 1.0, math.hypot(d.y, d.z) / 0.0135), 0.0
    return 0.0, 0.0


def surface_data(bm, deform, mesh, bone_names=None):
    """Writes the rest-position UVs and the AO / mask colors (see above) onto `mesh`,
    which was just made from `bm` (same vertex order)."""
    bone_names = bone_names or BONE_NAMES
    bm.verts.ensure_lookup_table()
    cos = [v.co.copy() for v in bm.verts]
    group = []
    for v in bm.verts:
        d = v[deform] if deform is not None else {}
        bone = bone_names[max(d.items(), key=lambda kv: kv[1])[0]] if d else "hips"
        group.append(AO_GROUP.get(bone, "core"))
    trees = {}
    for key, occluders in AO_OCCLUDERS.items():
        polys = [[v.index for v in f.verts] for f in bm.faces if group[f.verts[0].index] in occluders]
        trees[key] = BVHTree.FromPolygons(cos, polys) if polys else None
    rays = hemisphere()
    colors = []
    for v in bm.verts:
        n = v.normal
        tree = trees[group[v.index]]
        occluded = total = 0.0
        if tree is not None and n.length > 0.5:
            basis = n.to_track_quat("Z", "Y").to_matrix()
            origin = v.co + n * 2e-4
            for r in rays:
                d = basis @ r
                w = r.z  # cosine weighted
                total += w
                hit = tree.ray_cast(origin, d, AO_REACH)
                if hit[0] is not None:
                    occluded += w * (1 - (hit[3] / AO_REACH) ** 2)
        ao = 1 - occluded / total if total else 1.0
        face = next(iter(v.link_faces), None)
        mat = mesh.materials[face.material_index].name if face is not None and mesh.materials else ""
        d = v[deform] if deform is not None else {}
        bone = bone_names[max(d.items(), key=lambda kv: kv[1])[0]] if d else ""
        g, b = masks(v.co, mat, bone)
        colors.append((ao, g, b, 1.0))
    color = mesh.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
    for i, c in enumerate(colors):
        color.data[i].color = c
    mesh.color_attributes.active_color = color
    rest = mesh.uv_layers.new(name="Rest")
    rest_y = mesh.uv_layers.new(name="RestY")
    for loop in mesh.loops:
        co = cos[loop.vertex_index]
        rest.data[loop.index].uv = (co.x, co.z)
        rest_y.data[loop.index].uv = (co.y, 0.0)


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

    body = bpy.data.objects.new("Chef", mesh)
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


def holding_pie(pose, facing):
    """Shows the pie in the right fist, its cream facing `facing` degrees as seen by the
    camera (0 = forward, 90 = up). At rest the cream faces down the arm (-90)."""
    pitch = lambda bone: (lambda v: v[0] if isinstance(v, tuple) else v)(pose.get(bone, 0))  # noqa: E731
    chain = sum(pitch(b) for b in ("hips", "spine", "upper_arm.R", "forearm.R"))
    return with_(pose, pie=facing + 90 - chain, pie_scale=1)


# Pie throw: pulled out, shown off at the shoulder, cocked back and slung overhand.
PIE_SHOW = holding_pie(with_(g, spine=-4, upper_arm_R=25, forearm_R=105, upper_arm_L=10, forearm_L=110), 70)
PIE_WIND = holding_pie(
    planted(with_(g, hips_loc=(-0.04, -0.05), spine=14, head=-12, upper_arm_R=-55, forearm_R=95, upper_arm_L=60, forearm_L=25), 0.17, -0.2), 40
)
PIE_SWING = holding_pie(planted(with_(g, hips_loc=(0.03, -0.06), spine=-4, head=2, upper_arm_R=55, forearm_R=55, upper_arm_L=25, forearm_L=60), 0.24, -0.2), 5)
PIE_RELEASE = planted(with_(g, hips_loc=(0.08, -0.07), spine=-18, head=12, upper_arm_R=95, forearm_R=5, upper_arm_L=-25, forearm_L=50), 0.28, -0.2)
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
    # Specials. Neutral (pie throw): the pie leaves the hand on 12 and flies as a
    # projectile. Side: lunge 8-16. Up: rise 4-18. Down: plunge from 15.
    "pie_throw": [(1, g), (4, PIE_SHOW), (7, PIE_SHOW), (10, PIE_WIND), (11, PIE_SWING), (12, PIE_RELEASE), (22, PIE_RELEASE), (36, g)],
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

# --- Ledge hang and getups --------------------------------------------------------
# On a ledge the sim puts the origin LEDGE_HANG_X (0.1 m) outside the edge with the
# top of the 1.2 m hurtbox level with the deck, so the corner is at model (0.1, 1.2).
# A getup slides the origin linearly to `inward` meters onto the stage over `total`
# frames (`ledge_getup_pos` in sim/src/fighter.rs). The clips are designed in ledge
# space (origin = the corner, +x onto the stage, z up) and converted to the sliding
# model space frame by frame, so hands stay on the corner and feet on the deck.

BODY_HEIGHT = 1.2
HANG_X = 0.1
LIMBS = {"arm": (SHOULDER[1] - ELBOW[1], ELBOW[1] - WRIST[1] + FIST)}
GRIP = (0.035, 0.03)  # fist center, gripping over the corner (ledge space)


def _rot(angle, v):
    """`v` = (forward, up) turned `angle` degrees counter-clockwise (as the camera sees it)."""
    r = math.radians(angle)
    return (v[0] * math.cos(r) - v[1] * math.sin(r), v[0] * math.sin(r) + v[1] * math.cos(r))


def _add(*vs):
    return (sum(v[0] for v in vs), sum(v[1] for v in vs))


def _pitch(pose, bone):
    v = pose.get(bone, 0)
    return v[0] if isinstance(v, tuple) else v


def joints(pose):
    """Side-view forward kinematics: (forward, up) of the body's key points in model space."""
    fwd, up = pose.get("hips_loc", (0, 0))
    hips = (fwd, 0.55 + up)
    ah = _pitch(pose, "hips")
    asp = ah + _pitch(pose, "spine")
    spine = _add(hips, _rot(ah, (0, 0.13)))
    neck = _add(spine, _rot(asp, (0, 0.22)))
    ahd = asp + _pitch(pose, "head")
    out = {
        "hips": hips,
        "spine": spine,
        "neck": neck,
        "crown": _add(neck, _rot(ahd, (0, 0.24))),
        "toque": _add(neck, _rot(ahd, (-0.01, 0.46))),
        "nose": _add(neck, _rot(ahd, (0.12, 0.14))),
        "seat": _add(hips, _rot(ah, (-0.12, -0.06))),
        "belly": _add(hips, _rot(ah, (0.17, 0.08))),
        "back": _add(spine, _rot(asp, (-0.12, 0.12))),
    }
    for side in ("L", "R"):
        au = asp + _pitch(pose, f"upper_arm.{side}")
        af = au + _pitch(pose, f"forearm.{side}")
        out[f"shoulder.{side}"] = shoulder = _add(spine, _rot(asp, (0, SHOULDER[1] - 0.68)))
        out[f"elbow.{side}"] = elbow = _add(shoulder, _rot(au, (0, -LIMBS["arm"][0])))
        out[f"fist.{side}"] = _add(elbow, _rot(af, (0, -LIMBS["arm"][1])))
        at = ah + _pitch(pose, f"thigh.{side}")
        ash = at + _pitch(pose, f"shin.{side}")
        aft = ash + _pitch(pose, f"foot.{side}")
        out[f"hip.{side}"] = hip = _add(hips, _rot(ah, (0, HIP[1] - 0.55)))
        out[f"knee.{side}"] = knee = _add(hip, _rot(at, (0, -THIGH_LEN)))
        out[f"ankle.{side}"] = ankle = _add(knee, _rot(ash, (0, -SHIN_LEN)))
        out[f"toe.{side}"] = _add(ankle, _rot(aft, (0.16, -0.05)))
        out[f"heel.{side}"] = _add(ankle, _rot(aft, (-0.06, -0.06)))
    return out


def arm_ik(pose, side, target):
    """Puts the fist's center at `target` (model space), the elbow bending naturally."""
    upper, lower = LIMBS["arm"]
    s = joints(pose)[f"shoulder.{side}"]
    dx, dz = target[0] - s[0], target[1] - s[1]
    dist = max(min(math.hypot(dx, dz), upper + lower - 1e-4), abs(upper - lower) + 1e-3)
    aim = math.degrees(math.atan2(dx, -dz))
    at_shoulder = math.degrees(math.acos((upper**2 + dist**2 - lower**2) / (2 * upper * dist)))
    at_wrist = math.degrees(math.acos((lower**2 + dist**2 - upper**2) / (2 * lower * dist)))
    chain = _pitch(pose, "hips") + _pitch(pose, "spine")
    pose[f"upper_arm.{side}"] = aim - at_shoulder - chain
    pose[f"forearm.{side}"] = at_shoulder + at_wrist
    return pose


def knee_down(pose, side, knee, shin=-95, foot=-70):
    """Kneels: the thigh aims at `knee` (model space), the shin lies back along the
    floor at absolute angle `shin`, the foot pointed."""
    hip = joints(pose)[f"hip.{side}"]
    aim = math.degrees(math.atan2(knee[0] - hip[0], -(knee[1] - hip[1])))
    pose[f"thigh.{side}"] = aim - _pitch(pose, "hips")
    pose[f"shin.{side}"] = shin - aim
    pose[f"foot.{side}"] = foot
    return pose


ARM_BONES = ("upper_arm.{}", "forearm.{}")
LEG_BONES = ("thigh.{}", "shin.{}", "foot.{}")


def _unwrap(angle, near):
    """`angle` plus whole turns, as close as possible to `near`."""
    return angle + 360 * round((near - angle) / 360)


def _hermite(keys, t):
    """Catmull-Rom through [(frame, value)], flat at both ends."""
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    k = max(i for i in range(len(keys) - 1) if keys[i][0] <= t)
    (t0, v0), (t1, v1) = keys[k], keys[k + 1]

    def slope(i):
        if i == 0 or i == len(keys) - 1:
            return 0.0
        return (keys[i + 1][1] - keys[i - 1][1]) / (keys[i + 1][0] - keys[i - 1][0])

    dt = t1 - t0
    u = (t - t0) / dt
    h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2
    return h00 * v0 + h10 * dt * slope(k) + h01 * v1 + h11 * dt * slope(k + 1)


def ledge_clip(total, inward, keys):
    """One getup, keyed on every frame 1..total. `keys` is [(frame, spec)] where spec has
    "hips_at": the hips' (x, z) in ledge space (or "ground": clearance, which sets the
    height so the body's lowest point rests that far above the deck), pitches for
    "hips", "spine", "head" and any limb bone, and constraints "grip": sides whose fist
    holds the corner, "plant": {side: ankle (x, z)}, "kneel": {side: knee (x, z)}.
    A constraint shared by two neighboring keys holds on every frame between them."""

    def root(f):
        t = f / total
        return (-HANG_X + (HANG_X + inward) * t, -BODY_HEIGHT + BODY_HEIGHT * t)

    def local(p, f):
        r = root(f)
        return (p[0] - r[0], p[1] - r[1])

    def solve(spec, f, hips_at):
        pose = {b: v for b, v in spec.items() if b in BONE_NAMES}
        loc = local(hips_at, f)
        pose["hips_loc"] = (loc[0], loc[1] - 0.55)
        return pose

    def constrain(pose, f, grip, plant, kneel):
        for side, at in kneel.items():
            knee_down(pose, side, local(at, f))
        for side, at in plant.items():
            x, z = local(at, f)
            leg_ik(pose, side, x, z - ANKLE[1])
        for side in grip:
            arm_ik(pose, side, local(GRIP, f))
        return pose

    def ground(pose, f, clearance):
        lowest = min(p[1] for p in joints(pose).values())
        fwd, up = pose["hips_loc"]
        floor = local((0, 0), f)[1]
        pose["hips_loc"] = (fwd, up + floor + clearance - lowest)

    # Every key, fully solved: its hips in ledge space and its bone angles.
    solved = []
    for frame, spec in keys:
        hips_at = spec.get("hips_at", (0, 0))
        pose = constrain(solve(spec, frame, hips_at), frame, spec.get("grip", ()), spec.get("plant", {}), spec.get("kneel", {}))
        if "ground" in spec:
            ground(pose, frame, spec["ground"])
            constrain(pose, frame, spec.get("grip", ()), spec.get("plant", {}), spec.get("kneel", {}))
        hl = pose["hips_loc"]
        r = root(frame)
        if solved:  # turn the shortest way from the previous key (whole turns are kept)
            for b in BONE_NAMES:
                if b != "pie" and not isinstance(pose.get(b, 0), tuple):
                    pose[b] = _unwrap(pose.get(b, 0), solved[-1][2].get(b, 0))
        solved.append((frame, spec, pose, (hl[0] + r[0], hl[1] + 0.55 + r[1])))

    channels = [b for b in BONE_NAMES if b != "pie"]
    out = []
    for f in range(1, total + 1):
        k = max(i for i in range(len(solved)) if solved[i][0] <= f)
        nxt = min(k + 1, len(solved) - 1)
        pose = {b: _hermite([(fr, p.get(b, 0)) for fr, _, p, _ in solved], f) for b in channels}
        hx = _hermite([(fr, h[0]) for fr, _, _, h in solved], f)
        hz = _hermite([(fr, h[1]) for fr, _, _, h in solved], f)
        loc = local((hx, hz), f)
        pose["hips_loc"] = (loc[0], loc[1] - 0.55)
        a, b = solved[k][1], solved[nxt][1]
        if "ground" in a and "ground" in b:
            ground(pose, f, _hermite([(fr, sp.get("ground", 0)) for fr, sp, _, _ in solved], f))
        grip = [s for s in a.get("grip", ()) if s in b.get("grip", ())]
        plant = {s: at for s, at in a.get("plant", {}).items() if b.get("plant", {}).get(s) == at}
        kneel = {s: at for s, at in a.get("kneel", {}).items() if b.get("kneel", {}).get(s) == at}
        pose = constrain(pose, f, grip, plant, kneel)
        if out:
            for b in channels:
                pose[b] = _unwrap(pose[b], out[-1][1][b])
        out.append((f, pose))
    return out


def stand_key(total, inward):
    """The idle pose (`guard()`) at the end of a getup, feet planted where it stands."""
    spec = {b: v for b, v in g.items() if b in BONE_NAMES and not b.startswith(("thigh", "shin", "foot"))}
    spec["hips_at"] = (inward + g["hips_loc"][0], 0.55 + g["hips_loc"][1])
    spec["plant"] = {"R": (inward + 0.11, ANKLE[1]), "L": (inward - 0.11, ANKLE[1])}
    return (total, spec)


def hang_clip(length=80):
    """Dangling from the corner: a slow pendulum sway and breathing, on the world clock."""
    out = []
    for f in range(1, length + 2):
        ph = 2 * math.pi * (f - 1) / length
        sway = math.sin(ph)
        breath = math.sin(2 * ph)
        pose = {
            "hips": -3 + 2.5 * sway,
            "spine": 4 + 1.2 * breath,
            "head": 22 - 3 * sway + 1.5 * breath,
            "thigh.R": 12 + 6 * math.sin(ph - 0.6),
            "shin.R": -28 - 6 * math.sin(ph - 1.0),
            "foot.R": -35,
            "thigh.L": -4 + 6 * math.sin(ph - 0.9),
            "shin.L": -14 - 5 * math.sin(ph - 1.3),
            "foot.L": -40,
        }
        hips_at = (-0.26 - 0.012 * sway, -0.6 + 0.004 * breath)
        pose["hips_loc"] = (hips_at[0] + HANG_X, hips_at[1] + BODY_HEIGHT - 0.55)
        for side in ("R", "L"):
            arm_ik(pose, side, (GRIP[0] + HANG_X, GRIP[1] + BODY_HEIGHT))
        out.append((f, pose))
    return out


HANG = hang_clip()[0][1]
HANG_SPEC = {b: v for b, v in HANG.items() if b in BONE_NAMES and not b.startswith(("upper_arm", "forearm"))}
HANG_SPEC.update(hips_at=(HANG["hips_loc"][0] - HANG_X, HANG["hips_loc"][1] + 0.55 - BODY_HEIGHT), grip=("R", "L"))


def ledge_animations():
    climb = ledge_clip(20, 0.8, [
        (1, HANG_SPEC),
        # Hoist: chin to the deck, elbows driving down.
        (5, dict(hips_at=(-0.17, -0.34), hips=-8, spine=-6, head=12, grip=("R", "L"),
                 **{"thigh.R": 30, "shin.R": -60, "foot.R": -30, "thigh.L": 5, "shin.L": -30, "foot.L": -35})),
        # Mantle: chest over the edge, hands pressing down, the near knee coming up.
        (8, dict(hips_at=(-0.06, -0.06), hips=-28, spine=-22, head=30, grip=("R", "L"),
                 **{"thigh.R": 105, "shin.R": -120, "foot.R": -20, "thigh.L": 20, "shin.L": -50, "foot.L": -35})),
        # Knee on the deck.
        (11, dict(hips_at=(0.08, 0.2), hips=-20, spine=-25, head=30, grip=("R", "L"), kneel={"R": (0.2, 0.05)},
                  **{"thigh.L": 30, "shin.L": -70, "foot.L": -30})),
        # Step up: the far foot planted, rising, arms letting go.
        (15, dict(hips_at=(0.36, 0.38), hips=-10, spine=-24, head=26, plant={"L": (0.34, ANKLE[1])},
                  **{"upper_arm.R": 20, "forearm.R": 60, "upper_arm.L": 5, "forearm.L": 70,
                     "thigh.R": 60, "shin.R": -100, "foot.R": 10})),
        (18, dict(hips_at=(0.66, 0.5), hips=-2, spine=-14, head=12, plant={"L": (0.69, ANKLE[1])},
                  **{"upper_arm.R": 32, "forearm.R": 95, "upper_arm.L": 18, "forearm.L": 105,
                     "thigh.R": 30, "shin.R": -40, "foot.R": 0})),
        stand_key(20, 0.8),
    ])
    roll = ledge_clip(25, 1.6, [
        (1, HANG_SPEC),
        (4, dict(hips_at=(-0.15, -0.3), hips=-10, spine=-8, head=10, grip=("R", "L"),
                 **{"thigh.R": 40, "shin.R": -80, "thigh.L": 30, "shin.L": -70, "foot.R": -20, "foot.L": -20})),
        # Over the top, diving into the tuck.
        (7, dict(hips_at=(0.0, 0.12), hips=-45, spine=-30, head=10, grip=("R", "L"),
                 **{"thigh.R": 110, "shin.R": -130, "thigh.L": 100, "shin.L": -130, "foot.R": -10, "foot.L": -10})),
        # The tucked roll: one full turn around the pelvis, low along the deck.
        (10, dict(hips_at=(0.3, 0), ground=0.01, hips=-120, spine=-50, head=-45,
                  **{"thigh.R": 135, "shin.R": -150, "thigh.L": 130, "shin.L": -150, "foot.R": 15, "foot.L": 15,
                     "upper_arm.R": 95, "forearm.R": 100, "upper_arm.L": 85, "forearm.L": 105})),
        (13, dict(hips_at=(0.6, 0), ground=0.01, hips=-200, spine=-50, head=-45,
                  **{"thigh.R": 135, "shin.R": -150, "thigh.L": 130, "shin.L": -150, "foot.R": 15, "foot.L": 15,
                     "upper_arm.R": 95, "forearm.R": 100, "upper_arm.L": 85, "forearm.L": 105})),
        (16, dict(hips_at=(0.9, 0), ground=0.01, hips=-275, spine=-50, head=-45,
                  **{"thigh.R": 135, "shin.R": -150, "thigh.L": 130, "shin.L": -150, "foot.R": 15, "foot.L": 15,
                     "upper_arm.R": 95, "forearm.R": 100, "upper_arm.L": 85, "forearm.L": 105})),
        (19, dict(hips_at=(1.2, 0), ground=0.02, hips=-335, spine=-30, head=0,
                  **{"thigh.R": 110, "shin.R": -140, "thigh.L": 100, "shin.L": -135, "foot.R": 0, "foot.L": 0,
                     "upper_arm.R": 60, "forearm.R": 110, "upper_arm.L": 50, "forearm.L": 115})),
        # Pops up out of the crouch.
        (22, dict(hips_at=(1.45, 0.36), hips=-360, spine=-25, head=15, plant={"R": (1.62, ANKLE[1]), "L": (1.4, ANKLE[1])},
                  **{"upper_arm.R": 20, "forearm.R": 90, "upper_arm.L": 10, "forearm.L": 100})),
        stand_key(25, 1.6),
    ])
    attack = ledge_clip(30, 1.1, [
        (1, HANG_SPEC),
        (5, dict(hips_at=(-0.16, -0.32), hips=-8, spine=-6, head=12, grip=("R", "L"),
                 **{"thigh.R": 35, "shin.R": -70, "foot.R": -30, "thigh.L": 10, "shin.L": -40, "foot.L": -35})),
        (9, dict(hips_at=(-0.02, 0.02), hips=-30, spine=-25, head=30, grip=("R", "L"),
                 **{"thigh.R": 110, "shin.R": -125, "foot.R": -20, "thigh.L": 60, "shin.L": -90, "foot.L": -30})),
        # Crouched on the deck, the near leg cocked behind for the sweep.
        (12, dict(hips_at=(0.3, 0.3), hips=5, spine=-20, head=15, plant={"L": (0.32, ANKLE[1])},
                  **{"upper_arm.R": -30, "forearm.R": 60, "upper_arm.L": 40, "forearm.L": 80,
                     "thigh.R": -50, "shin.R": -60, "foot.R": -30})),
        (14, dict(hips_at=(0.42, 0.3), hips=10, spine=-10, head=8, plant={"L": (0.38, ANKLE[1])},
                  **{"upper_arm.R": -40, "forearm.R": 40, "upper_arm.L": 50, "forearm.L": 70,
                     "thigh.R": -10, "shin.R": -40, "foot.R": -20})),
        # Active 15-18: a low sweeping kick along the deck, out to ~1 m.
        (15, dict(hips_at=(0.48, 0.32), hips=25, spine=-25, head=-5, plant={"L": (0.38, ANKLE[1])},
                  **{"upper_arm.R": -60, "forearm.R": 30, "upper_arm.L": 60, "forearm.L": 60,
                     "thigh.R": 60, "shin.R": -15, "foot.R": -40})),
        (18, dict(hips_at=(0.52, 0.32), hips=30, spine=-28, head=-8, plant={"L": (0.38, ANKLE[1])},
                  **{"upper_arm.R": -65, "forearm.R": 25, "upper_arm.L": 65, "forearm.L": 55,
                     "thigh.R": 65, "shin.R": -5, "foot.R": -45})),
        (23, dict(hips_at=(0.7, 0.42), hips=8, spine=-14, head=4, plant={"L": (0.75, ANKLE[1])},
                  **{"upper_arm.R": 20, "forearm.R": 80, "upper_arm.L": 30, "forearm.L": 90,
                     "thigh.R": 50, "shin.R": -80, "foot.R": 0})),
        stand_key(30, 1.1),
    ])
    return {"ledge_hang": hang_clip(), "ledge_climb": climb, "ledge_roll": roll, "ledge_attack": attack}


ANIMATIONS.update(ledge_animations())


def apply_pose(rig, pose):
    for pb in rig.pose.bones:
        value = pose.get(pb.name, 0)
        pitch, twist, spread = value if isinstance(value, tuple) else (value, 0, 0)
        # Local X = world +Y, so counter-clockwise from the camera (-Y) is -X.
        pb.rotation_euler = (math.radians(-pitch), math.radians(twist), math.radians(spread))
        pb.location = (0, 0, 0)
    fwd, up = pose.get("hips_loc", (0, 0))
    rig.pose.bones["hips"].location = (0, up, fwd)  # hips local axes: Y = up, Z = forward
    rig.pose.bones["pie"].scale = (pose.get("pie_scale", 0),) * 3


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
            # Every action keys the pie's scale, so it never lingers from the pie throw.
            rig.pose.bones["pie"].keyframe_insert("scale", frame=frame, group="pie")
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, keys[0][0], action)
        track.mute = True
    rig.animation_data.action = None
    apply_pose(rig, guard())


def build_pie():
    """The flying pie (for the projectile): cream facing +X, centered on the origin."""
    bm = bmesh.new()
    parts = pie_parts(bm, Matrix.Rotation(math.pi / 2, 4, "Y") @ Matrix.Translation((0, 0, -0.05)))
    mesh = bpy.data.meshes.new("PieMesh")
    mats = materials()
    for mat, verts in parts.items():
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = MAT[mat]
            f.smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.normal_update()
    bm.to_mesh(mesh)
    for mat in mats:
        mesh.materials.append(mat)
    surface_data(bm, None, mesh)
    bm.free()
    obj = bpy.data.objects.new("Pie", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    rig = build_rig(chef_mesh())
    build_actions(rig)

    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH, **CHEF_EXPORT)

    # The pie goes in a file of its own; it isn't saved in fighter.blend.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_pie()
    bpy.ops.export_scene.gltf(filepath=PIE_GLB_PATH, export_format="GLB", export_yup=True, export_animations=False, export_cameras=False, export_lights=False, **CHEF_EXPORT)


# The chef's meshes carry baked AO and masks in their color attribute (see
# `surface_data`), which glTF only exports when asked to.
CHEF_EXPORT = dict(export_vertex_color="ACTIVE")


def export(path, **options):
    """Shared with export_fighter.py, so hand edits to the .blend export the same way,
    and with the other characters' scripts. `options` are extra glTF exporter settings
    (the chef passes `CHEF_EXPORT`)."""
    bpy.ops.export_scene.gltf(
        **options,
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

