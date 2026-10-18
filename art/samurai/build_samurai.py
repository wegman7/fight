"""Builds the samurai: a lean swordsman with a topknot and headband, in a kimono top,
wide hakama and sandals, a katana in his near hand and its scabbard at his hip. Then
his armature and one action per pose name the sim reports (`Fighter::anim()`). Saves
`samurai.blend` next to this script and exports `godot/models/samurai.glb`.

    blender --background --factory-startup --python art/samurai/build_samurai.py

He stands on the chef's skeleton (same joints, same 1.2 m), so the shapes, pose
helpers and conventions come from `art/fighter/build_fighter.py` (see its README).
On top of it is one bone, `katana`, held in the right (near) fist. Each pose says
where the blade points with `aim`: degrees as seen by the game camera with the
fighter facing right, 0 = forward, 90 = up, 180 = backward.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "samurai.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "samurai.glb")

sys.path.insert(0, os.path.join(ROOT, "art", "fighter"))
import build_fighter as chef  # noqa: E402
from build_fighter import (  # noqa: E402
    AIR,
    ANKLE,
    FLINCH,
    FWD,
    HIP,
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

# The chef's bones, minus the pie, plus the katana: it lies along +X through the
# right fist (its hilt through the curled fingers), edge down.
GRIP = Vector((0.0, -0.166, 0.388))
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONES.append(("katana", "forearm.R", tuple(GRIP), tuple(GRIP + Vector((0.12, 0, 0))), FWD))
BONE_NAMES = [b[0] for b in BONES]
BLADE = 0.64  # from the habaki to the tip
TSUBA = 0.05  # the guard, this far in front of the grip

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the
# headband and obi) with the player's color; the rest keep their own.
MATERIALS = {
    "Body": ((0.70, 0.12, 0.12, 1), 0.7, 0.0),
    "Gi": ((0.10, 0.13, 0.26, 1), 0.85, 0.0),
    "Collar": ((0.90, 0.88, 0.82, 1), 0.8, 0.0),
    "Hakama": ((0.10, 0.10, 0.11, 1), 0.85, 0.0),
    "Skin": ((0.80, 0.60, 0.46, 1), 0.55, 0.0),
    "Lip": ((0.62, 0.38, 0.33, 1), 0.45, 0.0),
    "Hair": ((0.025, 0.022, 0.022, 1), 0.45, 0.0),
    "Eye": ((0.93, 0.91, 0.87, 1), 0.12, 0.0),
    "Iris": ((0.16, 0.09, 0.05, 1), 0.15, 0.0),
    "Pupil": ((0.01, 0.01, 0.01, 1), 0.1, 0.0),
    "Tabi": ((0.92, 0.91, 0.88, 1), 0.85, 0.0),
    "Straw": ((0.72, 0.58, 0.36, 1), 0.9, 0.0),
    "Steel": ((0.70, 0.72, 0.75, 1), 0.2, 0.9),
    "Edge": ((0.93, 0.94, 0.96, 1), 0.3, 0.6),
    "Iron": ((0.08, 0.075, 0.07, 1), 0.4, 0.8),
    "Gold": ((0.85, 0.66, 0.28, 1), 0.3, 1.0),
    "Wrap": ((0.04, 0.04, 0.07, 1), 0.7, 0.0),
    "Saya": ((0.03, 0.025, 0.025, 1), 0.15, 0.0),
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
    """A lean face: high cheekbones, a square jaw and chin, a straight nose."""
    b = Blob(resolution=0.0035)
    b.ell((-0.005, 0, 1.085), (0.088, 0.075, 0.09))  # cranium
    b.ell((0.022, 0, 1.03), (0.072, 0.063, 0.074))  # face and jaw
    b.ell((0.054, 0, 0.98), (0.04, 0.043, 0.024), stiffness=3)  # square chin
    b.cap((-0.012, 0, 0.84), (0.0, 0, 0.99), 0.047)  # neck
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
    """Black hair drawn back tight from the forehead (the topknot is separate)."""
    b = Blob(resolution=0.004)
    b.ell((-0.015, 0, 1.1), (0.094, 0.082, 0.088))
    for s in (1, -1):
        b.ell((-0.01, s * 0.088, 1.06), (0.026, 0.02, 0.034), stiffness=4, negative=True)  # room for the ears
    b.ell((0.068, 0, 1.05), (0.052, 0.085, 0.066), stiffness=4, negative=True)  # clear of the face
    b.ell((-0.03, 0, 0.98), (0.08, 0.09, 0.05), stiffness=4, negative=True)  # nape
    return b


def gi_blob():
    """The kimono top: a lean chest and narrow waist, the robe's fullness at the back."""
    b = Blob(resolution=0.006)
    b.ell((0.0, 0, 0.775), (0.095, 0.14, 0.11))  # chest
    b.ell((0.005, 0, 0.64), (0.09, 0.122, 0.11))  # waist
    for s in (1, -1):
        b.ell((-0.005, s * 0.09, 0.845), (0.055, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.15, 0.83), (0.052, 0.045, 0.045))  # shoulder seam
        b.ell((-0.055, s * 0.06, 0.77), (0.04, 0.06, 0.07))  # shoulder blades
    return b


def sleeve_blob(s):
    """A wide kimono sleeve: full all the way to the wrist, with its pouch hanging
    behind the forearm (under it when the arm is raised)."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.005)
    b.ell((0.0, y - s * 0.005, 0.825), (0.056, 0.056, 0.06))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, 0.64), 0.052)
    b.cap((0, y, 0.64), (0, y, WRIST[1] + 0.03), 0.054)
    b.ell((-0.045, y, 0.58), (0.05, 0.045, 0.1), stiffness=3)  # the hanging pouch
    return b


def hakama_blob(s):
    """One leg of the hakama: wide, flaring toward the hem, with half the seat."""
    y = s * HIP[0]
    b = Blob(resolution=0.006)
    b.ell((-0.02, s * 0.05, 0.53), (0.1, 0.075, 0.08))  # seat and hip
    # Overlapping capsules, each a little wider and lower: straight sides flaring to the hem.
    for top, bottom, r in ((HIP[1] - 0.04, 0.34, 0.07), (0.4, 0.24, 0.076), (0.3, 0.16, 0.084), (0.22, 0.1, 0.092)):
        b.cap((0, y + s * 0.05 * (0.5 - top), top), (0, y + s * 0.05 * (0.5 - bottom), bottom), r)
    b.ell((0.0, y, -0.04), (0.3, 0.3, 0.1), stiffness=4, negative=True)  # flat hem
    return b


def tabi_blob(s):
    """Split-toe sock: the big toe apart from the rest."""
    y = s * HIP[0]
    b = Blob(resolution=0.004)
    b.ell((0.035, y, 0.04), (0.085, 0.038, 0.035), stiffness=3)
    b.ell((0.11, y + s * 0.012, 0.03), (0.04, 0.026, 0.024), stiffness=3)  # toes
    b.ell((0.115, y - s * 0.022, 0.03), (0.038, 0.016, 0.024), stiffness=3)  # big toe
    b.ell((-0.025, y, 0.045), (0.04, 0.036, 0.042), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.13), 0.036)  # ankle, up into the hakama
    b.ell((0.05, y, -0.088), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat sole
    return b


def samurai_mesh():
    m = Model()
    m.blob("head", head_blob(), 0.5, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    gi = m.blob("gi", gi_blob(), 0.25, "Gi", by_distance("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        m.blob(f"sleeve.{side}", sleeve_blob(s), 0.25, "Gi", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", chef.hand_blob(s), 0.3, "Skin", f"forearm.{side}")
        m.blob(f"leg.{side}", hakama_blob(s), 0.25, "Hakama", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6))
        m.blob(f"tabi.{side}", tabi_blob(s), 0.3, "Tabi", f"foot.{side}")
        sandal(m, s, f"foot.{side}")
    face(m)
    topknot_and_headband(m)
    collar(m, m.weights_near(gi))
    obi(m)
    scabbard(m)
    katana(m)

    mesh = bpy.data.meshes.new("SamuraiMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    return mesh


def face(m):
    def on_skin(y, z, lift):
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    for s in (1, -1):
        socket = on_skin(s * 0.031, 1.072, 0)
        eye = socket - Vector((0.012 - 0.004, 0, 0))
        m.part(uv_ellipsoid(m.bm, eye, (0.012,) * 3, segments=(16, 10)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.011, 0, -0.001)), (0.0024, 0.007, 0.007), segments=(14, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.013, 0, -0.001)), (0.0012, 0.0034, 0.0034), segments=(10, 6)), "head", "Pupil")
        # Narrowed: the upper lid comes down to the pupil, the lower one up a little.
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0005, 0, 0.0035)), (0.0128, 0.0138, 0.0098), segments=(16, 10)), "head", "Skin")
        m.part(uv_ellipsoid(m.bm, eye + Vector((-0.001, 0, -0.0105)), (0.0128, 0.0136, 0.006), segments=(16, 8)), "head", "Skin")
        # Brows drawn down toward the nose: a scowl.
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.01, 1.09), (0.03, 1.099), (0.052, 1.104))]
        m.part(tube(m.bm, brow, [0.0055, 0.006, 0.0035], sides=8), "head", "Hair")
        # A thin mustache drooping past the corners of the mouth.
        stache = [on_skin(s * y, z, 0.002) for y, z in ((0.002, 1.022), (0.016, 1.018), (0.027, 1.008), (0.031, 0.99))]
        stache.append(stache[-1] + Vector((-0.004, s * 0.002, -0.016)))
        m.part(tube(m.bm, stache, [0.0035, 0.004, 0.0035, 0.003, 0.0018], sides=8), "head", "Hair")
    # A short pointed beard under the lip.
    beard = [on_skin(0, z, 0.002) for z in (0.988, 0.972, 0.958)]
    beard.append(beard[-1] + Vector((0.004, 0, -0.018)))
    m.part(tube(m.bm, beard, [0.006, 0.0075, 0.006, 0.002], sides=8), "head", "Hair")
    m.part(uv_ellipsoid(m.bm, on_skin(0, 1.0085, -0.003), (0.008, 0.017, 0.0045), segments=(14, 8)), "head", "Lip")


def topknot_and_headband(m):
    """The topknot folded forward over the crown, its tie, and the headband (`Body`)
    knotted at the back with its tails hanging behind."""
    top = m.hit("hair", (-0.02, 0, 1.5), (0, 0, -1))[0]
    knot = [top + Vector(d) for d in ((-0.03, 0, -0.005), (-0.028, 0, 0.022), (-0.01, 0, 0.034), (0.02, 0, 0.032), (0.045, 0, 0.022))]
    m.part(tube(m.bm, knot, [0.017, 0.016, 0.014, 0.012, 0.009], sides=12), "head", "Hair")
    m.part(tube(m.bm, [knot[1] + Vector((-0.005, 0, -0.002)), knot[1] + Vector((0.005, 0, 0.002))], [0.0172, 0.0172], sides=12), "head", "Collar")

    center = lambda z: Vector((-0.012, 0, z))  # noqa: E731
    fit = [m.fit(("head", "hair"), center(1.115), 2 * math.pi * j / 48) + 0.004 for j in range(48)]
    band = ring_band(m.bm, center, lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48], 1.1, 1.13, rows=2, sides=48)
    m.part(band, "head", "Body")
    back = center(1.115) + Vector((-fit[24] - 0.006, 0, 0))
    m.part(uv_ellipsoid(m.bm, back, (0.012, 0.016, 0.014)), "head", "Body")
    for s in (1, -1):
        tail = [back + Vector(d) for d in ((-0.004, s * 0.006, -0.004), (-0.02, s * 0.014, -0.03), (-0.03, s * 0.018, -0.07), (-0.034, s * 0.016, -0.1))]
        verts = tube(m.bm, tail, [0.009, 0.011, 0.011, 0.009], sides=8)
        for v in verts:  # flatten into cloth, edge on to the side
            v.co.y = tail[1].y + (v.co.y - tail[1].y) * 0.35
        m.part(verts, "head", "Body")


def collar(m, on_gi):
    """The kimono's crossed collar, left over right, with the white under-collar
    showing at the neck."""
    for s, depth in ((1, 0.006), (-1, 0.003)):
        line = []
        for i in range(10):
            t = i / 9
            y = s * (0.062 - 0.1 * t)  # from the side of the neck, across to the other side
            z = 0.885 - 0.23 * t
            loc, normal = m.hit("gi", (0.5, y, z), (-1, 0, 0))
            line.append(loc + normal * depth)
        verts = tube(m.bm, line, [0.012] * len(line), sides=8)
        m.weigh(verts, on_gi)
        m.paint(verts, "Collar" if s == -1 else "Gi")
        inner = tube(m.bm, [p + Vector((-0.002, -s * 0.008, 0.004)) for p in line[:5]], [0.008] * 5, sides=8)
        m.weigh(inner, on_gi)
        m.paint(inner, "Collar")
    ring = ring_band(m.bm, lambda z: Vector((-0.008, 0, z)), lambda a, z: 0.06 - 0.25 * (z - 0.86), 0.85, 0.89, rows=2, sides=32)
    m.part(ring, "spine", "Collar")


def obi(m):
    """The sash (`Body`) wrapped high on the hakama, tied in a flat knot at the front."""
    axis = Vector((0.005, 0, 0))
    fit = [m.fit(("gi", "leg.L", "leg.R"), axis + Vector((0, 0, 0.585)), 2 * math.pi * j / 48) + 0.006 for j in range(48)]
    band = ring_band(m.bm, lambda z: axis + Vector((0, 0, z)), lambda a, z: fit[round(a / (2 * math.pi) * 48) % 48], 0.55, 0.62, rows=2, sides=48)
    m.part(band, "hips", "Body")
    front = axis + Vector((fit[0] + 0.004, 0, 0.585))
    m.part(uv_ellipsoid(m.bm, front, (0.012, 0.03, 0.022)), "hips", "Body")


def sandal(m, s, bone):
    """A straw sandal under the tabi, with its dark thong."""
    y = s * HIP[0]
    bm = m.bm
    sole = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((0.045, y, 0.006)) @ Matrix.Diagonal((0.23, 0.085, 0.012, 1)))["verts"]
    m.part(sole, bone, "Straw", smooth=False)
    toe = Vector((0.13, y - s * 0.01, 0.03))
    for side in (1, -1):
        strap = [toe + Vector((-0.005, 0, 0.012)), Vector((0.06, y + side * 0.04, 0.05)), Vector((0.03, y + side * 0.045, 0.02))]
        m.part(tube(bm, strap, [0.005, 0.006, 0.005], sides=6), bone, "Hakama")


def scabbard(m):
    """The empty scabbard through the obi on the far (left) hip, its mouth forward and
    up, sloping down behind."""
    mouth, end = Vector((0.12, 0.13, 0.6)), Vector((-0.5, 0.17, 0.33))
    axis = (end - mouth).normalized()
    points = [mouth + axis * (end - mouth).length * t for t in (0, 0.02, 0.5, 0.97, 1.0)]
    m.part(tube(m.bm, points, [0.019, 0.02, 0.019, 0.018, 0.012], sides=12), "hips", "Saya")
    m.part(tube(m.bm, [points[0] - axis * 0.004, points[1] + axis * 0.012], [0.022, 0.022], sides=12), "hips", "Gold")
    m.part(tube(m.bm, [end - axis * 0.03, end + axis * 0.004], [0.02, 0.014], sides=12), "hips", "Gold")


def katana(m):
    """The sword along +X from the grip: pommel, wrapped hilt, guard, collar and a
    curved blade, edge down, ending in a point."""
    bm = m.bm

    def at(x, z=0.0, y=0.0):
        return GRIP + Vector((x, y, z))

    def rod(x0, x1, r, mat, sides=14):
        m.part(tube(bm, [at(x0), at(x1)], [r, r], sides=sides), "katana", mat)

    rod(-0.125, -0.115, 0.016, "Gold")  # pommel cap
    rod(-0.116, TSUBA - 0.005, 0.0135, "Collar")  # ray skin under the wrap
    # The cord wrap: two opposite spirals, which leave white diamonds between them.
    for hand in (1, -1):
        turns, n = 6, 96
        spiral = [at(-0.112 + (TSUBA - 0.118) * i / n, 0.0148 * math.sin(hand * 2 * math.pi * turns * i / n),
                     0.0148 * math.cos(hand * 2 * math.pi * turns * i / n)) for i in range(n + 1)]
        m.part(tube(bm, spiral, [0.0038] * len(spiral), sides=6), "katana", "Wrap")
    tsuba = bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.032, radius2=0.032, depth=0.006,
                                  matrix=Matrix.Translation(at(TSUBA)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))["verts"]
    m.part(tsuba, "katana", "Iron")
    rod(TSUBA + 0.003, TSUBA + 0.02, 0.012, "Gold")  # habaki
    # The blade: a lens-shaped section (flat sides facing the camera and away), its
    # ridge toward the spine, curving up toward the point.
    base, steps, rings = TSUBA + 0.004, 28, []
    for i in range(steps + 1):
        t = i / steps
        x, bend = base + BLADE * t, 0.035 * t * t
        width, thick = 0.026 - 0.006 * t, 0.0065 - 0.0025 * t
        if i == steps:
            rings.append([bm.verts.new(at(x + 0.012, bend + width * 0.3))])
        else:
            # Spine, near ridge, edge, far ridge: (across, along the width) fractions.
            rings.append([bm.verts.new(at(x, bend + w * width, a * thick)) for a, w in ((0, 0.5), (-0.5, 0.15), (0, -0.5), (0.5, 0.15))])
    faces = []
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(4):
            quad = (r0[j], r0[(j + 1) % 4], r1[0]) if len(r1) == 1 else (r0[j], r0[(j + 1) % 4], r1[(j + 1) % 4], r1[j])
            faces.append((bm.faces.new(quad), j))
    faces.append((bm.faces.new(list(reversed(rings[0]))), 0))
    m.weigh([v for r in rings for v in r], "katana")
    for f, j in faces:  # the two faces either side of the edge are the polished hamon
        f.material_index = MAT["Edge" if j in (1, 2) else "Steel"]
        f.smooth = False


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
    rig = bpy.data.objects.new("Fighter", bpy.data.armatures.new("SamuraiRig"))
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

    body = bpy.data.objects.new("Samurai", mesh)
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
# plus "aim": where the blade points (see the module docstring).


def stance(drop=0.05, lean=-6, aim=35, front=0.14, back=-0.14):
    """One-handed guard: sword arm forward at the waist, blade angled up at the
    opponent, the free hand resting by the scabbard."""
    pose = guard(drop=drop, lean=lean, front=front, back=back)
    pose.update({"upper_arm.R": 34 - lean - 6, "forearm.R": 62, "upper_arm.L": 2 - lean, "forearm.L": 40, "aim": aim})
    return pose


def lunge(pose, fwd, drop, front, back=-0.2):
    """`pose` with the hips moved forward and down, feet re-planted wide."""
    return planted(with_(pose, hips_loc=(fwd, -drop)), front, back)


S = stance()
CROUCH = with_(crouch(0.16), upper_arm_R=20, forearm_R=70, aim=20)
AIR_S = with_(AIR, aim=45)
FLINCH_S = with_(FLINCH, aim=120)

# Ground cuts. The comment above each gives its sim frames (sim/src/moves.rs).
CUT_HIGH = with_(S, upper_arm_R=150, forearm_R=40, aim=125, spine=4)
CUT_LEVEL = lunge(with_(S, spine=-14, head=10, upper_arm_R=96, forearm_R=4, aim=8), 0.06, 0.06, 0.26)
CUT_LOW = with_(CUT_LEVEL, upper_arm_R=62, forearm_R=8, aim=-30)
BACKHAND_LOW = with_(S, upper_arm_R=40, forearm_R=30, aim=-50, upper_arm_L=-10)
BACKHAND = lunge(with_(S, spine=-10, head=8, upper_arm_R=92, forearm_R=6, aim=12), 0.05, 0.06, 0.24)
BACKHAND_HIGH = with_(BACKHAND, upper_arm_R=125, forearm_R=10, aim=65)
THRUST_BACK = lunge(with_(S, spine=4, upper_arm_R=-10, forearm_R=105, aim=2, upper_arm_L=50, forearm_L=60), -0.03, 0.08, 0.2)
THRUST = lunge(with_(S, spine=-22, head=16, upper_arm_R=100, forearm_R=0, aim=-4, upper_arm_L=-40, forearm_L=10), 0.16, 0.1, 0.45, -0.25)
FCUT_WIND = lunge(with_(S, spine=8, head=-6, upper_arm_R=135, forearm_R=70, aim=160, upper_arm_L=40, forearm_L=60), -0.03, 0.06, 0.18)
FCUT = lunge(with_(S, spine=-16, head=12, upper_arm_R=98, forearm_R=0, aim=6, upper_arm_L=-30, forearm_L=20), 0.09, 0.08, 0.34)
FCUT_THROUGH = with_(FCUT, upper_arm_R=66, aim=-35)
RISE_LOW = with_(crouch(0.1), upper_arm_R=36, forearm_R=20, aim=-25)
RISE_FRONT = with_(S, spine=-4, upper_arm_R=104, forearm_R=0, aim=30)
RISE_TOP = with_(S, hips_loc=(0, -0.01), spine=8, head=-10, upper_arm_R=176, forearm_R=0, aim=96)
RISE_BACK = with_(RISE_TOP, upper_arm_R=205, aim=135, spine=12)
KNEEL = planted(with_(crouch(0.24), spine=-26, head=22, upper_arm_R=30, forearm_R=40, aim=-150, upper_arm_L=40, forearm_L=60), 0.3, -0.24)
KNEEL_CUT = with_(KNEEL, upper_arm_R=82, forearm_R=0, aim=-8, upper_arm_L=-30)
KNEEL_THROUGH = with_(KNEEL_CUT, upper_arm_R=60, aim=-4)
DASH_TRAIL = planted(with_(guard(drop=0.07, lean=-30), hips_loc=(0.06, -0.07), upper_arm_R=-40, forearm_R=20, aim=-160, upper_arm_L=40, forearm_L=60), 0.2, -0.26)
DASH_CUT = planted(with_(guard(drop=0.08, lean=-24), hips_loc=(0.12, -0.08), upper_arm_R=110, forearm_R=0, aim=4, upper_arm_L=-40, forearm_L=20), 0.36, -0.26)

# Smash attacks: the pose on the charge frame is held while charging.
CLEAVE_WIND = lunge(with_(S, spine=12, head=-12, upper_arm_R=172, forearm_R=25, aim=160, upper_arm_L=165, forearm_L=30), -0.04, 0.05, 0.2)
CLEAVE_MID = with_(CLEAVE_WIND, upper_arm_R=150, forearm_R=10, aim=90, spine=0)
CLEAVE = lunge(with_(S, spine=-26, head=20, upper_arm_R=118, forearm_R=0, aim=6, upper_arm_L=112, forearm_L=8), 0.14, 0.12, 0.42, -0.24)
CLEAVE_DOWN = with_(CLEAVE, upper_arm_R=82, upper_arm_L=78, aim=-30)
SKY_LOW = with_(crouch(0.14), upper_arm_R=40, forearm_R=10, aim=-35)
SKY_FRONT = with_(S, upper_arm_R=104, forearm_R=0, aim=34, spine=0)
SKY_TOP = planted(with_(S, hips_loc=(0, 0.02), spine=6, head=-14, upper_arm_R=178, forearm_R=0, aim=94, upper_arm_L=-20), 0.08, -0.08)
SWEEP_WIND = planted(with_(crouch(0.2), spine=-10, upper_arm_R=-30, forearm_R=20, aim=175, upper_arm_L=40), 0.28, -0.28)
SWEEP_FRONT = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=94, forearm_R=0, aim=-10, upper_arm_L=-60), 0.36, -0.3)
SWEEP_BACK = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=-82, forearm_R=0, aim=190, upper_arm_L=60), 0.3, -0.36)

# Aerials
AIR_TUCK = with_(AIR_S, thigh_R=80, shin_R=-120, thigh_L=60, shin_L=-110)
SPIN_FRONT = with_(AIR_TUCK, spine=-10, upper_arm_R=115, forearm_R=0, aim=28)
SPIN_TOP = with_(AIR_TUCK, upper_arm_R=170, forearm_R=0, aim=110)
SPIN_BACK = with_(AIR_TUCK, spine=10, upper_arm_R=232, forearm_R=0, aim=200)
SPIN_LOW = with_(AIR_TUCK, spine=10, upper_arm_R=272, forearm_R=0, aim=232)
ACUT_HIGH = with_(AIR_S, spine=10, head=-6, upper_arm_R=172, forearm_R=20, aim=125)
ACUT_MID = with_(AIR_S, spine=-8, upper_arm_R=125, forearm_R=0, aim=55)
ACUT = with_(AIR_S, spine=-20, head=14, upper_arm_R=96, forearm_R=0, aim=2)
ACUT_LOW = with_(ACUT, upper_arm_R=60, aim=-52)
BCUT_WIND = with_(AIR_S, upper_arm_R=25, forearm_R=70, aim=70)
BCUT = with_(AIR_S, spine=-22, head=30, upper_arm_R=-78, forearm_R=0, aim=176, upper_arm_L=70, forearm_L=30,
             thigh_R=70, shin_R=-100, thigh_L=30, shin_L=-90)
BCUT_LOW = with_(BCUT, upper_arm_R=-58, aim=205)
ARC_FRONT = with_(AIR_S, upper_arm_R=105, forearm_R=0, aim=30)
ARC_UP = with_(AIR_S, spine=10, head=-18, upper_arm_R=160, forearm_R=0, aim=80)
ARC_TOP = with_(AIR_S, spine=18, head=-22, upper_arm_R=188, forearm_R=0, aim=104)
ARC_BACK = with_(ARC_TOP, upper_arm_R=218, aim=140)
STAB_WIND = with_(AIR_S, spine=6, upper_arm_R=165, forearm_R=20, aim=95, thigh_R=90, shin_R=-130, thigh_L=80, shin_L=-120)
STAB = with_(AIR_S, spine=-8, head=8, upper_arm_R=22, forearm_R=0, aim=-88, upper_arm_L=-30,
             thigh_R=60, shin_R=-20, foot_R=-30, thigh_L=-30, shin_L=-30, foot_L=-30)

# Specials
DRAW_WIND = lunge(with_(crouch(0.12), spine=-6, upper_arm_R=14, forearm_R=96, aim=188, upper_arm_L=10, forearm_L=70), -0.02, 0.12, 0.24)
DRAW_CUT = lunge(with_(S, spine=-18, head=14, upper_arm_R=100, forearm_R=0, aim=8, upper_arm_L=-40, forearm_L=10), 0.1, 0.1, 0.38)
DRAW_FOLLOW = with_(DRAW_CUT, upper_arm_R=132, aim=50)
STRIKE_WIND = lunge(with_(crouch(0.18), spine=-14, upper_arm_R=-24, forearm_R=30, aim=-162, upper_arm_L=30, forearm_L=80), -0.02, 0.18, 0.26)
STRIKE = {
    "hips_loc": (0.08, 0.02),
    "hips": -30,
    "spine": -15,
    "head": 35,
    "upper_arm.R": 130,
    "forearm.R": 0,
    "upper_arm.L": -10,
    "forearm.L": 20,
    "thigh.R": 70,
    "shin.R": -60,
    "foot.R": 10,
    "thigh.L": -40,
    "shin.L": -30,
    "foot.L": 30,
    "aim": 2,
}
STRIKE_THROUGH = with_(STRIKE, hips=-10, spine=-10, head=15, upper_arm_R=60, aim=-40)
STRIKE_SHEATHE = lunge(with_(S, spine=-8, upper_arm_R=-40, forearm_R=0, aim=-170, upper_arm_L=30, forearm_L=70), 0.06, 0.12, 0.34)
DRAGON_LOW = with_(crouch(0.14), upper_arm_R=30, forearm_R=10, aim=-30)
DRAGON = {
    "hips_loc": (0, 0.05),
    "spine": 6,
    "head": -12,
    "upper_arm.R": 176,
    "forearm.R": 0,
    "upper_arm.L": -20,
    "forearm.L": 50,
    "thigh.R": 85,
    "shin.R": -110,
    "thigh.L": -10,
    "shin.L": -15,
    "foot.L": -30,
    "aim": 92,
}
DRAGON_RISING = with_(DRAGON, upper_arm_R=104, aim=30)
HELPLESS = with_(AIR_S, spine=10, head=-10, upper_arm_R=150, forearm_R=30, upper_arm_L=140, forearm_L=40, aim=150,
                 thigh_R=20, shin_R=-40, thigh_L=5, shin_L=-30)
PARRY = with_(S, hips_loc=(-0.02, -0.07), spine=4, head=-4, upper_arm_R=48, forearm_R=96, aim=96, upper_arm_L=56, forearm_L=92)
PARRY = planted(PARRY, 0.16, -0.18)
RIPOSTE_HIGH = with_(PARRY, upper_arm_R=150, forearm_R=20, aim=130)
RIPOSTE = lunge(with_(S, spine=-20, head=16, upper_arm_R=104, forearm_R=0, aim=8, upper_arm_L=-36, forearm_L=20), 0.12, 0.1, 0.4)
RIPOSTE_THROUGH = with_(RIPOSTE, upper_arm_R=70, aim=-30)

# Grabs and throws: the free (left) hand does the grabbing; the sword stays back.
REACH = lunge(with_(S, spine=-14, head=10, upper_arm_L=88, forearm_L=6, upper_arm_R=-6, forearm_R=40, aim=-140), 0.06, 0.06, 0.26)
DASH_REACH = planted(with_(guard(drop=0.08, lean=-26), hips_loc=(0.1, -0.08), upper_arm_L=96, forearm_L=4, upper_arm_R=-30, forearm_R=20, aim=-160), 0.32, -0.26)
HOLD = with_(S, spine=-6, upper_arm_L=72, forearm_L=40, upper_arm_R=10, forearm_R=40, aim=-120)
HILT_BASH = with_(HOLD, spine=-14, head=10, upper_arm_R=88, forearm_R=20, aim=176)
HIP_PULL = lunge(with_(HOLD, spine=10, upper_arm_L=40, forearm_L=90), -0.04, 0.12, 0.18)
HIP_THROW = lunge(with_(HOLD, spine=-26, head=18, upper_arm_L=100, forearm_L=0, upper_arm_R=60, forearm_R=20, aim=-20), 0.1, 0.12, 0.36)
SHOULDER_LOAD = lunge(with_(HOLD, spine=-16, upper_arm_L=168, forearm_L=30), 0.02, 0.18, 0.2)
SHOULDER_THROW = lunge(with_(HOLD, spine=18, head=-10, upper_arm_L=232, forearm_L=0, upper_arm_R=-30, aim=-150), -0.04, 0.08, 0.16, -0.3)
TOSS_LOW = with_(crouch(0.14), upper_arm_L=60, forearm_L=60, upper_arm_R=10, forearm_R=40, aim=-120)
TOSS = planted(with_(HOLD, hips_loc=(0, 0.01), spine=8, head=-14, upper_arm_L=178, forearm_L=0), 0.08, -0.08)
KNEE_UP = with_(HOLD, spine=-10, thigh_R=88, shin_R=-100, foot_R=-10)
PIN = planted(with_(crouch(0.26), spine=-30, head=20, upper_arm_L=60, forearm_L=10, upper_arm_R=60, forearm_R=20, aim=176), 0.3, -0.22)
STRUGGLE = with_(S, spine=15, head=10, upper_arm_R=40, forearm_R=70, upper_arm_L=-30, forearm_L=100, aim=60)

# Shield and dodges
SHIELD = with_(stance(drop=0.07, lean=-4), upper_arm_R=46, forearm_R=96, aim=96, upper_arm_L=50, forearm_L=100)
DIZZY = with_(S, spine=(-15, 0, 10), head=(-20, 0, 15), upper_arm_R=-5, forearm_R=10, upper_arm_L=-5, forearm_L=10, aim=-60)
SIDESTEP = with_(crouch(0.08), spine=-10, head=10, upper_arm_R=10, forearm_R=40, aim=-130)
BALL = with_(crouch(0.3), spine=-60, head=40, upper_arm_R=60, forearm_R=130, upper_arm_L=60, forearm_L=130, aim=-100)
AIRDODGE = with_(AIR_S, spine=-10, upper_arm_R=60, forearm_R=120, upper_arm_L=55, forearm_L=125, thigh_R=70, shin_R=-120, thigh_L=60, shin_L=-110, aim=-120)


def walk(stride, lift, drop, swing, phase, run):
    """A walk/run key with the sword held still: forward on a walk, trailing low
    behind on a run."""
    pose = walk_key(stride, lift, drop, swing, phase)
    if run:
        return with_(pose, upper_arm_R=-34, forearm_R=24, aim=-158)
    return with_(pose, upper_arm_R=34, forearm_R=56, aim=30)


ANIMATIONS = {
    "idle": cycle(60, [S, with_(stance(drop=0.056), upper_arm_R=35, aim=33)]),
    "walk": cycle(40, [walk(0.12, 0.06, d, 22, i, False) for i, d in enumerate((0.04, 0.025, 0.04, 0.025))]),
    "run": cycle(24, [walk(0.2, 0.12, d, 45, i, True) for i, d in enumerate((0.06, 0.03, 0.06, 0.03))]),
    # JumpSquat lasts FighterParams::jump_squat (4) frames.
    "jumpsquat": [(1, stance(drop=0.07, lean=-12)), (4, CROUCH)],
    "air": cycle(40, [AIR_S, with_(AIR_S, thigh_R=60, shin_R=-100, thigh_L=10, upper_arm_R=50, aim=40)]),
    # Played backwards from the end as Landing counts down, so it always finishes on guard.
    "land": [(1, CROUCH), (5, S)],
    "crouch": cycle(60, [CROUCH, with_(CROUCH, hips_loc=(0, -0.165), aim=18)]),
    "hitstun": cycle(20, [FLINCH_S, with_(FLINCH_S, spine=26, upper_arm_R=78, upper_arm_L=-58, aim=130)]),
    "shield": cycle(40, [SHIELD, with_(SHIELD, upper_arm_R=48, aim=95)]),
    "dizzy": cycle(60, [DIZZY, with_(DIZZY, spine=(-15, 0, -10), head=(-20, 0, -15))]),
    "specialfall": cycle(30, [HELPLESS, with_(HELPLESS, upper_arm_R=165, upper_arm_L=125, aim=160)]),
    "grab_hold": cycle(40, [HOLD, with_(HOLD, upper_arm_L=75, spine=-8)]),
    "grabbed": cycle(16, [STRUGGLE, with_(STRUGGLE, spine=20, head=15, upper_arm_R=60, forearm_R=60, upper_arm_L=-10, aim=80)]),
    # Slash: 20 frames, hit 4-5. Slash2: 20, hit 4-5. Thrust: 32, hit 5-7.
    "slash": [(1, S), (3, CUT_HIGH), (4, CUT_LEVEL), (6, CUT_LOW), (12, CUT_LOW), (20, S)],
    "slash2": [(1, CUT_LOW), (3, BACKHAND_LOW), (4, BACKHAND), (5, with_(BACKHAND, upper_arm_R=100, aim=25)), (7, BACKHAND_HIGH), (12, BACKHAND_HIGH), (20, S)],
    "thrust": [(1, BACKHAND_HIGH), (3, THRUST_BACK), (5, THRUST), (11, THRUST), (20, with_(THRUST, upper_arm_R=80, aim=10)), (32, S)],
    # Forward cut: 30 frames, hit 7-9 (the tip at x 13).
    "forward_cut": [(1, S), (5, FCUT_WIND), (7, FCUT), (9, FCUT_THROUGH), (18, FCUT_THROUGH), (30, S)],
    # Rising cut: 30 frames, in front 6-8, overhead 9-12.
    "rising_cut": [(1, S), (4, RISE_LOW), (6, RISE_FRONT), (9, RISE_TOP), (12, RISE_BACK), (20, with_(RISE_TOP, upper_arm_R=150, aim=110)), (30, S)],
    # Low cut: 24 frames, hit 6-8 along the floor. Starts and ends crouched.
    "low_cut": [(1, CROUCH), (4, KNEEL), (6, KNEEL_CUT), (9, KNEEL_THROUGH), (15, KNEEL_THROUGH), (24, CROUCH)],
    # Dash cut: 40 frames, hit 7-11.
    "dash_cut": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (5, DASH_TRAIL), (7, DASH_CUT), (11, with_(DASH_CUT, upper_arm_R=80, aim=-30)), (26, with_(S, spine=-14)), (40, S)],
    # Cleave: charge frame 12, hit 17-19. Sky cut: charge 8, hit 11-16. Spin sweep: charge 6, front 10-11, back 16-17.
    "cleave": [(1, S), (8, CLEAVE_WIND), (12, CLEAVE_WIND), (16, CLEAVE_MID), (17, CLEAVE), (20, CLEAVE_DOWN), (36, CLEAVE_DOWN), (56, S)],
    "sky_cut": [(1, S), (5, SKY_LOW), (8, SKY_LOW), (11, SKY_FRONT), (12, with_(SKY_TOP, upper_arm_R=160, aim=82)), (16, SKY_TOP), (28, with_(SKY_TOP, upper_arm_R=150, aim=110)), (48, S)],
    "spin_sweep": [(1, S), (4, SWEEP_WIND), (6, SWEEP_WIND), (10, SWEEP_FRONT), (12, SWEEP_FRONT), (14, with_(SWEEP_FRONT, upper_arm_R=20, aim=-90)), (16, SWEEP_BACK), (19, SWEEP_BACK), (32, CROUCH), (50, S)],
    # Air spin: 38 frames, in front 5-8, behind 9-12. Air cut: hit 6-10. Back cut: 8-11.
    # Sky arc: 5-10. Plunge stab: 12-16.
    "air_spin": [(1, AIR_S), (3, with_(AIR_TUCK, upper_arm_R=60, aim=0)), (5, SPIN_FRONT), (8, with_(SPIN_FRONT, upper_arm_R=150, aim=75)), (9, SPIN_BACK), (12, SPIN_LOW), (22, with_(AIR_TUCK, upper_arm_R=290, aim=250)), (32, with_(AIR_S, upper_arm_R=380, aim=400)), (38, with_(AIR_S, upper_arm_R=405, aim=405))],
    "air_cut": [(1, AIR_S), (4, ACUT_HIGH), (5, ACUT_MID), (7, ACUT), (10, ACUT_LOW), (22, ACUT_LOW), (36, AIR_S)],
    "back_cut": [(1, AIR_S), (5, BCUT_WIND), (8, BCUT), (11, BCUT_LOW), (24, BCUT_LOW), (38, AIR_S)],
    "sky_arc": [(1, AIR_S), (3, ARC_FRONT), (5, ARC_UP), (8, ARC_TOP), (10, ARC_BACK), (20, ARC_BACK), (36, AIR_S)],
    "plunge_stab": [(1, AIR_S), (8, STAB_WIND), (11, with_(STAB, upper_arm_R=90, aim=-40)), (12, STAB), (30, STAB), (46, AIR_S)],
    # Specials. Wind slash: charge frame 10, the blade of wind leaves on 14.
    "wind_slash": [(1, S), (6, DRAW_WIND), (10, DRAW_WIND), (13, with_(DRAW_CUT, upper_arm_R=60, aim=-20)), (14, DRAW_CUT), (18, DRAW_FOLLOW), (28, DRAW_FOLLOW), (40, S)],
    # Dash strike: still on 1-8, dashes 9-16, hit 10-16.
    "dash_strike": [(1, S), (5, STRIKE_WIND), (8, STRIKE_WIND), (9, STRIKE), (13, STRIKE), (16, STRIKE_THROUGH), (24, STRIKE_SHEATHE), (34, STRIKE_SHEATHE), (46, S)],
    # Rising dragon: rises 4-20, hit 4-7 then 8-18, then helpless.
    "rising_dragon": [(1, S), (3, DRAGON_LOW), (4, DRAGON_RISING), (7, DRAGON), (18, DRAGON), (28, with_(DRAGON, upper_arm_R=150, aim=130, thigh_R=50)), (46, HELPLESS)],
    # Parry: counters hits on 5-24. Riposte: 32 frames, hit 4-7.
    "parry": [(1, S), (4, PARRY), (24, PARRY), (34, with_(PARRY, upper_arm_R=40, aim=80)), (46, S)],
    "riposte": [(1, PARRY), (3, RIPOSTE_HIGH), (4, RIPOSTE), (7, RIPOSTE_THROUGH), (16, RIPOSTE_THROUGH), (32, S)],
    # Grab: 30 frames, grab box 7-8. Dash grab: 40, 9-10. Pummel (a hilt bash) hits on 3.
    "grab": [(1, S), (6, REACH), (9, REACH), (18, HOLD), (30, S)],
    "dashgrab": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (8, DASH_REACH), (11, DASH_REACH), (25, with_(HOLD, spine=-12)), (40, S)],
    "pummel": [(1, HOLD), (3, HILT_BASH), (6, HILT_BASH), (16, HOLD)],
    # Throws release on 13 (hip), 16 (shoulder), 12 (toss), 15 (pin).
    "hip_throw": [(1, HOLD), (8, HIP_PULL), (13, HIP_THROW), (19, HIP_THROW), (32, S)],
    "shoulder_throw": [(1, HOLD), (9, SHOULDER_LOAD), (16, SHOULDER_THROW), (22, SHOULDER_THROW), (38, S)],
    "toss_up": [(1, HOLD), (6, TOSS_LOW), (12, TOSS), (18, TOSS), (34, S)],
    "pin": [(1, HOLD), (7, KNEE_UP), (12, PIN), (15, PIN), (22, with_(PIN, upper_arm_R=100, aim=100)), (34, S)],
    # Dodges: spot 26 frames (invincible 3-17), rolls 32 (4-15), air dodge 34-40 (3-18 / 3-25).
    "spotdodge": [(1, S), (3, SIDESTEP), (17, SIDESTEP), (26, S)],
    "roll_f": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "roll_b": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "airdodge": [(1, AIR_S), (4, AIRDODGE), (25, AIRDODGE), (34, AIR_S), (40, AIR_S)],
}


def pitch(value):
    return value[0] if isinstance(value, tuple) else value


def apply_pose(rig, pose):
    # The katana's own angle is whatever is left of `aim` after the arm's chain.
    chain = sum(pitch(pose.get(b, 0)) for b in ("hips", "spine", "upper_arm.R", "forearm.R"))
    angles = dict(pose, katana=pose.get("aim", 35) - chain)
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


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    rig = build_rig(samurai_mesh())
    build_actions(rig)
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)


if __name__ == "__main__":
    main()
