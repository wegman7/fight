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
    """Round, ruddy face: full cheeks, a bulbous nose, a soft double chin."""
    b = Blob(resolution=0.0035)
    b.ell((-0.005, 0, 1.085), (0.093, 0.079, 0.09))  # cranium
    b.ell((0.025, 0, 1.03), (0.075, 0.07, 0.072))  # face and jaw
    b.ell((0.05, 0, 0.982), (0.045, 0.05, 0.026), stiffness=3)  # chin
    b.ell((0.02, 0, 0.972), (0.05, 0.06, 0.03), stiffness=3)  # double chin
    b.cap((-0.012, 0, 0.84), (0.0, 0, 0.99), 0.054)  # thick neck, down into the collar
    for s in (1, -1):
        b.ell((0.062, s * 0.043, 1.035), (0.03, 0.03, 0.026), stiffness=3)  # cheeks
        b.cap((-0.02, s * 0.058, 1.02), (0.06, s * 0.03, 0.978), 0.016, stiffness=3)  # jawline
        b.cap((0.085, s * 0.012, 1.097), (0.08, s * 0.052, 1.1), 0.011, stiffness=3)  # brow ridge
        b.ball((0.078, s * 0.033, 1.072), 0.014, stiffness=4, negative=True)  # eye socket
        # Ears, with a hollow.
        b.ell((-0.012, s * 0.08, 1.06), (0.018, 0.011, 0.03), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-10 * s)))
        b.ell((-0.006, s * 0.088, 1.062), (0.009, 0.007, 0.016), stiffness=5, negative=True)
    # A big round nose: bridge and bulb.
    b.cap((0.088, 0, 1.09), (0.104, 0, 1.05), 0.011, stiffness=3)
    b.ball((0.106, 0, 1.042), 0.017, stiffness=3)
    # Mouth: a crease between the lips, and a full lower lip.
    b.cap((0.092, -0.02, 1.006), (0.092, 0.02, 1.006), 0.004, stiffness=6, negative=True)
    b.ell((0.089, 0, 0.998), (0.012, 0.021, 0.008), stiffness=4)
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
    b = Blob(resolution=0.006)
    b.ell((0.005, 0, 0.775), (0.105, 0.15, 0.11))  # chest
    b.ell((0.04, 0, 0.625), (0.13, 0.135, 0.13))  # belly
    b.ell((0.0, 0, 0.52), (0.11, 0.14, 0.08))  # hips
    for s in (1, -1):
        b.ell((-0.005, s * 0.095, 0.845), (0.06, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.155, 0.83), (0.055, 0.045, 0.045))  # shoulder seam
        b.ell((-0.06, s * 0.06, 0.78), (0.04, 0.06, 0.07))  # shoulder blades
    b.ell((0.0, 0, 0.45), (0.12, 0.142, 0.02), stiffness=4)  # hem
    return b


def sleeve_blob(s):
    y = s * SHOULDER[0]
    b = Blob(resolution=0.005)
    b.ell((0.0, y - s * 0.005, 0.825), (0.055, 0.055, 0.06))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.046)
    b.ell((0.012, y, 0.73), (0.035, 0.038, 0.06), stiffness=3)  # biceps
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.05), 0.043)
    b.ell((-0.008, y, 0.6), (0.036, 0.038, 0.05), stiffness=3)  # forearm
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


def leg_blob(s):
    """One leg of the baggy chef's trousers, with half of the seat."""
    y = s * HIP[0]
    b = Blob(resolution=0.006)
    b.ell((-0.025, s * 0.05, 0.48), (0.09, 0.07, 0.07))  # seat
    b.cap((0, y, HIP[1] - 0.05), (0, y, KNEE[1]), 0.066)
    b.ell((0.01, y + s * 0.004, 0.43), (0.07, 0.066, 0.1), stiffness=3)  # thigh
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.01), 0.054)
    b.ell((-0.012, y, 0.21), (0.052, 0.054, 0.08), stiffness=3)  # calf
    b.ell((0.0, y, 0.085), (0.06, 0.058, 0.02), stiffness=4)  # hem, breaking over the shoe
    return b


def shoe_blob(s):
    y = s * HIP[0]
    b = Blob(resolution=0.004)
    b.ell((0.04, y, 0.04), (0.09, 0.044, 0.04), stiffness=3)
    b.ell((0.115, y, 0.03), (0.05, 0.043, 0.03), stiffness=3)  # toe box
    b.ell((-0.025, y, 0.045), (0.042, 0.04, 0.045), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.1), 0.042)  # ankle, inside the trouser hem
    b.ell((0.05, y, -0.1), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat sole
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
    m.blob("head", head_blob(), 0.5, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    jacket = m.blob("jacket", jacket_blob(), 0.25, "Jacket", by_distance("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        m.blob(f"sleeve.{side}", sleeve_blob(s), 0.25, "Jacket", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", hand_blob(s), 0.3, "Skin", f"forearm.{side}")
        m.blob(f"leg.{side}", leg_blob(s), 0.25, "Pants", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"shoe.{side}", shoe_blob(s), 0.3, "Shoe", f"foot.{side}")
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
    apron(m)
    pie = pie_parts(m.bm, Matrix.Translation(Vector(PIE_PIVOT) + Vector((0, 0, -0.035))) @ Matrix.Rotation(math.pi, 4, "Y"))
    for mat, verts in pie.items():
        m.part(verts, "pie", mat)

    mesh = bpy.data.meshes.new("ChefMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    return mesh


def face(m):
    def on_skin(y, z, lift):
        """The point on the face at height z and side offset y, lifted off the skin."""
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.033, 1.072, 0)
        eye = socket - Vector((0.0135 - 0.005, 0, 0))  # bulging 5 mm out of the socket
        m.part(uv_ellipsoid(m.bm, eye, (0.0135,) * 3, segments=(16, 10)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0123, 0, 0)), (0.0025, 0.0075, 0.0075), segments=(14, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0144, 0, 0)), (0.0012, 0.0036, 0.0036), segments=(10, 6)), "head", "Pupil")
        # Heavy upper lids, a third of the way over the eyes.
        lid = uv_ellipsoid(m.bm, eye + Vector((0.0, 0, 0.006)), (0.0142, 0.0152, 0.0105), segments=(16, 10))
        m.part(lid, "head", "Skin")
        # Bushy brows.
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.012, 1.098), (0.03, 1.103), (0.05, 1.099))]
        m.part(tube(m.bm, brow, [0.0045, 0.006, 0.0038], sides=8), "head", "Hair")
        # Handlebar mustache: from under the nose out over the cheeks, curling up.
        root = [on_skin(s * y, z, lift) for y, z, lift in ((0.002, 1.022, 0.002), (0.02, 1.017, 0.003), (0.04, 1.015, 0.004))]
        tip = root[-1]
        curl = root + [tip + Vector((-0.01, s * 0.016, 0.004)), tip + Vector((-0.016, s * 0.023, 0.016)), tip + Vector((-0.014, s * 0.017, 0.026)),
                       tip + Vector((-0.01, s * 0.011, 0.024))]
        m.part(tube(m.bm, curl, [0.009, 0.0095, 0.007, 0.0048, 0.0036, 0.0028, 0.002], sides=10), "head", "Hair")
    lip = on_skin(0, 1.0095, -0.004)
    m.part(uv_ellipsoid(m.bm, lip, (0.009, 0.019, 0.005), segments=(14, 8)), "head", "Lip")


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


def apron(m):
    """Bistro apron: tied at the waist, hanging straight to the knees in soft folds.
    The top follows the hips; lower down it follows the thighs halfway."""
    top, bottom, span, cols, rows = 0.545, 0.27, math.radians(108), 40, 18
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
    bm.to_mesh(mesh)
    bm.free()
    for mat in mats:
        mesh.materials.append(mat)
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
    export(GLB_PATH)

    # The pie goes in a file of its own; it isn't saved in fighter.blend.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_pie()
    bpy.ops.export_scene.gltf(filepath=PIE_GLB_PATH, export_format="GLB", export_yup=True, export_animations=False, export_cameras=False, export_lights=False)


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

