"""Builds the ninja: the lightest, fastest fighter, a lean figure in a dark shinobi
shozoku (a wrap-front jacket with crossed lapels, baggy trousers bloused into shin
wraps, split-toe tabi), a face mask draped over nose and chin, a headband, forearm
wraps and hand guards over open knife-hands, and a shuriken pouch. Then his armature
and one action per pose name the sim reports (`Fighter::anim()`), including the four
ledge clips. Saves `ninja.blend` next to this script, the generated textures in
`textures/`, and exports `godot/models/ninja.glb`.

    blender --background --factory-startup --python art/ninja/build_ninja.py

He stands on the chef's skeleton (same joints, 1.2 m), so the shapes, pose helpers
and conventions come from `art/fighter/build_fighter.py` (see its README). Unlike the
samurai there is no extra bone: his shuriken is drawn as a projectile orb, and his
specials are a shadow dash, a smoke bomb and a substitution counter, so the hands
stay free. The headband and the obi are the `Body` material that the game recolors
per player.

Everything is generated from code and seeded, so a rebuild gives the same file.
"""

import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "ninja.blend")
TEX_DIR = os.path.join(HERE, "textures")
GLB_PATH = os.path.join(ROOT, "godot", "models", "ninja.glb")

sys.path.insert(0, os.path.join(ROOT, "art", "fighter"))
import build_fighter as chef  # noqa: E402
from build_fighter import (  # noqa: E402
    AIR,
    ANKLE,
    ELBOW,
    FLINCH,
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
H = 1.1  # FighterParams::NINJA.height (11 sim units): where his hands hang on a ledge
TILE = 0.1  # meters of surface per repeat of the tiling textures
TEX_SIZE = 256

# The chef's bones, minus the pie (the ninja throws shuriken drawn as a projectile,
# so he carries nothing in his hands).
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONE_NAMES = [b[0] for b in BONES]
UPPER_ARM, FOREARM = SHOULDER[1] - ELBOW[1], ELBOW[1] - WRIST[1]

# Material name -> settings. Godot replaces "Body" (the headband and the obi) with the
# player's color; the rest keep their own. `color` is sRGB (converted to linear for
# Blender/glTF); `rough`/`metal` are Principled BSDF values; `spec` is "Specular IOR
# Level" (0 = fully diffuse cloth, ~0.35 = skin, ~1.6 = a wet eyeball); `normal`
# picks one of the generated tiling normal maps below and `bump` its strength;
# `albedo` bakes a tiling color texture (fading, weave, blotches) from `color`; `sss`
# adds subsurface scattering in Blender (glTF has no such channel, so it doesn't reach
# the game).
MATERIALS = {
    "Body": dict(color=(0.62, 0.1, 0.1), rough=0.8, metal=0.0, spec=0.2, normal="cloth"),
    "Gi": dict(color=(0.085, 0.09, 0.125), rough=0.88, metal=0.0, spec=0.25, normal="cloth", bump=1.0, albedo="cloth"),
    "Wrap": dict(color=(0.15, 0.15, 0.165), rough=0.9, metal=0.0, spec=0.2, normal="cloth", bump=1.0, albedo="cloth"),
    "Skin": dict(color=(0.78, 0.58, 0.44), rough=0.5, metal=0.0, spec=0.35, normal="skin", bump=0.22, albedo="skin",
                 sss=0.25, sss_radius=(1.0, 0.35, 0.2), sss_scale=0.02),
    "Hair": dict(color=(0.03, 0.026, 0.024), rough=0.45, metal=0.0, spec=0.5, normal="hair", bump=0.8),
    "Eye": dict(color=(0.86, 0.84, 0.8), rough=0.08, metal=0.0, spec=1.6),
    "Iris": dict(color=(0.2, 0.11, 0.06), rough=0.15, metal=0.0, spec=1.2),
    "Pupil": dict(color=(0.01, 0.01, 0.01), rough=0.08, metal=0.0, spec=1.2),
    "Steel": dict(color=(0.6, 0.61, 0.63), rough=0.3, metal=1.0, spec=1.0, normal="steel", bump=0.6),
    "Leather": dict(color=(0.16, 0.1, 0.07), rough=0.6, metal=0.0, spec=0.4, normal="leather", bump=0.8),
    "Sole": dict(color=(0.07, 0.07, 0.075), rough=0.85, metal=0.0, spec=0.2, normal="leather", bump=0.6),
}
MAT = {name: i for i, name in enumerate(MATERIALS)}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# --- Noise -------------------------------------------------------------------
# Integer-hashed value noise: deterministic, no Python `random`. `tile_noise` repeats
# on its lattice (so the textures tile seamlessly); `noise3` is 3D, for shaping cloth.


def _hash(seed, *ix):
    n = seed * 0x9E3779B1
    for k, v in zip((0x27D4EB2D, 0x165667B1, 0x1B873593), ix):
        n += v * k
    n &= 0xFFFFFFFF
    n = ((n ^ (n >> 15)) * 0x85EBCA6B) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFFFF) / 0xFFFFFFFF * 2.0 - 1.0


def _fade(t):
    return t * t * (3 - 2 * t)


def tile_noise(x, y, px, py, seed):
    """Value noise in [-1, 1] on an integer lattice repeating every (px, py) cells."""
    x0, y0 = math.floor(x), math.floor(y)
    sx, sy = _fade(x - x0), _fade(y - y0)

    def h(i, j):
        return _hash(seed, i % px, j % py)

    a = h(x0, y0) + (h(x0 + 1, y0) - h(x0, y0)) * sx
    b = h(x0, y0 + 1) + (h(x0 + 1, y0 + 1) - h(x0, y0 + 1)) * sx
    return a + (b - a) * sy


def noise3(p, seed):
    """Smooth 3D value noise in [-1, 1]."""
    x, y, z = p
    x0, y0, z0 = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = _fade(x - x0), _fade(y - y0), _fade(z - z0)
    c = [[[_hash(seed, x0 + i, y0 + j, z0 + k) for k in (0, 1)] for j in (0, 1)] for i in (0, 1)]
    x00 = c[0][0][0] + (c[1][0][0] - c[0][0][0]) * fx
    x10 = c[0][1][0] + (c[1][1][0] - c[0][1][0]) * fx
    x01 = c[0][0][1] + (c[1][0][1] - c[0][0][1]) * fx
    x11 = c[0][1][1] + (c[1][1][1] - c[0][1][1]) * fx
    y0_ = x00 + (x10 - x00) * fy
    y1_ = x01 + (x11 - x01) * fy
    return y0_ + (y1_ - y0_) * fz


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# --- Generated textures --------------------------------------------------------
# Small tiling maps, built at build time and embedded in the .glb (Godot extracts them
# next to the model on import): height fields turned into tangent-space normal maps,
# and color variation baked into albedo maps. With TILE = 0.1 m per repeat, one pixel
# is about 0.4 mm of surface, so the cloth weave repeats every ~3 mm.


def _cloth(i, j):
    """A plain weave (threads over and under) with slubs and soft broad creases."""
    weave = math.sin(2 * math.pi * i / 8) * math.sin(2 * math.pi * j / 8)
    slub = tile_noise(i / 4, j / 32, 64, 8, 3)
    crease = tile_noise(i / 32, j / 32, 8, 8, 7) + 0.5 * tile_noise(i / 16, j / 16, 16, 16, 8)
    return 0.6 * weave + 0.3 * slub + 1.6 * crease


def _pores(i, j):
    """Fine skin pores over a slightly coarser grain."""
    return tile_noise(i / 2, j / 2, 128, 128, 11) + 0.6 * tile_noise(i / 8, j / 8, 32, 32, 12)


def _hair(i, j):
    """Strands: tight across, long along."""
    return tile_noise(i / 1.0, j / 16, 256, 16, 23) + 0.5 * tile_noise(i / 4, j / 32, 64, 8, 24)


def _steel(i, j):
    """Fine brushed lines plus faint pitting."""
    return 0.5 * tile_noise(i, j / 64, 256, 4, 31) + 0.3 * tile_noise(i / 4, j / 4, 64, 64, 32)


def _leather(i, j):
    """Pebbled grain with a few creases."""
    grain = 1 - abs(tile_noise(i / 4, j / 4, 64, 64, 41))
    return 0.8 * grain * grain + 1.2 * tile_noise(i / 32, j / 16, 8, 16, 42)


NORMAL_TEXTURES = {
    "cloth": (_cloth, 0.45),
    "skin": (_pores, 0.35),
    "hair": (_hair, 0.5),
    "steel": (_steel, 0.4),
    "leather": (_leather, 0.4),
}


def _cloth_tone(i, j):
    """Faded, slightly uneven dye; the thread crossings catch a little more light."""
    fade = 0.6 * tile_noise(i / 32, j / 32, 8, 8, 51) + 0.25 * tile_noise(i / 8, j / 8, 32, 32, 52)
    thread = math.sin(2 * math.pi * i / 8) * math.sin(2 * math.pi * j / 8)
    return (1 + 0.14 * fade + 0.05 * thread,) * 3


def _skin_tone(i, j):
    """Faint blotches: a little redder in places, a little sallower in others."""
    blotch = tile_noise(i / 16, j / 16, 16, 16, 61)
    fine = tile_noise(i / 4, j / 4, 64, 64, 62)
    v = 1 + 0.04 * fine
    return (v * (1 + 0.035 * blotch), v * (1 - 0.02 * blotch), v * (1 - 0.03 * blotch))


ALBEDO_TEXTURES = {"cloth": _cloth_tone, "skin": _skin_tone}
_IMAGES = {}


def _save(img, filename):
    os.makedirs(TEX_DIR, exist_ok=True)
    img.filepath_raw = os.path.join(TEX_DIR, filename)
    img.file_format = "PNG"
    img.save()


def normal_image(key):
    """The tiling normal map for `key` (cached), saved as `textures/<key>_normal.png`."""
    name = f"ninja_{key}_normal"
    if name in _IMAGES:
        return _IMAGES[name]
    height, gain = NORMAL_TEXTURES[key]
    n = TEX_SIZE
    h = [[height(i, j) for i in range(n)] for j in range(n)]
    px = [0.0] * (n * n * 4)
    idx = 0
    for j in range(n):
        jm, jp = (j - 1) % n, (j + 1) % n
        for i in range(n):
            dx = (h[j][(i + 1) % n] - h[j][(i - 1) % n]) * gain
            dy = (h[jp][i] - h[jm][i]) * gain
            inv = 1.0 / math.sqrt(dx * dx + dy * dy + 1.0)
            px[idx : idx + 4] = (-dx * inv * 0.5 + 0.5, -dy * inv * 0.5 + 0.5, inv * 0.5 + 0.5, 1.0)
            idx += 4
    img = bpy.data.images.new(name, n, n, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(px)
    _save(img, f"{key}_normal.png")
    _IMAGES[name] = img
    return img


def albedo_image(mat_name, key, color):
    """A tiling sRGB color map: `color` modulated by `ALBEDO_TEXTURES[key]`."""
    name = f"ninja_{mat_name.lower()}_albedo"
    n = TEX_SIZE
    px = [0.0] * (n * n * 4)
    idx = 0
    tone = ALBEDO_TEXTURES[key]
    for j in range(n):
        for i in range(n):
            t = tone(i, j)
            px[idx : idx + 4] = (min(1.0, color[0] * t[0]), min(1.0, color[1] * t[1]), min(1.0, color[2] * t[2]), 1.0)
            idx += 4
    img = bpy.data.images.new(name, n, n, alpha=False)
    img.pixels.foreach_set(px)  # an 8-bit sRGB image: these are the sRGB values
    _save(img, f"{mat_name.lower()}_albedo.png")
    return img


def materials():
    mats = []
    for name, p in MATERIALS.items():
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        if mat.node_tree is None:
            mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        lin = tuple(srgb_to_linear(c) for c in p["color"]) + (1.0,)
        mat.diffuse_color = lin
        bsdf.inputs["Base Color"].default_value = lin
        bsdf.inputs["Roughness"].default_value = p["rough"]
        bsdf.inputs["Metallic"].default_value = p["metal"]
        bsdf.inputs["Specular IOR Level"].default_value = p["spec"]
        if "sss" in p:
            bsdf.inputs["Subsurface Weight"].default_value = p["sss"]
            bsdf.inputs["Subsurface Radius"].default_value = p["sss_radius"]
            bsdf.inputs["Subsurface Scale"].default_value = p["sss_scale"]
        if "albedo" in p:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = albedo_image(name, p["albedo"], p["color"])
            tex.location = (-600, 300)
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if "normal" in p:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = normal_image(p["normal"])
            tex.location = (-600, -200)
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.inputs["Strength"].default_value = p.get("bump", 1.0)
            nmap.location = (-300, -200)
            nt.links.new(tex.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        mats.append(mat)
    return mats


def unwrap(obj):
    """UVs for the tiling textures: Smart UV Project, then scaled so one UV unit is
    TILE meters everywhere (the islands keep their relative sizes)."""
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.002, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = obj.data
    uv = mesh.uv_layers.active.data
    area3d = sum(p.area for p in mesh.polygons)
    area_uv = 0.0
    for poly in mesh.polygons:
        pts = [uv[i].uv for i in poly.loop_indices]
        area_uv += abs(sum(pts[k].x * pts[k - 1].y - pts[k - 1].x * pts[k].y for k in range(len(pts)))) / 2
    k = math.sqrt(area3d / area_uv) / TILE
    for loop in uv:
        loop.uv *= k
    obj.select_set(False)


# --- Shapes -----------------------------------------------------------------------


def blob_mesh(blob, ratio, displace=None):
    """The chef's `Blob.mesh`, with an optional `displace(point) -> meters` pushed
    along the normals after smoothing and before decimating (cloth folds, hair)."""
    obj = bpy.data.objects.new("Blob", blob.mb)
    bpy.context.scene.collection.objects.link(obj)
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    bpy.data.objects.remove(obj)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    for _ in range(4):
        bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    if displace is not None and bm.verts:
        bm.normal_update()
        center = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
        sign = 1 if sum((v.co - center).dot(v.normal) for v in bm.verts) >= 0 else -1
        moves = [v.normal * (sign * displace(v.co)) for v in bm.verts]
        for v, d in zip(bm.verts, moves):
            v.co += d
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


class Model(chef.Model):
    """The chef's `Model`, on this skeleton and these materials, with displaced blobs."""

    def weigh(self, verts, weights):
        for v in verts:
            ws = {weights: 1.0} if isinstance(weights, str) else weights(v.co)
            for bone, w in ws.items():
                v[self.deform][BONE_NAMES.index(bone)] = w

    def paint(self, verts, mat, smooth=True):
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = MAT[mat]
            f.smooth = smooth

    def blob(self, name, blob, ratio, mat, weights, displace=None):
        mesh = blob_mesh(blob, ratio, displace)
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

    def surface(self, name, verts):
        """Registers `verts`' faces as a surface for `hit` / `fit`."""
        faces = list(dict.fromkeys(f for v in verts for f in v.link_faces))
        index = {v: i for i, v in enumerate(verts)}
        self.surfaces[name] = BVHTree.FromPolygons([v.co for v in verts], [[index[v] for v in f.verts] for f in faces if all(v in index for v in f.verts)])

    def outer_hit(self, pieces, center, angle):
        """The outermost point (and normal) of `pieces` seen horizontally from `center` at `angle`."""
        d = Vector((math.cos(angle), math.sin(angle), 0))
        best = None
        for p in pieces:
            loc, normal = self.hit(p, center + d * 0.5, -d)
            if loc is not None and (best is None or (loc - center).xy.length > (best[0] - center).xy.length):
                best = (loc, normal)
        return best


def folds(a, b, across, along, amp, seed, envelope=None, valley=0.45):
    """Cloth folds on a piece wrapped round the segment a-b: sharp ridges `across`
    meters apart running `along` meters along it, `amp` deep. `envelope(t, p)` (t = 0
    at a, 1 at b) shapes where they show."""
    a, b = Vector(a), Vector(b)
    length = (b - a).length
    d = (b - a) / length
    u = d.orthogonal().normalized()
    w = d.cross(u)

    def f(p):
        r = p - a
        t = r.dot(d)
        radial = r - d * t
        n = noise3((radial.dot(u) / across, radial.dot(w) / across, t / along), seed)
        ridge = (1 - abs(n)) ** 2.5
        e = 1.0 if envelope is None else envelope(t / length, p)
        return amp * e * (ridge - valley)

    return f


def combine(*fs):
    return lambda p: sum(f(p) for f in fs)


def head_blob():
    """A lean face: high cheekbones, a square jaw, a straight nose and a full mouth
    (the mask drapes over the lower half, so it takes their shape)."""
    b = Blob(resolution=0.0032)
    b.ell((-0.005, 0, 1.07), (0.086, 0.073, 0.088))  # cranium
    b.ell((0.022, 0, 1.015), (0.07, 0.062, 0.072))  # face and jaw
    b.ell((0.052, 0, 0.965), (0.04, 0.042, 0.024), stiffness=3)  # square chin
    b.cap((-0.012, 0, 0.825), (0.0, 0, 0.975), 0.047)  # neck
    for s in (1, -1):
        b.ell((0.06, s * 0.041, 1.03), (0.021, 0.023, 0.017), stiffness=3)  # cheekbones
        b.cap((-0.02, s * 0.054, 1.0), (0.058, s * 0.031, 0.952), 0.015, stiffness=3)  # jawline
        b.cap((0.08, s * 0.012, 1.08), (0.074, s * 0.048, 1.085), 0.011, stiffness=3)  # brow ridge
        b.ell((0.074, s * 0.03, 1.055), (0.0125, 0.0165, 0.0112), stiffness=4, negative=True)  # eye socket, almond-shaped
        b.ell((0.077, s * 0.03, 1.07), (0.008, 0.016, 0.006), stiffness=4)  # fold of the upper lid
        b.ell((-0.012, s * 0.076, 1.045), (0.016, 0.0095, 0.027), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-10 * s)))  # ears
        b.ell((-0.006, s * 0.084, 1.048), (0.008, 0.0065, 0.014), stiffness=5, negative=True)
        b.cap((-0.004, s * 0.072, 1.0275), (-0.011, s * 0.075, 1.064), 0.003, stiffness=5)  # rim of the ear
    b.cap((0.084, 0, 1.075), (0.1, 0, 1.035), 0.008, stiffness=3)  # nose bridge
    b.ell((0.098, 0, 1.03), (0.011, 0.013, 0.0095), stiffness=3)  # nose tip
    b.cap((0.087, -0.018, 0.99), (0.087, 0.018, 0.99), 0.0032, stiffness=6, negative=True)  # mouth
    b.ell((0.085, 0, 0.983), (0.008, 0.017, 0.0055), stiffness=4)  # lower lip
    return b


def hair_blob():
    """Dark hair combed straight back under the headband."""
    b = Blob(resolution=0.0035)
    b.ell((-0.02, 0, 1.085), (0.09, 0.078, 0.082))
    for s in (1, -1):
        b.ell((-0.01, s * 0.085, 1.045), (0.025, 0.019, 0.032), stiffness=4, negative=True)  # ears
    b.ell((0.064, 0, 1.035), (0.05, 0.08, 0.06), stiffness=4, negative=True)  # clear of the face
    b.ell((-0.03, 0, 0.96), (0.078, 0.085, 0.048), stiffness=4, negative=True)  # nape
    return b


def hair_strands(p):
    """Combed strands: long front to back, tight side to side."""
    return 0.0011 * noise3((p.x / 0.05, p.y / 0.0032, p.z / 0.0032), 71) + 0.0006 * noise3((p.x / 0.02, p.y / 0.008, p.z / 0.008), 72)


def gi_blob():
    """The jacket's body: a lean chest, a narrow waist, the cloth bloused over the obi."""
    b = Blob(resolution=0.0045)
    b.ell((0.0, 0, 0.755), (0.092, 0.137, 0.106))  # chest
    b.ell((0.005, 0, 0.625), (0.088, 0.121, 0.106))  # waist
    b.ell((0.012, 0, 0.598), (0.09, 0.125, 0.05), stiffness=3)  # bloused over the obi
    for s in (1, -1):
        b.ell((0.045, s * 0.05, 0.768), (0.04, 0.05, 0.04), stiffness=3)  # pecs, under the cloth
        b.ell((-0.005, s * 0.087, 0.825), (0.052, 0.065, 0.034))  # trapezius
        b.ell((0.0, s * 0.145, 0.81), (0.05, 0.042, 0.042))  # shoulder seam
        b.ell((-0.055, s * 0.055, 0.755), (0.038, 0.056, 0.065))  # shoulder blades
    b.ell((0.0, 0, 0.44), (0.1, 0.13, 0.02), stiffness=4)  # hem, tucked in the trousers
    return b


def gi_folds():
    above_obi = lambda t, p: smoothstep(0.56, 0.6, p.z) * (1 - smoothstep(0.62, 0.74, p.z))  # noqa: E731
    chest = lambda t, p: smoothstep(0.6, 0.66, p.z) * (1 - smoothstep(0.76, 0.84, p.z))  # noqa: E731
    return combine(
        folds((0, 0, 0.44), (0, 0, 0.88), 0.018, 0.05, 0.0055, 1, above_obi),
        # Drag lines from the armpits down to the obi, on the front and the back.
        folds((0, -0.3, 0.42), (0, 0.3, 0.9), 0.026, 0.1, 0.0022, 2, chest),
        folds((0, 0.3, 0.42), (0, -0.3, 0.9), 0.026, 0.1, 0.0022, 3, chest),
    )


def sleeve_blob(s):
    """A sleeve full at the shoulder and upper arm, tight on the forearm under the wraps."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.004)
    b.ell((0.0, y - s * 0.005, 0.805), (0.05, 0.05, 0.055))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1]), 0.044)
    b.ell((0.0, y, 0.71), (0.047, 0.048, 0.07), stiffness=3)  # loose cloth round the upper arm
    b.cap((0, y, ELBOW[1]), (0, y, WRIST[1] + 0.03), 0.031)
    return b


def sleeve_folds(s):
    y = s * SHOULDER[0]
    upper = lambda t, p: smoothstep(0.6, 0.66, p.z) * (1 - smoothstep(0.78, 0.84, p.z))  # noqa: E731
    elbow = lambda t, p: smoothstep(0.58, 0.62, p.z) * (1 - smoothstep(0.66, 0.7, p.z))  # noqa: E731
    return combine(
        folds((0, y, 0.86), (0, y, 0.6), 0.013, 0.05, 0.0035, 10 + s, upper),
        folds((0, y, 0.86), (0, y, 0.6), 0.04, 0.012, 0.003, 12 + s, elbow),  # bunching at the bend
    )


def pant_blob(s):
    """One leg of the trousers: baggy through the thigh, bloused over the shin wraps."""
    y = s * HIP[0]
    b = Blob(resolution=0.0045)
    b.ell((-0.02, s * 0.045, 0.48), (0.088, 0.068, 0.07))  # seat and hip
    b.cap((0, y, HIP[1] - 0.04), (0, y, KNEE[1] + 0.02), 0.057)  # thigh
    b.ell((0.01, y, 0.41), (0.062, 0.06, 0.09), stiffness=3)  # baggy cloth on the thigh
    b.ell((0.006, y, 0.295), (0.052, 0.05, 0.038), stiffness=3)  # bloused over the wraps
    b.cap((0, y, KNEE[1]), (0, y, ANKLE[1] + 0.01), 0.036)  # shin, under the wraps
    return b


def pant_folds(s):
    y = s * HIP[0]
    thigh = lambda t, p: smoothstep(0.3, 0.36, p.z) * (1 - smoothstep(0.48, 0.54, p.z))  # noqa: E731
    blouse = lambda t, p: smoothstep(0.26, 0.28, p.z) * (1 - smoothstep(0.32, 0.36, p.z))  # noqa: E731
    return combine(
        folds((0, y, 0.56), (0, y, 0.26), 0.016, 0.07, 0.005, 20 + s, thigh),
        folds((0, y, 0.56), (0, y, 0.26), 0.04, 0.012, 0.0045, 22 + s, blouse),
    )


def tabi_blob(s):
    """A split-toe tabi: the big toe in its own pocket, a groove between."""
    y = s * HIP[0]
    b = Blob(resolution=0.003)
    b.ell((0.035, y, 0.042), (0.085, 0.036, 0.033), stiffness=3)  # foot
    b.ell((0.105, y + s * 0.008, 0.029), (0.042, 0.027, 0.021), stiffness=3)  # four toes
    b.ell((0.12, y - s * 0.022, 0.031), (0.04, 0.015, 0.023), stiffness=3)  # big toe
    b.ell((-0.025, y, 0.046), (0.04, 0.035, 0.042), stiffness=3)  # heel
    b.cap((0, y, 0.05), (0, y, 0.14), 0.034)  # ankle, under the shin wraps
    b.cap((0.1, y - s * 0.0075, 0.045), (0.18, y - s * 0.0075, 0.04), 0.0035, stiffness=6, negative=True)  # the split
    b.ell((0.05, y, -0.088), (0.4, 0.3, 0.1), stiffness=4, negative=True)  # flat underneath
    return b


def sole_blob(s):
    """The tabi's rubber sole, following its outline and its split toe."""
    y = s * HIP[0]
    b = Blob(resolution=0.0025)
    for (x, dy), (sx, sy) in (((0.035, 0), (0.085, 0.038)), ((0.105, s * 0.008), (0.044, 0.029)), ((0.12, -s * 0.022), (0.042, 0.017)), ((-0.025, 0), (0.042, 0.037))):
        b.ell((x, y + dy, 0.0075), (sx, sy, 0.0075), stiffness=4)
    b.cap((0.1, y - s * 0.0075, 0.007), (0.18, y - s * 0.0075, 0.007), 0.003, stiffness=6, negative=True)
    return b


def hand_blob(s):
    """An open hand hanging in line with the forearm (fingers down at rest, palm toward
    the body): wrist, palm with its pads, and the thumb tucked along the index finger.
    The fingers are separate pieces (`finger_blob`)."""
    y = s * SHOULDER[0]
    w = WRIST[1]
    b = Blob(resolution=0.0018)
    b.ell((0.0, y, w + 0.012), (0.021, 0.015, 0.03))  # wrist
    b.ell((0.001, y, w - 0.038), (0.029, 0.0115, 0.036), stiffness=3)  # palm
    b.ell((0.0, y - s * 0.004, w - 0.052), (0.025, 0.009, 0.02), stiffness=3)  # pads under the knuckles
    b.ell((0.017, y - s * 0.006, w - 0.022), (0.013, 0.011, 0.022), stiffness=3)  # ball of the thumb
    b.ell((-0.018, y - s * 0.004, w - 0.032), (0.009, 0.009, 0.026), stiffness=3)  # heel of the hand
    for i, (x, kz, _, r) in enumerate(FINGERS):
        b.ball((x, y, kz), r * 1.15, stiffness=3)  # knuckles
    b.cap((0.022, y - s * 0.003, w - 0.012), (0.033, y - s * 0.009, w - 0.04), 0.0085, stiffness=3)  # thumb
    b.cap((0.033, y - s * 0.009, w - 0.04), (0.036, y - s * 0.017, w - 0.062), 0.0068, stiffness=3)
    b.cap((0.036, y - s * 0.017, w - 0.062), (0.033, y - s * 0.022, w - 0.079), 0.006, stiffness=3)
    return b


# (x, knuckle height, length, radius): index (thumb side, +X) to little finger.
FINGERS = [
    (0.0195, WRIST[1] - 0.072, 0.047, 0.0058),
    (0.0065, WRIST[1] - 0.076, 0.052, 0.006),
    (-0.0065, WRIST[1] - 0.074, 0.049, 0.0056),
    (-0.0185, WRIST[1] - 0.068, 0.039, 0.0049),
]
CURL = (8, 24, 16)  # degrees each finger bends toward the palm at its three joints


def finger_points(s, i):
    """The four joints (knuckle to tip) of finger `i`, slightly curled and fanned."""
    x, kz, length, _ = FINGERS[i]
    p = Vector((x, s * SHOULDER[0], kz))
    points, bend = [p.copy()], 0
    for frac, c in zip((0.46, 0.31, 0.23), CURL):
        bend += c
        d = Vector((x * 0.6, -s * math.sin(math.radians(bend)), -math.cos(math.radians(bend)))).normalized()
        p = p + d * length * frac
        points.append(p.copy())
    return points


def finger_blob(s, i):
    r = FINGERS[i][3]
    pts = finger_points(s, i)
    b = Blob(resolution=0.0014)
    radii = (r, r * 0.93, r * 0.86, r * 0.78)
    for k in range(3):
        b.cap(pts[k], pts[k + 1] - (pts[k + 1] - pts[k]) * (0.2 if k == 2 else 0), (radii[k] + radii[k + 1]) / 2, stiffness=3)
    for k in (1, 2):
        b.ball(pts[k], radii[k] * 1.06, stiffness=4)  # joints
    return b


def ninja_mesh():
    m = Model()
    head = m.blob("head", head_blob(), 0.5, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.35, "Hair", "head", hair_strands)
    log("head")
    gi = m.blob("gi", gi_blob(), 0.35, "Gi", by_distance("hips", "spine"), gi_folds())
    on_gi = m.weights_near(gi)
    log("gi")
    for side, s in (("L", 1), ("R", -1)):
        sleeve = m.blob(f"sleeve.{side}", sleeve_blob(s), 0.35, "Gi", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6), sleeve_folds(s))
        m.blob(f"hand.{side}", hand_blob(s), 0.4, "Skin", f"forearm.{side}")
        for i in range(4):
            m.blob(f"finger{i}.{side}", finger_blob(s, i), 0.45, "Skin", f"forearm.{side}")
        leg = m.blob(f"leg.{side}", pant_blob(s), 0.35, "Gi", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6), pant_folds(s))
        m.blob(f"tabi.{side}", tabi_blob(s), 0.35, "Wrap", by_distance(f"shin.{side}", f"foot.{side}", sharpness=8))
        m.blob(f"sole.{side}", sole_blob(s), 0.35, "Sole", f"foot.{side}")
        hand_guard(m, s, side)
        wrap_bands(m, (f"sleeve.{side}", f"hand.{side}"), 0, s * SHOULDER[0], WRIST[1] - 0.008, ELBOW[1] - 0.045, 0.024, m.weights_near(sleeve), start=1.3 * s)
        shin = wrap_bands(m, (f"leg.{side}", f"tabi.{side}"), 0, s * HIP[0], 0.092, KNEE[1] - 0.02, 0.026, m.weights_near(leg), start=0.7 * s)
        kyahan_tie(m, s, side, m.weights_near(shin))
        tabi_clasps(m, s, side)
        log(f"limbs {side}")
    face(m)
    face_mask(m, m.weights_near(head))
    log("mask")
    headband(m)
    lapels(m, on_gi)
    side_seams(m, on_gi)
    obi(m)
    shuriken_pouch(m)

    mesh = bpy.data.meshes.new("NinjaMesh")
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces[:])
    m.bm.to_mesh(mesh)
    m.bm.free()
    for mat in materials():
        mesh.materials.append(mat)
    return mesh


def faces_of(verts):
    """The faces round `verts`, in a stable order (a set's order would vary per run)."""
    return list(dict.fromkeys(f for v in verts for f in v.link_faces))


def solid(m, faces, thickness):
    """Gives a sheet of `faces` thickness; returns every vert of the result."""
    verts = dict.fromkeys(v for f in faces for v in f.verts)
    out = bmesh.ops.solidify(m.bm, geom=faces, thickness=thickness)
    return list(verts) + [v for v in out["geom"] if isinstance(v, bmesh.types.BMVert) and v not in verts]


def grid_faces(bm, grid, closed=False):
    faces = []
    for r0, r1 in zip(grid, grid[1:]):
        n = len(r0)
        for j in range(n if closed else n - 1):
            faces.append(bm.faces.new((r0[j], r0[(j + 1) % n], r1[(j + 1) % n], r1[j])))
    return faces


def hand_guard(m, s, side):
    """The tekko: a cloth guard over the back of the hand, from the wrist to the
    knuckles, held by a loop round the middle finger."""
    y = s * SHOULDER[0]
    rows = []
    for i in range(10):
        t = i / 9
        z = WRIST[1] + 0.012 - 0.074 * t
        half = 0.027 - 0.006 * t
        row = []
        for j in range(8):
            x = -half + 2 * half * j / 7
            loc, normal = m.hit(f"hand.{side}", (x, y + s * 0.2, z), (0, -s, 0))
            if loc is None:
                loc, normal = Vector((x, y + s * 0.012, z)), Vector((0, s, 0))
            row.append(m.bm.verts.new(loc + normal * 0.0016))
        rows.append(row)
    verts = solid(m, grid_faces(m.bm, rows), 0.0015)
    m.part(verts, f"forearm.{side}", "Wrap")
    # The loop round the middle finger.
    pts = finger_points(s, 1)
    c, d = (pts[0] + pts[1]) / 2, (pts[1] - pts[0]).normalized()
    u = d.cross(Vector((1, 0, 0))).normalized()
    v = d.cross(u)
    r = FINGERS[1][3] + 0.0012
    loop = [c + (u * math.cos(a) + v * math.sin(a)) * r for a in (2 * math.pi * k / 12 for k in range(13))]
    m.part(tube(m.bm, loop, [0.0011] * len(loop), sides=6), f"forearm.{side}", "Wrap")


def wrap_bands(m, pieces, x, y, z0, z1, height, weights, start=0.0, tilt=0.006, lift=0.0022, sides=40):
    """Overlapping turns of a cloth strip wound up a vertical limb (forearm or shin):
    each turn tilted, phased round from the last, and laid over the one below."""
    turns = max(1, round((z1 - z0 - height) / (height * 0.72)))
    step = (z1 - z0 - height) / turns
    out = []
    for k in range(turns + 1):
        zb = z0 + k * step
        phase = start + k * 2.4
        rows = []
        for frac, puff in ((0.0, 0.0), (0.5, 0.0009), (1.0, 0.0)):
            row = []
            for j in range(sides):
                a = 2 * math.pi * j / sides
                z = zb + frac * height + tilt * math.sin(a + phase)
                center = Vector((x, y, z))
                rad = m.fit(pieces, center, a) + lift + 0.0009 * k + puff
                row.append(m.bm.verts.new(center + Vector((math.cos(a), math.sin(a), 0)) * rad))
            rows.append(row)
        verts = solid(m, grid_faces(m.bm, rows, closed=True), 0.0016)
        m.part(verts, weights, "Wrap")
        out += verts
    return out


def kyahan_tie(m, s, side, weights):
    """The cord tying the shin wrap below the knee, knotted on the outside."""
    y = s * HIP[0]
    z = KNEE[1] - 0.026
    center = Vector((0, y, z))
    loop = []
    for j in range(33):
        a = 2 * math.pi * j / 32
        loop.append(center + Vector((math.cos(a), math.sin(a), 0)) * (m.fit((f"leg.{side}",), center, a) + 0.004))
    m.part(tube(m.bm, loop, [0.0022] * len(loop), sides=6), weights, "Wrap")
    knot = center + Vector((0, s, 0)) * (m.fit((f"leg.{side}",), center, s * math.pi / 2) + 0.006)
    m.part(uv_ellipsoid(m.bm, knot, (0.006, 0.005, 0.006), segments=(10, 6)), weights, "Wrap")
    for dz, dx in ((-0.03, 0.006), (-0.026, -0.008)):
        m.part(tube(m.bm, [knot, knot + Vector((dx * 0.5, s * 0.004, dz * 0.5)), knot + Vector((dx, s * 0.005, dz))], [0.002, 0.0018, 0.0014], sides=5), weights, "Wrap")


def tabi_clasps(m, s, side):
    """Kohaze: the little metal hooks closing the tabi at the back of the ankle."""
    y = s * HIP[0]
    for z in (0.052, 0.074):
        loc, normal = m.hit(f"tabi.{side}", (-0.3, y + s * 0.012, z), (1, 0, 0))
        if loc is not None:
            rot = normal.to_track_quat("Z", "Y")
            m.part(uv_ellipsoid(m.bm, loc + normal * 0.0008, (0.006, 0.0022, 0.0009), rot, segments=(10, 6)), f"foot.{side}", "Steel")


def face(m):
    """Eyes under heavy, narrowed lids with a dark lash line, and the brows."""

    def on_skin(y, z, lift):
        loc, normal = m.hit("head", (0.4, y, z), (-1, 0, 0))
        return loc + normal * lift

    r = 0.0115
    for s in (1, -1):
        eye = on_skin(s * 0.03, 1.055, 0) - Vector((0.0062, 0, 0))
        m.part(uv_ellipsoid(m.bm, eye, (r,) * 3, segments=(20, 12)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((r * 0.92, 0, -0.0006)), (0.0016, 0.0056, 0.0056), segments=(16, 8)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((r * 0.99, 0, -0.0006)), (0.0007, 0.0024, 0.0024), segments=(12, 6)), "head", "Pupil")
        # Lids: shells of skin over the eyeball, cut along a tilted plane (the upper
        # one slanting down toward the nose, a scowl).
        for normal, cut, lash in (((-0.3, -s * 0.2, 1.0), 0.42, True), ((-0.3, 0.0, -1.0), 0.62, False)):
            n = Vector(normal).normalized()
            rot = Vector((0, 0, 1)).rotation_difference(n)
            lid_r = r + 0.0011
            verts = uv_ellipsoid(m.bm, eye, (lid_r,) * 3, rot, segments=(28, 18))
            drop = [v for v in verts if (v.co - eye).dot(n) < cut * lid_r]
            keep = [v for v in verts if v not in set(drop)]
            bmesh.ops.delete(m.bm, geom=drop, context="VERTS")
            m.part(keep, "head", "Skin")
            if lash:
                edge = min((v.co - eye).dot(n) for v in keep) / lid_r
                e1 = n.orthogonal().normalized()
                e2 = n.cross(e1)
                ring = [eye + (n * edge + (e1 * math.cos(a) + e2 * math.sin(a)) * math.sqrt(1 - edge * edge)) * lid_r for a in (2 * math.pi * k / 64 for k in range(64))]
                front = [p for p in ring if (p - eye).x > 0.45 * r]
                front.sort(key=lambda p: p.y)
                if len(front) > 2:
                    radii = [0.0007 + 0.0005 * math.sin(math.pi * i / (len(front) - 1)) for i in range(len(front))]
                    m.part(tube(m.bm, front, radii, sides=6), "head", "Hair")
        # Brows: flat, tapering strokes lying on the skin, low and drawn in.
        for lift, rows in ((0.0006, ((0.009, 1.075), (0.024, 1.0805), (0.04, 1.0825), (0.055, 1.0785))),
                           (0.0004, ((0.012, 1.0785), (0.03, 1.084), (0.048, 1.0845)))):
            pts = [on_skin(s * y, z, lift) for y, z in rows]
            verts = tube(m.bm, pts, [0.0034, 0.0036, 0.003, 0.0018][: len(pts)], sides=8)
            for v in verts:  # flatten against the brow
                loc, normal = m.hit("head", v.co + Vector((0.05, 0, 0)), (-1, 0, 0))
                if loc is not None:
                    v.co = v.co + normal * (-(v.co - loc).dot(normal) * 0.55)
            m.part(verts, "head", "Hair")


def _hull_radii(angles, radii):
    """For a slice given as radius per angle (round the origin), the radius of its
    convex hull at each angle: cloth stretched across the slice's hollows."""
    pts = sorted({(round(math.cos(a) * r, 7), round(math.sin(a) * r, 7)) for a, r in zip(angles, radii) if r > 0})
    if len(pts) < 3:
        return list(radii)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    out = []
    for a, r in zip(angles, radii):
        d = (math.cos(a), math.sin(a))
        best = r
        for k in range(len(hull)):
            p, q = hull[k], hull[(k + 1) % len(hull)]
            e = (q[0] - p[0], q[1] - p[1])
            den = d[0] * e[1] - d[1] * e[0]
            if abs(den) < 1e-12:
                continue
            t = (p[0] * e[1] - p[1] * e[0]) / den
            u = (p[0] * d[1] - p[1] * d[0]) / den
            if t > 0 and -1e-9 <= u <= 1 + 1e-9:
                best = max(best, t)
        out.append(best)
    return out


def mask_top(a):
    """Height of the mask's upper edge at angle `a` round the head: up over the bridge
    of the nose, just under the eyes, then up over the ears and round the back of
    the head under the headband."""
    deg = abs(math.degrees((a + math.pi) % (2 * math.pi) - math.pi))
    return 1.036 + 0.042 * smoothstep(40, 72, deg) + 0.024 * max(0.0, 1 - deg / 16) ** 1.5


def face_mask(m, on_head):
    """The fukumen: one piece of cloth from inside the collar up over the bridge of the
    nose. It stretches across the cheeks and falls straight off the nose and chin
    (it doesn't follow the mouth or the throat), creases loosely round the neck, and
    is knotted at the back of the head."""
    cx = -0.01
    sides, rows = 96, 28
    angles = [2 * math.pi * j / sides for j in range(sides)]
    z_lo, z_hi, dz = 0.85, 1.066, 0.003
    zs = [z_lo + dz * i for i in range(round((z_hi - z_lo) / dz) + 1)]
    table = []
    for z in zs:
        center = Vector((cx, 0, z))
        table.append(_hull_radii(angles, [m.fit(("head", "hair"), center, a) for a in angles]))
    for i in range(len(zs) - 2, -1, -1):  # drape: in front, cloth hangs from the nose and chin
        for j, a in enumerate(angles):
            front = 1 - smoothstep(0.6, 1.2, abs((a + math.pi) % (2 * math.pi) - math.pi))
            if front > 0:
                table[i][j] = max(table[i][j], table[i][j] + front * (table[i + 1][j] - 0.55 * dz - table[i][j]))

    def radius(z, j):
        f = max(0.0, min(len(zs) - 1.001, (z - z_lo) / dz))
        i = int(f)
        return table[i][j] + (table[i + 1][j] - table[i][j]) * (f - i)

    grid = []
    for r in range(rows + 1):
        row = []
        for j, a in enumerate(angles):
            z = z_lo + (mask_top(a) - z_lo) * (r / rows) ** 0.85
            d = Vector((math.cos(a), math.sin(a), 0))
            rad = radius(z, j) + 0.0035
            loose = 1 - smoothstep(0.93, 1.0, z)
            p = Vector((cx, 0, z)) + d * rad
            ridge = (1 - abs(noise3((p.x / 0.011, p.y / 0.011, z / 0.03), 81))) ** 4
            rad += 0.004 * loose * (ridge - 0.25)
            row.append(m.bm.verts.new(Vector((cx, 0, z)) + d * rad))
        grid.append(row)
    verts = solid(m, grid_faces(m.bm, grid, closed=True), 0.0022)
    m.part(verts, on_head, "Wrap")
    m.surface("mask", verts)
    # The knot at the back, two short tails hanging from it.
    back = Vector((cx - radius(1.0, sides // 2) - 0.008, 0, 1.0))
    m.part(uv_ellipsoid(m.bm, back, (0.011, 0.016, 0.012)), on_head, "Wrap")
    for s in (1, -1):
        tail = [back + Vector(d) for d in ((-0.003, s * 0.006, -0.004), (-0.012, s * 0.012, -0.03), (-0.016, s * 0.016, -0.06), (-0.016, s * 0.015, -0.085))]
        verts = tube(m.bm, tail, [0.008, 0.01, 0.0095, 0.008], sides=8)
        for v in verts:  # flatten into cloth
            v.co.x = tail[1].x + (v.co.x - tail[1].x) * 0.3
        m.part(verts, on_head, "Wrap")


def headband(m):
    """A cloth headband (`Body`) across the forehead, knotted at the back with two
    tails hanging behind."""
    center = lambda z: Vector((-0.012, 0, z))  # noqa: E731
    sides = 64
    fit = [m.fit(("head", "hair"), center(1.112), 2 * math.pi * j / sides) + 0.0035 for j in range(sides)]
    z0, z1 = 1.094, 1.13

    def r(a, z):
        return fit[round(a / (2 * math.pi) * sides) % sides] + 0.0025 * math.sin(math.pi * (z - z0) / (z1 - z0))

    band = ring_band(m.bm, center, r, z0, z1, rows=4, sides=sides)
    m.part(solid(m, faces_of(band), 0.002), "head", "Body")
    back = center(1.11) + Vector((-fit[sides // 2] - 0.007, 0, 0))
    m.part(uv_ellipsoid(m.bm, back, (0.012, 0.017, 0.014)), "head", "Body")
    for s in (1, -1):
        tail = [back + Vector(d) for d in ((-0.004, s * 0.006, -0.004), (-0.02, s * 0.014, -0.03), (-0.03, s * 0.018, -0.07), (-0.034, s * 0.016, -0.1))]
        verts = tube(m.bm, tail, [0.009, 0.011, 0.011, 0.009], sides=8)
        for v in verts:  # flatten into cloth, edge-on to the side
            v.co.y = tail[1].y + (v.co.y - tail[1].y) * 0.35
        m.part(verts, "head", "Body")


def ribbon(m, pieces, path, width, lift, thickness, weights, mat):
    """A strip of cloth laid on `pieces` along `path` [(angle in degrees round the
    torso, z)], `width` across, given `thickness`."""
    pts = []
    for deg, z in path:
        hit = m.outer_hit(pieces, Vector((0, 0, z)), math.radians(deg))
        if hit is not None:
            pts.append(hit)
    rows = []
    for i, (loc, normal) in enumerate(pts):
        a = pts[max(i - 1, 0)][0]
        b = pts[min(i + 1, len(pts) - 1)][0]
        across = normal.cross(b - a).normalized()
        base = loc + normal * lift
        rows.append([m.bm.verts.new(base + across * width * k / 2 + normal * (0.0012 * (1 - k * k))) for k in (-1, -0.5, 0, 0.5, 1)])
    verts = solid(m, grid_faces(m.bm, rows), thickness)
    m.part(verts, weights, mat)
    return verts


def lapels(m, on_gi):
    """The jacket's crossed front: a thick collar band standing round the base of the
    neck, its wearer's-left side crossing over the right down to the obi."""
    outer = [(180, 0.846), (150, 0.847), (118, 0.846), (88, 0.84), (60, 0.82), (36, 0.785), (16, 0.74), (0, 0.7), (-16, 0.66), (-32, 0.62), (-44, 0.59)]
    inner = [(180, 0.846), (-150, 0.847), (-118, 0.846), (-88, 0.84), (-60, 0.82), (-36, 0.785), (-16, 0.74), (0, 0.71), (12, 0.685)]
    ribbon(m, ("gi", "mask"), inner, 0.03, 0.002, 0.004, on_gi, "Gi")
    ribbon(m, ("gi", "mask"), outer, 0.032, 0.0055, 0.0045, on_gi, "Gi")


def side_seams(m, on_gi):
    """Seams down each side of the jacket, under the arms."""
    for s in (1, -1):
        seam = []
        for i in range(10):
            z = 0.8 - 0.22 * i / 9
            loc, normal = m.hit("gi", (0.0, s * 0.5, z), (0, -s, 0))
            if loc is not None:
                seam.append(loc + normal * 0.001)
        if len(seam) > 1:
            m.part(tube(m.bm, seam, [0.0025] * len(seam), sides=6), on_gi, "Wrap")


def obi(m):
    """The obi (`Body`): two turns of a broad sash round the waist, knotted at the back
    with its ends hanging down."""
    center = lambda z: Vector((0.005, 0, z))  # noqa: E731
    sides = 64
    fit = [m.fit(("gi", "leg.L", "leg.R"), center(0.55), 2 * math.pi * j / sides) + 0.005 for j in range(sides)]

    def at(a):
        return fit[round(a / (2 * math.pi) * sides) % sides]

    for z0, z1, out in ((0.512, 0.588, 0.0), (0.53, 0.572, 0.0045)):
        band = ring_band(m.bm, center, lambda a, z, z0=z0, z1=z1, out=out: at(a) + out + 0.003 * math.sin(math.pi * (z - z0) / (z1 - z0)), z0, z1, rows=4, sides=sides)
        m.part(solid(m, faces_of(band), 0.002), "hips", "Body")
    knot = center(0.55) + Vector((-at(math.pi) - 0.012, 0, 0))
    m.part(uv_ellipsoid(m.bm, knot, (0.014, 0.022, 0.018)), "hips", "Body")
    for s, length in ((1, 0.12), (-1, 0.1)):
        end = [knot + Vector(d) for d in ((-0.002, s * 0.008, -0.01), (-0.008, s * 0.02, -0.04), (-0.006, s * 0.026, -length * 0.7), (-0.004, s * 0.028, -length))]
        verts = tube(m.bm, end, [0.012, 0.015, 0.016, 0.015], sides=8)
        for v in verts:  # flatten against the seat
            v.co.x = end[1].x + (v.co.x - end[1].x) * 0.3
        m.part(verts, by_distance("hips", "thigh.L", "thigh.R"), "Body")


def add_bm(bm, src):
    """Copies the bmesh `src` into `bm` (and frees it); returns the new verts."""
    vmap = {v: bm.verts.new(v.co) for v in src.verts}
    for f in src.faces:
        bm.faces.new([vmap[v] for v in f.verts])
    src.free()
    return list(vmap.values())


def rounded_box(bm, center, size, radius):
    tmp = bmesh.new()
    bmesh.ops.create_cube(tmp, size=1.0, matrix=Matrix.Translation(center) @ Matrix.Diagonal((*size, 1)))
    bmesh.ops.bevel(tmp, geom=tmp.verts[:] + tmp.edges[:], offset=radius, segments=3, affect="EDGES", profile=0.5)
    return add_bm(bm, tmp)


def star(bm, center, points=4, r_out=0.016, r_in=0.005, thickness=0.0022):
    """A flat throwing star in the XZ plane (facing Y), centered on `center`."""
    tmp = bmesh.new()
    outline = []
    for k in range(points * 2):
        a = math.pi * k / points + math.pi / 4
        r = r_out if k % 2 == 0 else r_in
        outline.append(Vector((math.cos(a) * r, 0, math.sin(a) * r)))
    top = [tmp.verts.new(center + p + Vector((0, thickness / 2, 0))) for p in outline]
    bot = [tmp.verts.new(center + p - Vector((0, thickness / 2, 0))) for p in outline]
    tmp.faces.new(top)
    tmp.faces.new(list(reversed(bot)))
    n = len(outline)
    for k in range(n):
        tmp.faces.new((top[k], bot[k], bot[(k + 1) % n], top[(k + 1) % n]))
    return add_bm(bm, tmp)


def shuriken_pouch(m):
    """A leather pouch on the back-right hip, its flap shut, a shuriken peeking out."""
    m.part(rounded_box(m.bm, (-0.02, -0.122, 0.5), (0.06, 0.04, 0.068), 0.008), "hips", "Leather")
    m.part(rounded_box(m.bm, (-0.02, -0.124, 0.528), (0.064, 0.046, 0.022), 0.006), "hips", "Leather")
    m.part(uv_ellipsoid(m.bm, (-0.02, -0.148, 0.52), (0.005, 0.003, 0.005), segments=(10, 6)), "hips", "Steel")  # the stud
    m.part(star(m.bm, Vector((0.004, -0.122, 0.542))), "hips", "Steel")


# --- Rig --------------------------------------------------------------------


def build_rig(mesh):
    rig = bpy.data.objects.new("Fighter", bpy.data.armatures.new("NinjaRig"))
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

    body = bpy.data.objects.new("Ninja", mesh)
    bpy.context.scene.collection.objects.link(body)
    unwrap(body)
    body.parent = rig
    for name in BONE_NAMES:
        body.vertex_groups.new(name=name)
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for pb in rig.pose.bones:
        pb.rotation_mode = ROTATION_MODE
    return rig


# --- Poses ------------------------------------------------------------------
# The chef's pose format: {bone: degrees or (pitch, twist, spread)}, plus "hips_loc".
# Bones rotate in "YXZ" order: twist about the bone's own axis first, then pitch,
# then spread. (The chef uses "XYZ"; the two agree whenever twist is 0, which it is in
# every pose but the ledge clips, where a forearm turns its palm to the ledge and the
# hips spin the ledge attack.)
ROTATION_MODE = "YXZ"


def lunge(pose, fwd, drop, front, back=-0.2):
    """`pose` with the hips moved forward and down, feet re-planted wide."""
    return planted(with_(pose, hips_loc=(fwd, -drop)), front, back)


S = with_(guard(drop=0.05, lean=-6, front=0.13, back=-0.13), upper_arm_R=28, forearm_R=102, upper_arm_L=16, forearm_L=108)
CROUCH = with_(crouch(0.15), upper_arm_R=0, forearm_R=70, upper_arm_L=-10, forearm_L=70)
AIR_S = with_(AIR, upper_arm_R=55, forearm_R=70, upper_arm_L=-15, forearm_L=80)
FLINCH_S = FLINCH

# Knife-hand chops (jab chain): the near hand does the cutting.
CHOP_HIGH = with_(S, upper_arm_R=140, forearm_R=20)
CHOP = lunge(with_(S, spine=-14, head=10, upper_arm_R=96, forearm_R=0), 0.05, 0.06, 0.26)
CHOP_LOW = with_(CHOP, upper_arm_R=70, forearm_R=0)
BACKHAND = lunge(with_(S, spine=-10, head=8, upper_arm_L=88, forearm_L=0, upper_arm_R=10), 0.04, 0.06, 0.24)
FINISH = lunge(with_(S, spine=-18, head=12, upper_arm_R=92, forearm_R=0, upper_arm_L=-40), 0.1, 0.08, 0.34)
PALM_WIND = with_(S, spine=4, head=-4, upper_arm_R=-10, forearm_R=80)
PALM = lunge(with_(S, spine=-12, head=8, upper_arm_R=70, forearm_R=6, upper_arm_L=-20, forearm_L=70), 0.08, 0.06, 0.3)
RISE_LOW = with_(CROUCH, upper_arm_R=30, forearm_R=20)
RISE_FRONT = with_(S, spine=-4, upper_arm_R=100, forearm_R=0)
RISE_TOP = with_(S, hips_loc=(0, -0.01), spine=8, head=-10, upper_arm_R=170, forearm_R=0)
SWEEP = planted(with_(crouch(0.22), spine=-16, head=12, upper_arm_R=-60, upper_arm_L=50, forearm_L=40), 0.5, -0.22)
DASH_TRAIL = planted(with_(guard(drop=0.07, lean=-30), hips_loc=(0.06, -0.07), upper_arm_R=60, forearm_R=0, upper_arm_L=-20), 0.2, -0.26)
DASH_CUT = planted(with_(guard(drop=0.08, lean=-24), hips_loc=(0.12, -0.08), upper_arm_R=95, forearm_R=0, upper_arm_L=-40, forearm_L=20), 0.36, -0.26)

# Smash attacks: the pose on the charge frame is held while charging.
CHOP_WIND = lunge(with_(S, spine=12, head=-12, upper_arm_R=165, forearm_R=25, upper_arm_L=160, forearm_L=30), -0.04, 0.05, 0.2)
CHOP_MID = with_(CHOP_WIND, upper_arm_R=145, upper_arm_L=140, spine=0)
CHOP_HIT = lunge(with_(S, spine=-26, head=20, upper_arm_R=112, forearm_R=0, upper_arm_L=108, forearm_L=6), 0.14, 0.12, 0.42, -0.24)
CHOP_DOWN = with_(CHOP_HIT, upper_arm_R=78, upper_arm_L=74)
FLIP_LOW = with_(CROUCH, upper_arm_R=-20, forearm_R=40, upper_arm_L=-20, forearm_L=40)
FLIP_KICK = planted(with_(S, hips_loc=(0, 0.02), spine=-8, head=-14, upper_arm_R=-60, upper_arm_L=-80, thigh_R=130, shin_R=-10, foot_R=-20), 0.08, -0.08)
SPIN_WIND = planted(with_(crouch(0.2), spine=-10, upper_arm_R=-30, upper_arm_L=40), 0.28, -0.28)
SPIN_FRONT = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=80, upper_arm_L=-60, thigh_R=90, shin_R=-10), 0.36, -0.3)
SPIN_BACK = planted(with_(crouch(0.24), spine=-12, head=12, upper_arm_R=-60, upper_arm_L=60, thigh_L=90, shin_L=-10), 0.3, -0.36)

# Aerials
AIR_TUCK = with_(AIR_S, thigh_R=80, shin_R=-120, thigh_L=60, shin_L=-110)
SPIN_FRONT_A = with_(AIR_TUCK, spine=-10, upper_arm_R=110, forearm_R=0)
SPIN_BACK_A = with_(AIR_TUCK, spine=10, upper_arm_R=210, forearm_R=0)
FLY_WIND = with_(AIR_S, spine=10, head=-5, upper_arm_R=170, forearm_R=20, thigh_R=70, shin_R=-110)
FLY = with_(AIR_S, spine=-20, head=16, upper_arm_R=50, forearm_R=0, upper_arm_L=-60, thigh_R=95, shin_R=-6, foot_R=-40)
HOOK = with_(AIR_S, spine=-24, head=26, thigh_L=-95, shin_L=-5, foot_L=40, thigh_R=60, shin_R=-100, upper_arm_R=60, upper_arm_L=40, forearm_L=60)
UP_FLIP = with_(AIR_S, spine=30, head=-18, thigh_R=150, shin_R=-5, foot_R=-20, thigh_L=20, shin_L=-90, upper_arm_R=-60, upper_arm_L=-80)
AXE_WIND = with_(AIR_S, thigh_R=95, shin_R=-135, thigh_L=85, shin_L=-125, upper_arm_R=120, upper_arm_L=110)
AXE = with_(AIR_S, spine=-5, thigh_R=5, shin_R=0, foot_R=-40, thigh_L=-5, shin_L=0, foot_L=-40, upper_arm_R=140, upper_arm_L=130, forearm_R=20, forearm_L=20)

# Specials
SHURIKEN_SHOW = with_(S, spine=-4, upper_arm_R=20, forearm_R=100, upper_arm_L=10, forearm_L=110)
SHURIKEN_WIND = planted(with_(S, hips_loc=(-0.04, -0.05), spine=14, head=-12, upper_arm_R=-55, forearm_R=95, upper_arm_L=60, forearm_L=25), 0.17, -0.2)
SHURIKEN_RELEASE = planted(with_(S, hips_loc=(0.08, -0.07), spine=-18, head=12, upper_arm_R=95, forearm_R=5, upper_arm_L=-25, forearm_L=50), 0.28, -0.2)
DASH_CROUCH = with_(crouch(0.2), spine=-20, head=16, upper_arm_R=-30, upper_arm_L=30, forearm_L=60)
DASH_LEAN = planted(with_(guard(drop=0.06, lean=-40), hips_loc=(0.1, -0.06), upper_arm_R=70, forearm_R=0, upper_arm_L=-50, forearm_L=30), 0.3, -0.3)
SMOKE_CROUCH = with_(crouch(0.28), spine=-30, head=20, upper_arm_R=40, forearm_R=120, upper_arm_L=40, forearm_L=120)
SMOKE_RISE = with_(AIR_S, spine=8, head=-12, upper_arm_R=175, forearm_R=0, upper_arm_L=170, forearm_L=0, thigh_R=30, shin_R=-30, thigh_L=10, shin_L=-10)
SUB_STANCE = planted(with_(S, hips_loc=(-0.02, -0.07), spine=4, head=-4, upper_arm_R=60, forearm_R=110, upper_arm_L=50, forearm_L=115), 0.16, -0.18)
SUB_STRIKE = lunge(with_(S, spine=-20, head=16, upper_arm_R=104, forearm_R=0, upper_arm_L=-36, forearm_L=20), 0.12, 0.1, 0.4)
HELPLESS = with_(AIR_S, spine=10, head=-10, upper_arm_R=150, forearm_R=30, upper_arm_L=140, forearm_L=40, thigh_R=20, shin_R=-40, thigh_L=5, shin_L=-30)

# Grabs and throws
REACH = lunge(with_(S, spine=-14, head=10, upper_arm_R=88, forearm_R=6, upper_arm_L=80, forearm_L=10), 0.06, 0.06, 0.26)
DASH_REACH = planted(with_(guard(drop=0.08, lean=-26), hips_loc=(0.1, -0.08), upper_arm_R=95, forearm_R=5, upper_arm_L=90, forearm_L=10), 0.32, -0.26)
HOLD = with_(S, spine=-5, upper_arm_R=70, forearm_R=50, upper_arm_L=65, forearm_L=55)
POMEL = with_(HOLD, spine=-14, head=10, upper_arm_R=88, forearm_R=20)
THROW_F = lunge(with_(HOLD, spine=-26, head=18, upper_arm_R=100, forearm_R=0, upper_arm_L=60, forearm_L=20), 0.1, 0.12, 0.36)
THROW_B_LOAD = lunge(with_(HOLD, spine=-16, upper_arm_L=168, forearm_L=30), 0.02, 0.18, 0.2)
THROW_B = lunge(with_(HOLD, spine=18, head=-10, upper_arm_L=232, forearm_L=0, upper_arm_R=-30), -0.04, 0.08, 0.16, -0.3)
THROW_U = planted(with_(HOLD, hips_loc=(0, 0.01), spine=8, head=-14, upper_arm_R=178, forearm_R=0, upper_arm_L=170, forearm_L=0), 0.08, -0.08)
THROW_D = planted(with_(crouch(0.26), spine=-30, head=20, upper_arm_R=60, forearm_R=10, upper_arm_L=60, forearm_L=10), 0.3, -0.22)
STRUGGLE = with_(S, spine=15, head=10, upper_arm_R=40, forearm_R=70, upper_arm_L=-30, forearm_L=100)

# Shield and dodges
SHIELD = with_(guard(drop=0.06, lean=-5), upper_arm_R=60, forearm_R=110, upper_arm_L=55, forearm_L=115)
DIZZY = with_(S, spine=(-15, 0, 10), head=(-20, 0, 15), upper_arm_R=-5, forearm_R=10, upper_arm_L=-5, forearm_L=10)
SIDESTEP = with_(crouch(0.08), spine=-10, head=10, upper_arm_R=10, forearm_R=40, upper_arm_L=10, forearm_L=40)
BALL = with_(crouch(0.3), spine=-60, head=40, upper_arm_R=60, forearm_R=130, upper_arm_L=60, forearm_L=130)
AIRDODGE = with_(AIR_S, spine=-10, upper_arm_R=60, forearm_R=120, upper_arm_L=55, forearm_L=125, thigh_R=70, shin_R=-120, thigh_L=60, shin_L=-110)


def walk(stride, lift, drop, swing, phase, run):
    """A walk/run key with the knife-hands held ready."""
    pose = walk_key(stride, lift, drop, swing, phase)
    if run:
        return with_(pose, upper_arm_R=-20, forearm_R=60, upper_arm_L=-30, forearm_L=60)
    return with_(pose, upper_arm_R=30, forearm_R=95, upper_arm_L=16, forearm_L=100)


# --- Ledge clips ----------------------------------------------------------------
# The sim hangs the fighter's origin 0.1 m outside the edge with the top of his
# hurtbox (H) level with the stage, so the ledge corner is at model (0.1, H). A getup
# slides the origin linearly onto the stage; `pose()` in gdext shows Blender frame k
# while the origin is (k - 1)/n of the way there (the state's frame counter runs one
# ahead of the position it set). The clips are authored on the stage instead: in
# "stage" coordinates (origin at the ledge corner, +x onto the stage, z up) each key
# places the hips, then every frame is converted back to model space against where
# the origin is on that frame, so hands and feet stay put on the ledge and the floor.
# Arms that hold the ledge are solved by IK (`arm_ik`), planted feet by `leg_ik`.


def _rest_frames():
    out = {}
    for name, parent, head, tail, _ in BONES:
        head, tail = Vector(head), Vector(tail)
        y = (tail - head).normalized()
        x = Vector((0, 1, 0))
        frame = Matrix((x, y, x.cross(y))).transposed().to_4x4()
        frame.translation = head
        out[name] = frame
    return out


REST = _rest_frames()
PARENT = {b[0]: b[1] for b in BONES}


def _angles(value):
    return value if isinstance(value, tuple) else (value, 0, 0)


def _basis(pose, name):
    pitch, twist, spread = _angles(pose.get(name, 0))
    rot = Euler((math.radians(-pitch), math.radians(twist), math.radians(spread)), ROTATION_MODE).to_matrix().to_4x4()
    if name == "hips":
        fwd, up = pose.get("hips_loc", (0, 0))
        return Matrix.Translation((0, up, fwd)) @ rot
    return rot


def fk(pose, names=BONE_NAMES):
    """Each bone's posed matrix in model space (as `apply_pose` would leave it)."""
    out = {}
    for name in names:
        parent = PARENT[name]
        base = REST[name] if parent is None else out[parent] @ REST[parent].inverted() @ REST[name]
        out[name] = base @ _basis(pose, name)
    return out


def arm_ik(pose, side, target, pole, twist):
    """Sets the arm on `side` so its wrist reaches `target` (model space), the elbow
    bending toward `pole` (a direction), the forearm turned `twist` degrees. Analytic
    two-bone IK; the upper arm takes whatever twist puts the elbow's hinge in the
    plane of the arm."""
    ua, fa = f"upper_arm.{side}", f"forearm.{side}"
    chain = fk(pose, ["hips", "spine"])
    base = chain["spine"] @ REST["spine"].inverted() @ REST[ua]
    shoulder = base.translation
    to = target - shoulder
    dist = max(abs(UPPER_ARM - FOREARM) + 1e-4, min(to.length, UPPER_ARM + FOREARM - 1e-4))
    u = to.normalized()
    alpha = math.acos(max(-1, min(1, (UPPER_ARM**2 + dist**2 - FOREARM**2) / (2 * UPPER_ARM * dist))))
    v = Vector(pole) - u * Vector(pole).dot(u)
    v = v.normalized() if v.length > 1e-6 else u.orthogonal().normalized()
    elbow = shoulder + (u * math.cos(alpha) + v * math.sin(alpha)) * UPPER_ARM
    wrist = shoulder + u * dist
    y_axis = (elbow - shoulder).normalized()
    f = (wrist - elbow).normalized()
    x_axis = f.cross(y_axis)
    x_axis = x_axis.normalized() if x_axis.length > 1e-6 else v.cross(y_axis).normalized()
    world = Matrix((x_axis, y_axis, x_axis.cross(y_axis))).transposed()
    local = base.to_3x3().inverted() @ world
    prev = _angles(pose.get(ua, 0))
    e = local.to_euler(ROTATION_MODE, Euler((math.radians(-prev[0]), math.radians(prev[1]), math.radians(prev[2])), ROTATION_MODE))
    pose[ua] = (-math.degrees(e.x), math.degrees(e.y), math.degrees(e.z))
    flex = math.degrees(math.atan2(-f.dot(x_axis.cross(y_axis)), f.dot(y_axis)))
    pose[fa] = (flex, twist, 0)
    return pose


def _lerp(a, b, t):
    if isinstance(a, tuple) or isinstance(b, tuple):
        a, b = _angles(a), _angles(b)
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def _components(value):
    """A pose value as a tuple of floats: angles as (pitch, twist, spread), positions as-is."""
    return tuple(value) if isinstance(value, tuple) else (value, 0, 0)


def _spline(keys, k):
    """The pose at frame k on a Catmull-Rom spline through `keys` [(frame, pose)]
    (every value componentwise), easing in and out at the first and last keys."""
    i = 0
    while i < len(keys) - 2 and keys[i + 1][0] <= k:
        i += 1
    (f0, p0), (f1, p1) = keys[i], keys[i + 1]
    fp, pp = keys[i - 1] if i > 0 else (f0, p0)
    fn, pn = keys[i + 2] if i + 2 < len(keys) else (f1, p1)
    t = max(0.0, min(1.0, (k - f0) / (f1 - f0)))
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    out = {}
    for name in set(p0) | set(p1):
        a, b = _components(p0.get(name, 0)), _components(p1.get(name, 0))
        prev, nxt = _components(pp.get(name, 0)), _components(pn.get(name, 0))
        vals = []
        for xa, xb, xp, xn in zip(a, b, prev, nxt):
            m0 = 0.0 if i == 0 else (xb - xp) / (f1 - fp) * (f1 - f0)
            m1 = 0.0 if i + 2 >= len(keys) else (xn - xa) / (fn - f0) * (f1 - f0)
            vals.append(h00 * xa + h10 * m0 + h01 * xb + h11 * m1)
        out[name] = tuple(vals)
    return out


def placed(pose, x, z=0.0, **changes):
    """A pose standing with its origin at stage (x, z): the key form the getups use."""
    pose = with_(pose, **changes)
    fwd, up = pose.pop("hips_loc", (0, 0))
    pose["hips_at"] = (x + fwd, z + REST["hips"].translation.z + up)
    return pose


def at(pose, hx, hz, **changes):
    """A key with its hips head at stage (hx, hz)."""
    pose = with_(pose, **changes)
    pose.pop("hips_loc", None)
    pose["hips_at"] = (hx, hz)
    return pose


def _weight(k, spans, ramp=2):
    """1 inside any of `spans` [(first, last)], fading to 0 over `ramp` frames outside."""
    w = 0.0
    for a, b in spans:
        if a <= k <= b:
            return 1.0
        d = a - k if k < a else k - b
        w = max(w, 1 - d / (ramp + 1))
    return max(0.0, w)


GRIP_HANG = Vector((-0.02, 0, -0.064))  # wrist from the corner: hand up over the edge
GRIP_PRESS = Vector((-0.05, 0, 0.085))  # wrist from the corner: leaning on the hand, pushing up
HAND_Y = 0.2  # the hands hold the ledge a little wider than the shoulders


def _hold_ledge(pose, corner, w):
    """Blends both arms (by `w`) into holding the ledge corner (model space)."""
    if w <= 0:
        return pose
    chain = fk(pose, ["hips", "spine"])
    shoulder_z = (chain["spine"] @ REST["spine"].inverted() @ REST["upper_arm.L"]).translation.z
    press = smoothstep(-0.22, 0.06, shoulder_z - corner.z)
    grip = GRIP_HANG.lerp(GRIP_PRESS, press)
    solved = dict(pose)
    for side, s in (("L", 1), ("R", -1)):
        target = corner + grip + Vector((0, s * HAND_Y, 0))
        pole = Vector((-0.5 - 0.6 * press, s * 1.0, -0.4))  # elbows out to the sides, and back as he presses up
        arm_ik(solved, side, target, pole, twist=s * 90)
    for bone in ("upper_arm.L", "forearm.L", "upper_arm.R", "forearm.R"):
        pose[bone] = _lerp(pose.get(bone, 0), solved[bone], w)
    return pose


def _plant_feet(pose, plants, k, root):
    for side, a, b, x in plants:
        w = _weight(k, [(a, b)], ramp=2)
        if w > 0:
            ik = leg_ik(with_(pose, hips=_angles(pose.get("hips", 0))[0]), side, x - root.x, -root.y)
            for bone in (f"thigh.{side}", f"shin.{side}", f"foot.{side}"):
                pose[bone] = _lerp(pose.get(bone, 0), ik[bone], w)
    return pose


# How far above the floor each bone point must stay (bone, meters along it, clearance):
# the body's thickness round its bones, so a tuck or a crouch never sinks into the stage.
CLEARANCE = [("hips", 0.0, 0.08), ("spine", 0.0, 0.08), ("spine", 0.2, 0.09), ("head", 0.05, 0.07), ("head", 0.26, 0.03)] + [
    (f"{bone}.{side}", along, clear)
    for side in "LR"
    for bone, along, clear in (("forearm", 0.0, 0.04), ("forearm", FOREARM, 0.03), ("shin", 0.0, 0.05), ("shin", 0.23, 0.06), ("foot", 0.13, 0.03))
]


def _keep_above_floor(pose, root, skip):
    """Raises the hips so no bone point (but those of the legs in `skip`) is closer
    to the floor than its clearance. Returns how far it raised them."""
    mats = fk(pose)
    need = 0.0
    for bone, along, clear in CLEARANCE:
        if bone.split(".")[-1] in skip and bone.split(".")[0] in ("shin", "foot"):
            continue
        z = (mats[bone] @ Vector((0, along, 0))).z + root.y
        need = max(need, clear - z)
    if need > 0:
        fwd, up = pose["hips_loc"]
        pose["hips_loc"] = (fwd, up + need)
    return need


def getup(n, dist, keys, hands, feet=()):
    """A getup clip of `n` frames that carries the origin `dist` meters onto the stage
    (and up H). `keys` [(frame, stage pose)] run from the hang (frame 1) to standing
    in place (frame n + 1, the first frame of `idle`); `hands` are the frame spans the
    hands hold the ledge, `feet` [(side, first, last, stage x)] the spans a foot is
    planted on the floor."""
    out = []
    for k in range(1, n + 1):
        t = (k - 1) / n
        root = Vector((-0.1 + dist * t, -H + H * t))  # the model origin, in stage coordinates
        pose = _spline(keys, k)
        hx, hz = pose.pop("hips_at")
        pose["hips_loc"] = (hx - root.x, hz - root.y - REST["hips"].translation.z)
        pose = _plant_feet(pose, feet, k, root)
        if hx > 0.05:  # over the stage: nothing sinks into it
            planted_sides = {side for side, a, b, _ in feet if _weight(k, [(a, b)]) > 0}
            if _keep_above_floor(pose, root, planted_sides) > 0:
                pose = _plant_feet(pose, feet, k, root)
        pose = _hold_ledge(pose, Vector((-root.x, 0, -root.y)), _weight(k, hands))
        out.append((k, pose))
    return out


# Hanging: arms up to the corner, body dangling just off the wall, legs loose.
HANG = {
    "hips_loc": (-0.05, -0.2),
    "spine": -6,
    "head": 16,
    "thigh.R": 14,
    "shin.R": -28,
    "foot.R": -38,
    "thigh.L": -4,
    "shin.L": -16,
    "foot.L": -32,
    "upper_arm.R": 165,
    "forearm.R": 10,
    "upper_arm.L": 165,
    "forearm.L": 10,
}
HANG_AT = placed(HANG, -0.1, -H)
HANG_LOOP = 80


def ledge_hang():
    """Loops on the world clock: a slow sway from the hands, breathing, legs trailing."""
    out = []
    corner = Vector((0.1, 0, H))
    for k in range(1, HANG_LOOP + 2):
        a = 2 * math.pi * (k - 1) / HANG_LOOP
        pose = dict(HANG)
        pose["hips_loc"] = (HANG["hips_loc"][0] + 0.012 * math.sin(a), HANG["hips_loc"][1] + 0.004 * math.cos(2 * a))
        pose["spine"] = HANG["spine"] + 1.5 * math.sin(2 * a) - 2 * math.sin(a)
        pose["head"] = HANG["head"] + 3 * math.sin(a - 0.8)
        for side, lag, amp in (("R", 0.7, 6), ("L", 1.3, 5)):
            pose[f"thigh.{side}"] = HANG[f"thigh.{side}"] + amp * math.sin(a - lag)
            pose[f"shin.{side}"] = HANG[f"shin.{side}"] - 0.6 * amp * math.sin(a - lag - 0.6)
        out.append((k, _hold_ledge(pose, corner, 1.0)))
    return out


def ledge_climb():
    """20 frames: pulls up, presses over the edge, plants the near knee on the stage,
    steps up through it and stands 0.8 m in."""
    keys = [
        (1, HANG_AT),
        (5, at(HANG, -0.13, -0.42, hips=-10, spine=-14, head=18, thigh_R=45, shin_R=-95, foot_R=-20, thigh_L=22, shin_L=-50, foot_L=-25)),
        (8, at(HANG, -0.07, -0.1, hips=-35, spine=-18, head=30, thigh_R=110, shin_R=-130, foot_R=-10, thigh_L=42, shin_L=-60, foot_L=-30)),
        (11, at(HANG, 0.12, 0.25, hips=-15, spine=-20, head=24, thigh_R=40, shin_R=-115, foot_R=-60, thigh_L=35, shin_L=-105, foot_L=-30,
                upper_arm_R=30, forearm_R=30, upper_arm_L=20, forearm_L=40)),
        (15, at(HANG, 0.42, 0.42, hips=-4, spine=-14, head=12, thigh_L=85, shin_L=-120, foot_L=-10, upper_arm_R=25, forearm_R=70, upper_arm_L=10, forearm_L=80)),
        (21, placed(S, 0.8)),
    ]
    feet = [("R", 13, 16, 0.42), ("L", 19, 21, 0.67), ("R", 20, 21, 0.93)]
    return getup(20, 0.9, keys, hands=[(1, 9)], feet=feet)


def ledge_roll():
    """25 frames: springs up on the hands, dives over them into a tight forward roll
    (a full turn round the hips, staying low) and pops up 1.5 m in."""
    tuck = dict(thigh_R=128, shin_R=-148, foot_R=-20, thigh_L=122, shin_L=-145, foot_L=-20, spine=-38, head=-8,
                upper_arm_R=35, forearm_R=135, upper_arm_L=30, forearm_L=140)  # hugging the shins
    keys = [
        (1, HANG_AT),
        (4, at(HANG, -0.11, -0.34, hips=-18, spine=-20, head=24, thigh_R=85, shin_R=-125, thigh_L=75, shin_L=-115)),
        (7, at(HANG, 0.08, 0.14, hips=-80, spine=-22, head=30, thigh_R=118, shin_R=-145, thigh_L=112, shin_L=-140)),
        (10, at(HANG, 0.4, 0.12, hips=-150, **tuck)),  # low: `_keep_above_floor` sets the contact
        (14, at(HANG, 0.8, 0.1, hips=-240, **tuck)),
        (18, at(HANG, 1.14, 0.12, hips=-322, **tuck)),
        (21, at(HANG, 1.36, 0.3, hips=-352, spine=-28, head=10, thigh_R=100, shin_R=-140, foot_R=10, thigh_L=96, shin_L=-138, foot_L=10,
                upper_arm_R=40, forearm_R=80, upper_arm_L=30, forearm_L=90)),
        (23, at(S, 1.46, 0.42, hips=-360, spine=-18, head=14, upper_arm_R=30, forearm_R=95, upper_arm_L=20, forearm_L=100)),
        (26, placed(S, 1.5, hips=-360)),
    ]
    feet = [("L", 21, 26, 1.37), ("R", 22, 26, 1.63)]
    return getup(25, 1.6, keys, hands=[(1, 7)], feet=feet)


def ledge_attack():
    """30 frames: hoists over the edge into a low crouch, winds round and sweeps the
    near leg along the floor in a spin, through the hit on 15-18, and stands 1.0 m in."""
    low_r = dict(thigh_L=100, shin_L=-150, foot_L=40, upper_arm_R=-30, forearm_R=20, upper_arm_L=60, forearm_L=30)
    keys = [
        (1, HANG_AT),
        (5, at(HANG, -0.12, -0.38, hips=-15, spine=-15, head=22, thigh_R=60, shin_R=-110, thigh_L=50, shin_L=-100)),
        (8, at(HANG, 0.08, 0.05, hips=-45, spine=-20, head=30, thigh_R=112, shin_R=-140, thigh_L=108, shin_L=-140)),
        (11, at(HANG, 0.4, 0.2, hips=(-20, -160, 0), spine=-12, head=(14, 60, 0), thigh_R=100, shin_R=-140, foot_R=10, **low_r)),
        (14, at(HANG, 0.54, 0.27, hips=(-26, -70, 0), spine=-12, head=(12, 30, 0), thigh_R=78, shin_R=-40, foot_R=-40, **low_r)),
        (16, at(HANG, 0.6, 0.27, hips=(-28, -12, 0), spine=-12, head=(12, 0, 0), thigh_R=86, shin_R=-4, foot_R=-48, **low_r)),
        (18, at(HANG, 0.66, 0.27, hips=(-28, 14, 0), spine=-12, head=(12, -8, 0), thigh_R=86, shin_R=-4, foot_R=-48, **low_r)),
        (22, at(HANG, 0.8, 0.33, hips=(-15, 28, 0), spine=-10, head=(10, -10, 0), thigh_R=60, shin_R=-85, foot_R=-10, **low_r)),
        (26, at(S, 0.95, 0.46, hips=(0, 4, 0), spine=-10, head=8)),
        (31, placed(S, 1.0)),
    ]
    feet = [("L", 26, 31, 0.87), ("R", 27, 31, 1.13)]
    return getup(30, 1.1, keys, hands=[(1, 8)], feet=feet)


ANIMATIONS = {
    "idle": cycle(60, [S, with_(guard(drop=0.056), upper_arm_R=30, upper_arm_L=18)]),
    "walk": cycle(40, [walk(0.12, 0.06, d, 22, i, False) for i, d in enumerate((0.04, 0.025, 0.04, 0.025))]),
    "run": cycle(24, [walk(0.2, 0.12, d, 45, i, True) for i, d in enumerate((0.06, 0.03, 0.06, 0.03))]),
    "jumpsquat": [(1, guard(drop=0.07, lean=-12)), (3, CROUCH)],
    "air": cycle(40, [AIR_S, with_(AIR_S, thigh_R=60, shin_R=-100, thigh_L=10, upper_arm_R=50)]),
    "land": [(1, CROUCH), (3, S)],
    "crouch": cycle(60, [CROUCH, with_(crouch(0.155), upper_arm_R=2)]),
    "hitstun": cycle(20, [FLINCH_S, with_(FLINCH_S, spine=26, upper_arm_R=78, upper_arm_L=-58)]),
    "shield": cycle(40, [SHIELD, with_(SHIELD, upper_arm_R=62, upper_arm_L=57)]),
    "dizzy": cycle(60, [DIZZY, with_(DIZZY, spine=(-15, 0, -10), head=(-20, 0, -15))]),
    "specialfall": cycle(30, [HELPLESS, with_(HELPLESS, upper_arm_R=165, upper_arm_L=125)]),
    "grab_hold": cycle(40, [HOLD, with_(HOLD, upper_arm_R=73, upper_arm_L=68, spine=-7)]),
    "grabbed": cycle(16, [STRUGGLE, with_(STRUGGLE, spine=20, head=15, upper_arm_R=60, forearm_R=60, upper_arm_L=-10)]),
    # Ledge: the hang loops on the world clock; climb 20 frames, roll 25, attack 30
    # (hit 15-18). Every frame is keyed (see "Ledge clips" above).
    "ledge_hang": ledge_hang(),
    "ledge_climb": ledge_climb(),
    "ledge_roll": ledge_roll(),
    "ledge_attack": ledge_attack(),
    # Kunai jab: 16 frames, hit 2-3. Kunai2: 16, hit 2-3. Kunai3: 28, hit 4-6.
    "ninja_kunai": [(1, S), (2, CHOP), (4, CHOP_LOW), (9, CHOP_LOW), (16, S)],
    "ninja_kunai2": [(1, CHOP_LOW), (2, BACKHAND), (4, with_(BACKHAND, upper_arm_L=100)), (9, BACKHAND), (16, S)],
    "ninja_kunai3": [(1, BACKHAND), (3, with_(S, upper_arm_R=140, forearm_R=20)), (4, FINISH), (6, with_(FINISH, upper_arm_R=70)), (16, with_(S, spine=-10)), (28, S)],
    # Palm thrust: 20 frames, hit 3-5. Rising chop: 24, hit 4-10. Sweep: 20, hit 4-6.
    "ninja_palm_thrust": [(1, S), (2, PALM_WIND), (3, PALM), (6, PALM), (12, with_(S, upper_arm_R=50, forearm_R=60)), (20, S)],
    "ninja_rising_chop": [(1, S), (3, RISE_LOW), (4, RISE_FRONT), (8, RISE_TOP), (11, with_(RISE_TOP, upper_arm_R=150)), (16, with_(S, upper_arm_R=120, forearm_R=60)), (24, S)],
    "ninja_sweep": [(1, CROUCH), (3, with_(crouch(0.2), upper_arm_R=-40)), (4, SWEEP), (7, SWEEP), (12, CROUCH), (20, CROUCH)],
    # Dash slice: 34 frames, hit 5-9.
    "ninja_dash_slice": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (4, DASH_TRAIL), (5, DASH_CUT), (9, with_(DASH_CUT, upper_arm_R=80)), (22, with_(S, spine=-14)), (34, S)],
    # Chop (fsmash): charge 8, hit 12-14. Flip kick: charge 6, hit 9-12. Spin kick: charge 5, hit 7-9.
    "ninja_chop": [(1, S), (6, CHOP_WIND), (8, CHOP_WIND), (11, CHOP_MID), (12, CHOP_HIT), (15, CHOP_DOWN), (28, CHOP_DOWN), (42, S)],
    "ninja_flip_kick": [(1, S), (4, FLIP_LOW), (6, FLIP_LOW), (8, with_(FLIP_KICK, thigh_R=90)), (9, FLIP_KICK), (13, FLIP_KICK), (26, with_(S, spine=-6)), (40, S)],
    "ninja_spin_kick": [(1, S), (4, SPIN_WIND), (5, SPIN_WIND), (7, SPIN_FRONT), (10, SPIN_FRONT), (12, SPIN_BACK), (16, SPIN_BACK), (28, CROUCH), (38, S)],
    # Aerials: air spin 30 (3-5, 6-20), flying kick 32 (5-8), back hook 30 (4-7),
    # up flip 28 (4-7), axe kick 38 (10-13).
    "ninja_air_spin": [(1, AIR_S), (3, SPIN_FRONT_A), (6, SPIN_BACK_A), (12, with_(SPIN_BACK_A, upper_arm_R=150)), (20, with_(AIR_TUCK, upper_arm_R=290)), (30, with_(AIR_S, upper_arm_R=380))],
    "ninja_flying_kick": [(1, AIR_S), (3, FLY_WIND), (5, with_(FLY, thigh_R=110)), (6, FLY), (10, FLY), (20, with_(AIR_S, spine=-5)), (32, AIR_S)],
    "ninja_back_hook": [(1, AIR_S), (3, with_(AIR_S, thigh_L=10, shin_L=-120)), (4, HOOK), (8, HOOK), (18, with_(HOOK, thigh_L=-60, shin_L=-50)), (30, AIR_S)],
    "ninja_up_flip": [(1, AIR_S), (3, with_(AIR_S, thigh_R=70, shin_R=-110)), (4, UP_FLIP), (7, UP_FLIP), (16, with_(AIR_S, spine=10)), (28, AIR_S)],
    "ninja_axe_kick": [(1, AIR_S), (6, AXE_WIND), (10, AXE), (14, AXE), (24, with_(AIR_S, spine=0)), (38, AIR_S)],
    # Specials. Shuriken leaves the hand on 10; shadow dash dashes 6-14; smoke bomb
    # teleports on 8; substitution counters 5-24.
    "ninja_shuriken": [(1, S), (3, SHURIKEN_SHOW), (6, SHURIKEN_SHOW), (8, SHURIKEN_WIND), (9, with_(SHURIKEN_WIND, upper_arm_R=55, forearm_R=55)), (10, SHURIKEN_RELEASE), (18, SHURIKEN_RELEASE), (26, S)],
    "ninja_shadow_dash": [(1, S), (3, DASH_CROUCH), (5, DASH_CROUCH), (6, DASH_LEAN), (14, DASH_LEAN), (20, with_(DASH_LEAN, upper_arm_R=40)), (28, with_(S, spine=-10)), (34, S)],
    "ninja_smoke_bomb": [(1, S), (3, SMOKE_CROUCH), (7, SMOKE_CROUCH), (8, SMOKE_RISE), (16, SMOKE_RISE), (26, with_(HELPLESS, upper_arm_R=120)), (40, HELPLESS)],
    "ninja_substitution": [(1, S), (4, SUB_STANCE), (24, SUB_STANCE), (32, with_(SUB_STANCE, upper_arm_R=40)), (40, S)],
    "ninja_substitution_strike": [(1, SUB_STANCE), (3, with_(SUB_STANCE, upper_arm_R=140, forearm_R=20)), (4, SUB_STRIKE), (8, SUB_STRIKE), (16, with_(SUB_STRIKE, upper_arm_R=70)), (28, S)],
    # Grab: 28 frames, 6-7. Dash grab: 36, 8-9. Pummel: 14, hit 3.
    "ninja_grab": [(1, S), (5, REACH), (8, REACH), (16, HOLD), (28, S)],
    "ninja_dash_grab": [(1, walk(0.2, 0.12, 0.06, 45, 0, True)), (7, DASH_REACH), (10, DASH_REACH), (22, with_(HOLD, spine=-12)), (36, S)],
    "ninja_pummel": [(1, HOLD), (3, POMEL), (6, POMEL), (14, HOLD)],
    # Throws release on 11 (f), 14 (b), 11 (u), 12 (d).
    "ninja_throw_forward": [(1, HOLD), (7, with_(HOLD, spine=8, upper_arm_R=40, forearm_R=110)), (11, THROW_F), (17, THROW_F), (28, S)],
    "ninja_throw_back": [(1, HOLD), (8, THROW_B_LOAD), (14, THROW_B), (20, THROW_B), (34, S)],
    "ninja_throw_up": [(1, HOLD), (5, with_(crouch(0.1), upper_arm_R=60, upper_arm_L=60)), (11, THROW_U), (17, THROW_U), (30, S)],
    "ninja_throw_down": [(1, HOLD), (6, with_(HOLD, thigh_R=88, shin_R=-100)), (12, THROW_D), (18, THROW_D), (30, S)],
    # Dodges: spot 26 (3-17), rolls 32 (4-15), air dodge 34-40 (3-18 / 3-25).
    "spotdodge": [(1, S), (3, SIDESTEP), (17, SIDESTEP), (26, S)],
    "roll_f": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "roll_b": [(1, S), (4, BALL), (20, BALL), (28, CROUCH), (32, S)],
    "airdodge": [(1, AIR_S), (4, AIRDODGE), (25, AIRDODGE), (34, AIR_S), (40, AIR_S)],
}


def apply_pose(rig, pose):
    for pb in rig.pose.bones:
        pitch, twist, spread = _angles(pose.get(pb.name, 0))
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
    apply_pose(rig, S)


def log(msg, _start=[time.time()]):
    print(f"[build_ninja {time.time() - _start[0]:6.1f}s] {msg}", flush=True)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, 60
    mesh = ninja_mesh()
    log("mesh")
    rig = build_rig(mesh)
    log("rig and UVs")
    build_actions(rig)
    log("actions")
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    export(GLB_PATH)


if __name__ == "__main__":
    main()
