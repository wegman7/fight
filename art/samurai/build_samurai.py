"""Builds the samurai: a lean, weathered swordsman in lacquered lamellar armor (laced
cuirass, skirt plates, shoulder guards, a ridged kabuto with a gold crescent) over a
kimono and wide hakama, with tabi and sandals, a katana in his near hand and its
scabbard through his sash. Then his armature and one action per pose name the sim
reports (`Fighter::anim()`). Saves `samurai.blend` next to this script and exports
`godot/models/samurai.glb`.

    blender --background --factory-startup --python art/samurai/build_samurai.py

He stands on the chef's skeleton (same joints, same 1.2 m), so the shapes, pose
helpers and conventions come from `art/fighter/build_fighter.py` (see its README).
On top of it is one bone, `katana`, held in the right (near) fist. Each pose says
where the blade points with `aim`: degrees as seen by the game camera with the
fighter facing right, 0 = forward, 90 = up, 180 = backward.

Materials are physically based, and the ones that need surface detail get seeded,
script-generated image textures (`make_textures`): glTF keeps image textures but not
procedural node trees, so this is what reaches Godot.
"""

import bisect
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "samurai.blend")
GLB_PATH = os.path.join(ROOT, "godot", "models", "samurai.glb")

sys.path.insert(0, os.path.join(ROOT, "art", "fighter"))
import build_fighter as chef  # noqa: E402
from build_fighter import (  # noqa: E402
    AIR,
    ELBOW,
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
    planted,
    ring_band,
    tube,
    uv_ellipsoid,
    walk_key,
    with_,
)

FPS = 60
HEIGHT = 1.2  # FighterParams::SAMURAI.height (12) x SCALE (0.1)

# The chef's bones, minus the pie, plus the katana: it lies along +X through the
# right fist (its hilt through the curled fingers), edge down.
GRIP = Vector((0.0, -0.166, 0.388))
BONES = [b for b in chef.BONES if b[0] != "pie"]
BONES.append(("katana", "forearm.R", tuple(GRIP), tuple(GRIP + Vector((0.12, 0, 0))), FWD))
BONE_NAMES = [b[0] for b in BONES]
BLADE = 0.64  # from the habaki to the tip
TSUBA = 0.05  # the guard, this far in front of the grip

# Material name -> (base color, roughness, metallic). Godot replaces "Body" (the
# headband and the sash) with the player's color; the rest keep their own. The
# textured ones (TEXTURED below) take their color/roughness from images instead.
MATERIALS = {
    "Body": ((0.70, 0.12, 0.12, 1), 0.7, 0.0),
    "Gi": ((0.05, 0.065, 0.16, 1), 0.85, 0.0),
    "Collar": ((0.80, 0.78, 0.72, 1), 0.8, 0.0),
    "Hakama": ((0.055, 0.055, 0.06, 1), 0.85, 0.0),
    "Kote": ((0.04, 0.04, 0.045, 1), 0.8, 0.0),
    "Skin": ((0.58, 0.40, 0.29, 1), 0.5, 0.0),
    "Hand": ((0.55, 0.38, 0.27, 1), 0.55, 0.0),
    "Lip": ((0.45, 0.25, 0.21, 1), 0.45, 0.0),
    "Hair": ((0.02, 0.018, 0.018, 1), 0.45, 0.0),
    "Beard": ((0.045, 0.04, 0.038, 1), 0.6, 0.0),
    "Eye": ((0.80, 0.76, 0.70, 1), 0.08, 0.0),
    "Iris": ((0.10, 0.055, 0.03, 1), 0.08, 0.0),
    "Pupil": ((0.005, 0.005, 0.005, 1), 0.05, 0.0),
    "Tabi": ((0.78, 0.76, 0.72, 1), 0.85, 0.0),
    "Straw": ((0.55, 0.42, 0.24, 1), 0.9, 0.0),
    "Blade": ((0.60, 0.61, 0.62, 1), 0.15, 1.0),
    "Iron": ((0.06, 0.055, 0.05, 1), 0.5, 0.85),
    "Gold": ((0.83, 0.62, 0.26, 1), 0.28, 1.0),
    "Wrap": ((0.03, 0.03, 0.05, 1), 0.65, 0.0),
    "Same": ((0.78, 0.75, 0.66, 1), 0.7, 0.0),
    "Saya": ((0.02, 0.012, 0.01, 1), 0.12, 0.0),
    "Lamellar": ((0.03, 0.025, 0.022, 1), 0.3, 0.0),
    "Lacquer": ((0.018, 0.015, 0.013, 1), 0.18, 0.0),
    "Cord": ((0.17, 0.06, 0.20, 1), 0.6, 0.0),
}
MAT = {name: i for i, name in enumerate(MATERIALS)}
# The cord dyed into the lacing texture matches "Cord" (murasaki-ito: purple silk).
CORD_RGB = MATERIALS["Cord"][0][:3]


# --- Textures ---------------------------------------------------------------
# Every texture is generated here from seeded noise, so a rebuild is identical. They
# are packed into the .blend and embedded in the .glb; Godot extracts them on import.


def noise(h, w, sigma, seed, sy=None):
    """Smooth periodic noise (so it tiles), zero mean, unit deviation. `sigma` is the
    blur in pixels across u (and `sy` along v, if different)."""
    rng = np.random.default_rng(seed)
    n = rng.standard_normal((h, w))
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    sy = sigma if sy is None else sy
    g = np.exp(-2 * np.pi**2 * (sigma**2 * fx**2 + sy**2 * fy**2))
    out = np.real(np.fft.ifft2(np.fft.fft2(n) * g))
    out -= out.mean()
    return out / (out.std() + 1e-9)


def normals(height, strength):
    """Tangent-space normal map (OpenGL convention, as glTF) from a height field in
    pixels: +X along u, +Y along v."""
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * 0.5
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * 0.5
    n = np.dstack((-dx * strength, -dy * strength, np.ones_like(height)))
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n * 0.5 + 0.5


def orm(rough, metal):
    """glTF metallic-roughness image: G = roughness, B = metallic."""
    rough = np.broadcast_to(rough, np.shape(rough))
    return np.dstack((np.ones_like(rough), np.clip(rough, 0, 1), np.clip(np.broadcast_to(metal, rough.shape), 0, 1)))


def to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def image(name, rgb, color):
    """Packs `rgb` (rows from v = 0 up, linear values) into the .blend as a PNG."""
    h, w, _ = rgb.shape
    img = bpy.data.images.new(name, w, h, alpha=False)
    img.colorspace_settings.name = "sRGB" if color else "Non-Color"
    data = to_srgb(rgb) if color else np.clip(rgb, 0, 1)
    rgba = np.dstack((data, np.ones((h, w)))).astype(np.float32)
    img.pixels.foreach_set(rgba.ravel())
    img.file_format = "PNG"
    img.pack()
    return img


def lamellar_texture():
    """One row of kozane (small lacquered scales) laced with silk: u runs along the
    row (one tile = LAMELLAR_TILE m, five scales), v across it, 1 = top. The top of
    each row shows the lacquered scale heads; below them the cords run down to the
    next row (kebiki-odoshi)."""
    h, w = 256, 512
    v = (np.arange(h)[:, None] + 0.5) / h
    u = (np.arange(w)[None, :] + 0.5) / w
    lace_top = 0.6
    # Scales: each overlaps its neighbour, so the height ramps across it and steps
    # down at its edge; its head (the top) is rounded.
    s = (u * 5) % 1.0
    scale_h = 0.6 * s + 0.4 * np.sin(np.pi * s) - 0.15 * np.clip((v - 0.9) / 0.1, 0, 1) * (1 - np.sin(np.pi * s))
    scale_h = scale_h + 0.25 * np.clip((v - lace_top) / 0.08, 0, 1)  # the row bulges above the lacing
    # Cords: 12 per tile, rounded, twisted (diagonal ridges), with dark gaps between.
    c = (u * 12) % 1.0
    across = np.clip(1 - ((c - 0.5) / 0.42) ** 2, 0, 1)
    cord_h = np.sqrt(across) + 0.18 * np.sin(2 * np.pi * (v * 22 + c * 1.3)) * across
    lacing = (v < lace_top) & (v > 0.04)
    # A soft shadow where the cords dive into the row's holes.
    lip = np.exp(-(((v - lace_top) / 0.025) ** 2))
    height = np.where(lacing, 0.9 + 0.8 * cord_h, scale_h)
    height = np.broadcast_to(height, (h, w)) + 0.03 * noise(h, w, 1.5, 11)
    grain = noise(h, w, 40, 12, sy=6)
    lacquer = np.array([0.028, 0.022, 0.019]) * (1 + 0.15 * grain[..., None])
    # The worn top edge of each scale shows the red-brown undercoat through the black.
    worn = np.clip((v - 0.93) / 0.07, 0, 1) * np.clip(0.5 + 0.5 * noise(h, w, 3, 13), 0, 1)
    lacquer = lacquer * (1 - worn[..., None]) + np.array([0.16, 0.05, 0.025]) * worn[..., None]
    silk = np.array(CORD_RGB) * (0.75 + 0.35 * across[..., None]) * (1 + 0.12 * noise(h, w, 2, 14, sy=8)[..., None])
    silk = silk * (0.85 + 0.15 * np.sin(2 * np.pi * (v * 22 + c * 1.3)))[..., None]
    gap = (across < 0.05)[..., None]
    albedo = np.where(lacing[..., None], np.where(gap, lacquer * 0.5, silk), lacquer)
    albedo = albedo * (1 - 0.5 * lip[..., None] * lacing[..., None])
    rough = np.where(lacing, 0.62 + 0.08 * noise(h, w, 2, 15), 0.22 + 0.06 * grain + 0.25 * worn)
    return image("lamellar_color", albedo, True), image("lamellar_normal", normals(height, 3.0), False), image("lamellar_orm", orm(rough, 0.0), False)


def cloth_texture():
    """Plain-weave cloth, one tile per CLOTH_TILE m: a fine weave, slubs in the yarn
    and soft creases. Returns the shared normal map, the indigo kimono's and the
    striped hakama's colors."""
    h = w = 512
    y, x = np.mgrid[0:h, 0:w]
    warp = np.sin(2 * np.pi * x / 6) * np.sign(np.sin(2 * np.pi * y / 12))
    weft = np.sin(2 * np.pi * y / 6) * np.sign(np.sin(2 * np.pi * x / 12 + np.pi / 2))
    weave = 0.5 * (warp + weft)
    slub = noise(h, w, 1.0, 21, sy=12)
    crease = noise(h, w, 30, 22, sy=60)
    height = 0.6 * weave + 0.4 * slub + 6.0 * crease
    normal = normals(height, 0.8)
    fade = noise(h, w, 50, 23)
    fleck = noise(h, w, 1.2, 24)
    indigo = np.array([0.045, 0.06, 0.15])
    gi = indigo * (1 + 0.12 * fade[..., None] + 0.08 * fleck[..., None] + 0.05 * weave[..., None])
    stripe = (np.abs(((x / w) * 10) % 1.0 - 0.5) < 0.05)[..., None]  # sendai-hira: fine stripes
    charcoal = np.array([0.05, 0.05, 0.056])
    hakama = np.where(stripe, charcoal * 1.8, charcoal) * (1 + 0.1 * fade[..., None] + 0.08 * fleck[..., None] + 0.05 * weave[..., None])
    rough = orm(0.82 + 0.06 * slub, 0.0)
    return image("cloth_normal", normal, False), image("cloth_orm", rough, False), image("gi_color", gi, True), image("hakama_color", hakama, True)


def skin_texture():
    """The face, in the head's cylindrical UVs (`head_uv`): sun-darkened, weathered
    skin with pores, crow's feet, a furrowed brow and nasolabial folds, stubble on the
    jaw and an old scar down the right cheek."""
    h = w = 512
    v = (np.arange(h)[:, None] + 0.5) / h
    u = (np.arange(w)[None, :] + 0.5) / w
    phi = (u - 0.5) * 2 * np.pi
    X = phi * 0.075 * np.ones_like(v)  # arc length around the face, m (+ = his left)
    Z = (HEAD_UV_Z0 + v * HEAD_UV_ZSPAN) * np.ones_like(u)

    def seg(ax, az, bx, bz):
        px, pz = X - ax, Z - az
        dx, dz = bx - ax, bz - az
        t = np.clip((px * dx + pz * dz) / (dx * dx + dz * dz), 0, 1)
        return np.hypot(px - t * dx, pz - t * dz)

    def gauss(cx, cz, sx, sz):
        return np.exp(-(((X - cx) / sx) ** 2) - ((Z - cz) / sz) ** 2)

    crease = np.zeros((h, w))
    for s in (1, -1):
        for a in (-0.5, -0.15, 0.2, 0.55):  # crow's feet, fanning out from the eye's corner
            x0, z0 = s * 0.046, 1.071 + 0.004 * a
            crease += np.exp(-((seg(x0, z0, x0 + s * 0.016 * math.cos(a), z0 + 0.016 * math.sin(a)) / 0.0007) ** 2))
        crease += 0.8 * np.exp(-((seg(s * 0.014, 1.058, s * 0.04, 1.06) / 0.0011) ** 2))  # under the eye
        crease += 1.2 * np.exp(-((seg(s * 0.017, 1.044, s * 0.031, 1.0) / 0.0013) ** 2))  # nasolabial fold
        crease += 0.9 * np.exp(-((seg(s * 0.005, 1.088, s * 0.007, 1.104) / 0.0008) ** 2))  # frown lines
        crease += 0.6 * np.exp(-((seg(s * 0.03, 0.995, s * 0.04, 0.985) / 0.0015) ** 2))  # mouth corners
    for z in (1.108, 1.115):  # forehead furrows, under the headband's edge
        crease += 0.7 * np.exp(-((seg(-0.035, z, 0.035, z + 0.001) / 0.0008) ** 2))
    scar = np.exp(-((seg(-0.05, 1.094, -0.026, 1.015) / 0.0016) ** 2))
    pores = noise(h, w, 0.7, 31)
    height = 0.18 * pores - 2.2 * crease + 2.0 * scar
    normal = normals(height, 1.0)

    tan = np.array([0.44, 0.26, 0.16])
    mottle = noise(h, w, 6, 32)
    spots = np.clip(noise(h, w, 2.5, 33) - 2.2, 0, 1)
    albedo = tan * (1 + 0.035 * mottle[..., None]) * (1 - 0.35 * spots[..., None])
    red = np.clip(gauss(0.04, 1.035, 0.02, 0.018) + gauss(-0.04, 1.035, 0.02, 0.018) + 1.2 * gauss(0, 1.043, 0.009, 0.01), 0, 1)
    albedo = albedo * (1 - 0.15 * red[..., None]) + np.array([0.42, 0.16, 0.11]) * 0.15 * red[..., None]
    sockets = gauss(0.03, 1.066, 0.016, 0.01) + gauss(-0.03, 1.066, 0.016, 0.01)
    albedo = albedo * (1 - 0.2 * sockets[..., None])
    jaw = np.clip((1.003 - Z) / 0.012, 0, 1) * np.clip((Z - 0.92) / 0.03, 0, 1) * np.exp(-((phi / 1.25) ** 4))
    lip = np.clip(1 - np.abs(Z - 1.019) / 0.008, 0, 1) * (np.abs(X) < 0.03)
    stubble_mask = np.clip(jaw + lip, 0, 1)
    dots = np.clip(noise(h, w, 0.6, 34) * 0.6 + 0.5, 0, 1)
    stubble = stubble_mask * (0.45 + 0.45 * dots)
    albedo = albedo * (1 - 0.55 * stubble[..., None]) + np.array([0.04, 0.035, 0.035]) * 0.55 * stubble[..., None]
    albedo = albedo * (1 - 0.25 * np.clip(crease, 0, 1)[..., None])
    albedo = albedo * (1 - scar[..., None] * 0.4) + np.array([0.62, 0.40, 0.36]) * 0.4 * scar[..., None]
    rough = 0.6 + 0.1 * stubble + 0.04 * pores - 0.12 * scar
    return image("skin_color", albedo, True), image("skin_normal", normal, False), image("skin_orm", orm(rough, 0.0), False)


def blade_texture():
    """The katana's steel: u along the blade from the habaki (0) to the tip (1), v
    across it from the spine (0) to the edge (1). Mirror-polished ji, the burnished
    shinogi-ji above the ridge line, and the frosty hardened edge below a wavy hamon."""
    h, w = 128, 1024
    v = (np.arange(h)[:, None] + 0.5) / h
    u = (np.arange(w)[None, :] + 0.5) / w
    rng = np.random.default_rng(41)
    wave = 0.04 * np.sin(2 * np.pi * u * 9 + rng.uniform(0, 6)) + 0.025 * np.sin(2 * np.pi * u * 23 + rng.uniform(0, 6))
    wave = wave + 0.012 * noise(1, w, 6, 42)[0][None, :]
    line = 0.72 + wave - 0.06 * np.clip((u - 0.9) / 0.1, 0, 1)  # the boshi turns up into the point
    line = line + 0.1 * np.clip((0.04 - u) / 0.04, 0, 1)  # yakidashi: it starts near the edge
    hamon = 1 / (1 + np.exp(-(v - line) / 0.012))
    nioi = np.exp(-(((v - line) / 0.018) ** 2))
    ridge = SHINOGI_V
    hada = noise(h, w, 4, 43, sy=0.8)  # the forging grain, stretched along the blade
    steel = 0.55 + 0.03 * hada
    color = np.where(v < ridge, 0.5 + 0.02 * hada, steel)
    color = color * (1 - hamon) + (0.82 + 0.03 * hada) * hamon + 0.1 * nioi
    albedo = np.dstack((color * 0.98, color, color * 1.02))
    rough = np.where(v < ridge, 0.06, 0.1) * (1 - hamon) + 0.34 * hamon + 0.02 * np.abs(hada)
    metal = 1.0 - 0.3 * hamon
    return image("blade_color", albedo, True), image("blade_orm", orm(rough, metal), False)


def iron_texture():
    """Forged iron: hammer marks and pitting (normal) and patchy wear (roughness).
    Also used, much fainter, for the lacquer's slightly uneven surface."""
    h = w = 256
    hammer = noise(h, w, 6, 51)
    pits = -np.clip(noise(h, w, 0.8, 52) - 1.6, 0, 3)
    normal = normals(2.0 * hammer + 1.5 * pits, 0.6)
    wear = noise(h, w, 10, 53)
    iron = image("iron_orm", orm(0.5 + 0.12 * wear - 0.1 * pits, 0.85), False)
    lacquer = image("lacquer_orm", orm(0.16 + 0.05 * wear, 0.0), False)
    return image("iron_normal", normal, False), iron, lacquer


def make_textures():
    t = {}
    t["Lamellar"] = dict(zip(("color", "normal", "orm"), lamellar_texture()))
    cloth_n, cloth_r, gi, hakama = cloth_texture()
    t["Gi"] = {"color": gi, "normal": cloth_n, "orm": cloth_r}
    t["Hakama"] = {"color": hakama, "normal": cloth_n, "orm": cloth_r}
    t["Kote"] = {"normal": cloth_n, "orm": cloth_r}
    t["Tabi"] = {"normal": cloth_n}
    t["Collar"] = {"normal": cloth_n}
    t["Skin"] = dict(zip(("color", "normal", "orm"), skin_texture()))
    t["Blade"] = dict(zip(("color", "orm"), blade_texture()))
    iron_n, iron_r, lacquer_r = iron_texture()
    t["Iron"] = {"normal": iron_n, "orm": iron_r}
    t["Lacquer"] = {"normal": iron_n, "orm": lacquer_r, "strength": 0.25}
    t["Saya"] = {"normal": iron_n, "strength": 0.15}
    return t


# UV conventions shared by the mesh and the textures.
LAMELLAR_TILE = 0.08  # m of plate row per lamellar texture tile
CLOTH_TILE = 0.12  # m of cloth per cloth texture tile
HEAD_UV_Z0, HEAD_UV_ZSPAN = 0.82, 0.42  # the head's cylindrical UVs: v = (z - Z0) / span
SHINOGI_V = 0.3  # where the blade's ridge line sits across its v


# --- Model ------------------------------------------------------------------


class Model(chef.Model):
    """The chef's `Model`, on this skeleton and these materials, with UVs: parts laid
    out as they're built (`fixed`), or projected per material at the end (`finish_uvs`)."""

    def __init__(self):
        super().__init__()
        self.uv = self.bm.loops.layers.uv.verify()
        self.fixed = {}  # BMVert -> (u, v)
        self.blob_faces = set()  # metaball surfaces: already facing out

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
        """As the chef's, plus an optional `displace(co) -> co` applied before decimating
        (for folds the metaballs can't make)."""
        mesh = blob.mesh(1.0)
        if displace is not None:
            for v in mesh.vertices:
                v.co = displace(v.co)
        if ratio < 1:
            mesh = decimate(mesh, ratio)
        verts = [self.bm.verts.new(v.co) for v in mesh.vertices]
        for poly in mesh.polygons:
            try:
                self.blob_faces.add(self.bm.faces.new([verts[i] for i in poly.vertices]))
            except ValueError:
                pass
        self.surfaces[name] = BVHTree.FromPolygons([v.co for v in mesh.vertices], [p.vertices for p in mesh.polygons])
        bpy.data.meshes.remove(mesh)
        self.weigh(verts, weights)
        self.paint(verts, mat)
        return verts

    def finish_uvs(self):
        names = list(MATERIALS)
        for f in self.bm.faces:
            mat = names[f.material_index]
            if all(v in self.fixed for v in f.verts):
                uvs = [self.fixed[v] for v in f.verts]
            elif mat == "Skin":
                uvs = unwrap([head_uv(v.co) for v in f.verts], 1.0)
            elif mat == "Hakama" and f.calc_center_median().z < 0.56:
                uvs = unwrap([leg_uv(v.co) for v in f.verts], LEG_U_PERIOD)
            else:
                uvs = box_uv(f, CLOTH_TILE if mat in ("Gi", "Hakama", "Kote", "Tabi", "Collar") else 0.1)
            for loop, uv in zip(f.loops, uvs):
                loop[self.uv].uv = uv


def decimate(mesh, ratio):
    obj = bpy.data.objects.new("Decimating", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.modifiers.new("Decimate", "DECIMATE").ratio = ratio
    dg = bpy.context.evaluated_depsgraph_get()
    out = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(mesh)
    return out


def head_uv(co):
    return (math.atan2(co.y, co.x) / (2 * math.pi) + 0.5, (co.z - HEAD_UV_Z0) / HEAD_UV_ZSPAN)


LEG_U_PERIOD = 4  # tiles around each hakama leg


def leg_uv(co):
    s = 1 if co.y > 0 else -1
    a = math.atan2(co.y - s * HIP[0], co.x)
    return (a / (2 * math.pi) * LEG_U_PERIOD, co.z / CLOTH_TILE)


def unwrap(uvs, period):
    """Keeps a face's u values together across a cylindrical mapping's seam."""
    us = [uv[0] for uv in uvs]
    if max(us) - min(us) > period / 2:
        uvs = [(u + period if u < period / 2 else u, v) for u, v in uvs]
    return uvs


def box_uv(f, tile):
    n = f.normal
    a = max(range(3), key=lambda i: abs(n[i]))
    i, j = [(1, 2), (0, 2), (0, 1)][a]
    return [(v.co[i] / tile, v.co[j] / tile) for v in f.verts]


def plate(m, grid, out, thick, weights, mat, tile=LAMELLAR_TILE):
    """A solid plate (lacquered plates, lamellar rows, crests): `grid[i][r]` is its
    outer surface, columns i along it, rows r across it (r = 0 at the top edge), and
    `out(p)` the direction its thickness is taken inward from. UVs: u along the top
    edge (one unit per `tile` m), v from 1 at the top to 0 at the bottom. Front and back
    shade smooth, the rims sharp."""
    bm = m.bm
    n, rows = len(grid), len(grid[0]) - 1
    arc = [0.0]
    for a, b in zip(grid, grid[1:]):
        arc.append(arc[-1] + (b[0] - a[0]).length)
    F = [[bm.verts.new(p) for p in col] for col in grid]
    B = [[bm.verts.new(p - out(p) * thick) for p in col] for col in grid]
    for i in range(n):
        for r in range(rows + 1):
            m.fixed[F[i][r]] = m.fixed[B[i][r]] = (arc[i] / tile, 1 - r / rows)
    faces, rims = [], []
    for i in range(n - 1):
        for r in range(rows):
            faces.append(bm.faces.new((F[i][r], F[i + 1][r], F[i + 1][r + 1], F[i][r + 1])))
            faces.append(bm.faces.new((B[i][r + 1], B[i + 1][r + 1], B[i + 1][r], B[i][r])))
        rims.append(bm.faces.new((F[i][0], B[i][0], B[i + 1][0], F[i + 1][0])))
        rims.append(bm.faces.new((F[i + 1][rows], B[i + 1][rows], B[i][rows], F[i][rows])))
    for i, flip in ((0, False), (n - 1, True)):
        for r in range(rows):
            quad = (F[i][r], F[i][r + 1], B[i][r + 1], B[i][r])
            rims.append(bm.faces.new(tuple(reversed(quad)) if flip else quad))
    verts = [v for col in F + B for v in col]
    m.weigh(verts, weights)
    for f in faces:
        f.material_index, f.smooth = MAT[mat], True
    for f in rims:
        f.material_index, f.smooth = MAT[mat], False
    return verts


def radial(center):
    """`out` for `plate`: horizontally away from a vertical axis through `center`."""

    def out(p):
        d = Vector((p.x - center.x, p.y - center.y, 0))
        return d.normalized() if d.length > 1e-6 else Vector((1, 0, 0))

    return out


def smooth_loop(values, passes=2):
    for _ in range(passes):
        values = [(values[i - 1] + 2 * values[i] + values[(i + 1) % len(values)]) / 4 for i in range(len(values))]
    return values


# --- Shapes -----------------------------------------------------------------


def head_blob():
    """A lean, weathered face: high cheekbones over hollow cheeks, a square jaw and
    chin, a straight nose with flared nostrils, deep folds beside the mouth."""
    b = Blob(resolution=0.0028)
    b.ell((-0.005, 0, 1.085), (0.088, 0.075, 0.09))  # cranium
    b.ell((0.022, 0, 1.03), (0.072, 0.063, 0.074))  # face and jaw
    b.ell((0.054, 0, 0.98), (0.04, 0.043, 0.024), stiffness=3)  # square chin
    b.cap((-0.012, 0, 0.84), (0.0, 0, 0.99), 0.047)  # neck
    b.cap((0.02, 0, 0.93), (0.045, 0, 0.965), 0.012, stiffness=4)  # Adam's apple and throat
    for s in (1, -1):
        b.ell((0.062, s * 0.042, 1.045), (0.022, 0.024, 0.018), stiffness=3)  # cheekbones
        b.cap((-0.02, s * 0.056, 1.015), (0.06, s * 0.032, 0.968), 0.016, stiffness=3)  # jawline
        b.cap((0.082, s * 0.012, 1.097), (0.076, s * 0.05, 1.103), 0.012, stiffness=3)  # brow ridge
        b.ball((0.075, s * 0.031, 1.072), 0.013, stiffness=4, negative=True)  # eye socket
        b.ell((0.042, s * 0.066, 1.09), (0.012, 0.008, 0.016), stiffness=5, negative=True)  # temples
        b.ell((-0.012, s * 0.078, 1.06), (0.017, 0.01, 0.028), stiffness=4, rot=Quaternion((1, 0, 0), math.radians(-10 * s)))  # ears
        b.ell((-0.006, s * 0.086, 1.062), (0.008, 0.007, 0.015), stiffness=5, negative=True)
        b.ell((0.095, s * 0.0125, 1.04), (0.008, 0.0075, 0.0065), stiffness=4)  # nostril wings
        b.ball((0.1, s * 0.0075, 1.0355), 0.0038, stiffness=6, negative=True)  # nostrils
        b.cap((0.091, s * 0.021, 1.041), (0.085, s * 0.031, 1.004), 0.0026, stiffness=6, negative=True)  # nasolabial fold
    b.cap((0.086, 0, 1.092), (0.103, 0, 1.048), 0.009, stiffness=3)  # nose bridge
    b.ell((0.101, 0, 1.044), (0.012, 0.013, 0.01), stiffness=3)  # tip
    b.cap((0.09, -0.019, 1.006), (0.09, 0.019, 1.006), 0.0035, stiffness=6, negative=True)  # mouth
    b.ell((0.087, 0, 0.998), (0.009, 0.018, 0.006), stiffness=4)  # lower lip
    return b


def hair_blob():
    """Black hair drawn back tight from the forehead, under the helmet."""
    b = Blob(resolution=0.004)
    b.ell((-0.015, 0, 1.1), (0.094, 0.082, 0.088))
    for s in (1, -1):
        b.ell((-0.01, s * 0.088, 1.06), (0.026, 0.02, 0.034), stiffness=4, negative=True)  # room for the ears
    b.ell((0.068, 0, 1.05), (0.052, 0.085, 0.066), stiffness=4, negative=True)  # clear of the face
    b.ell((-0.03, 0, 0.98), (0.08, 0.09, 0.05), stiffness=4, negative=True)  # nape
    return b


def gi_blob():
    """The kimono top under the armor: a lean chest and narrow waist."""
    b = Blob(resolution=0.006)
    b.ell((0.0, 0, 0.775), (0.095, 0.14, 0.11))  # chest
    b.ell((0.005, 0, 0.64), (0.09, 0.122, 0.11))  # waist
    for s in (1, -1):
        b.ell((-0.005, s * 0.09, 0.845), (0.055, 0.07, 0.035))  # trapezius
        b.ell((0.0, s * 0.15, 0.83), (0.052, 0.045, 0.045))  # shoulder seam
        b.ell((-0.055, s * 0.06, 0.77), (0.04, 0.06, 0.07))  # shoulder blades
    return b


def sleeve_blob(s):
    """The kimono's upper sleeve, full under the shoulder guard and bunched where it's
    tucked into the armored sleeve at the elbow."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.0045)
    b.ell((0.0, y - s * 0.005, 0.825), (0.058, 0.058, 0.06))  # deltoid
    b.cap((0, y, SHOULDER[1] - 0.03), (0, y, ELBOW[1] + 0.02), 0.054)
    b.ell((-0.008, y, ELBOW[1] + 0.03), (0.06, 0.058, 0.04), stiffness=3)  # bunched
    return b


def sleeve_folds(s):
    """Creases around the sleeve where it bunches above the elbow."""
    y = s * SHOULDER[0]

    def displace(co):
        d = Vector((co.x, co.y - y, 0))
        if d.length < 1e-6 or co.z > 0.8:
            return co
        a = math.atan2(d.y, d.x)
        k = max(0.0, 1 - abs(co.z - 0.7) / 0.1)
        fold = 0.004 * k * (math.sin(5 * a + 9 * co.z) + 0.6 * math.sin(11 * a - 20 * co.z))
        return co + d.normalized() * fold

    return displace


def kote_blob(s):
    """The armored sleeve (kote) from the elbow to the wrist: close-fitting cloth."""
    y = s * SHOULDER[0]
    b = Blob(resolution=0.004)
    b.cap((0, y, ELBOW[1] + 0.02), (0, y, WRIST[1] + 0.012), 0.039)
    b.ell((-0.006, y, 0.59), (0.04, 0.042, 0.06), stiffness=3)  # forearm
    return b


def hakama_blob(s):
    """One leg of the hakama: wide, flaring toward the hem, with half the seat."""
    y = s * HIP[0]
    b = Blob(resolution=0.005)
    b.ell((-0.02, s * 0.05, 0.53), (0.1, 0.075, 0.08))  # seat and hip
    # Overlapping capsules, each a little wider and lower: straight sides flaring to the hem.
    for top, bottom, r in ((HIP[1] - 0.04, 0.34, 0.07), (0.4, 0.24, 0.076), (0.3, 0.16, 0.084), (0.22, 0.1, 0.092)):
        b.cap((0, y + s * 0.05 * (0.5 - top), top), (0, y + s * 0.05 * (0.5 - bottom), bottom), r)
    b.ell((0.0, y, -0.04), (0.3, 0.3, 0.1), stiffness=4, negative=True)  # flat hem
    return b


def hakama_pleats(s):
    """The hakama's knife pleats: sharp folds around each leg, deepening toward the hem."""
    y = s * HIP[0]

    def displace(co):
        d = Vector((co.x, co.y - (y + s * 0.05 * (0.5 - co.z)), 0))
        if d.length < 1e-6 or co.z > 0.5:
            return co
        a = math.atan2(d.y, d.x)
        depth = 0.0035 + 0.006 * (1 - co.z / 0.5)
        tri = abs((a * 9 / (2 * math.pi)) % 1.0 - 0.5) * 4 - 1  # -1..1 sawtooth around the leg
        sway = 0.002 * math.sin(3 * a + 14 * co.z)
        return co + d.normalized() * (depth * tri + sway)

    return displace


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
    m.blob("head", head_blob(), 0.55, "Skin", by_distance("head", "spine", sharpness=6))
    m.blob("hair", hair_blob(), 0.3, "Hair", "head")
    gi = m.blob("gi", gi_blob(), 0.3, "Gi", by_distance("hips", "spine"))
    for side, s in (("L", 1), ("R", -1)):
        m.blob(f"sleeve.{side}", sleeve_blob(s), 0.3, "Gi", by_distance("spine", f"upper_arm.{side}", f"forearm.{side}", sharpness=6), sleeve_folds(s))
        m.blob(f"kote.{side}", kote_blob(s), 0.3, "Kote", by_distance(f"upper_arm.{side}", f"forearm.{side}", sharpness=6))
        m.blob(f"hand.{side}", chef.hand_blob(s), 0.35, "Hand", f"forearm.{side}")
        m.blob(f"leg.{side}", hakama_blob(s), 0.4, "Hakama", by_distance("hips", f"thigh.{side}", f"shin.{side}", sharpness=6), hakama_pleats(s))
        m.blob(f"tabi.{side}", tabi_blob(s), 0.3, "Tabi", f"foot.{side}")
        sandal(m, s, f"foot.{side}")
        kote_plates(m, s, f"forearm.{side}")
    on_gi = m.weights_near(gi)
    face(m)
    headband(m)
    kabuto(m)
    collar(m, on_gi)
    do_radius = cuirass(m, on_gi)
    obi(m, do_radius)
    kusazuri(m, do_radius)
    for s in (1, -1):
        sode(m, s)
    scabbard(m)
    katana(m)

    m.finish_uvs()
    mesh = bpy.data.meshes.new("SamuraiMesh")
    # Only the hand-built parts: on the decimated metaball surfaces a non-manifold edge
    # can make it flip a whole patch inside out.
    bmesh.ops.recalc_face_normals(m.bm, faces=[f for f in m.bm.faces if f not in m.blob_faces])
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
        m.part(uv_ellipsoid(m.bm, eye, (0.012,) * 3, segments=(20, 12)), "head", "Eye")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.011, 0, -0.001)), (0.0024, 0.007, 0.007), segments=(16, 10)), "head", "Iris")
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.013, 0, -0.001)), (0.0012, 0.0034, 0.0034), segments=(10, 6)), "head", "Pupil")
        # Narrowed: the upper lid comes down to the pupil, the lower one up a little,
        # with a fold of skin over the upper lid.
        m.part(uv_ellipsoid(m.bm, eye + Vector((0.0005, 0, 0.0035)), (0.0128, 0.0138, 0.0098), segments=(20, 12)), "head", "Skin")
        m.part(uv_ellipsoid(m.bm, eye + Vector((-0.001, 0, -0.0105)), (0.0128, 0.0136, 0.006), segments=(20, 10)), "head", "Skin")
        fold = [eye + Vector((0.008, s * y, 0.0095 + 0.002 * (1 - (y / 0.012) ** 2))) for y in (-0.011, -0.005, 0.0, 0.005, 0.011)]
        m.part(tube(m.bm, fold, [0.0012, 0.0018, 0.002, 0.0018, 0.0012], sides=6), "head", "Skin")
        # Brows drawn down toward the nose: a scowl.
        brow = [on_skin(s * y, z, 0.002) for y, z in ((0.01, 1.09), (0.022, 1.096), (0.035, 1.1), (0.052, 1.104))]
        m.part(tube(m.bm, brow, [0.0034, 0.0044, 0.0038, 0.002], sides=8), "head", "Beard")
        # A thin mustache drooping past the corners of the mouth.
        stache = [on_skin(s * y, z, 0.002) for y, z in ((0.002, 1.022), (0.016, 1.018), (0.027, 1.008), (0.031, 0.99))]
        stache.append(stache[-1] + Vector((-0.004, s * 0.002, -0.016)))
        m.part(tube(m.bm, stache, [0.0035, 0.004, 0.0035, 0.003, 0.0018], sides=8), "head", "Beard")
    # A short pointed beard under the lip.
    beard = [on_skin(0, z, 0.002) for z in (0.988, 0.972, 0.958)]
    beard.append(beard[-1] + Vector((0.004, 0, -0.018)))
    m.part(tube(m.bm, beard, [0.006, 0.0075, 0.006, 0.002], sides=8), "head", "Beard")
    m.part(uv_ellipsoid(m.bm, on_skin(0, 1.0085, -0.003), (0.008, 0.017, 0.0045), segments=(14, 8)), "head", "Lip")


def headband(m):
    """The hachimaki (`Body`) tied round the head under the helmet, tilted down at the
    back like the helmet's rim: it shows as a band across the forehead, below the
    peak, and its knotted tails hang out below the neck guard at the back."""
    center = Vector((-0.012, 0, 0))
    sides, rows = 48, (1.103, 1.114, 1.126)
    grid = []
    for j in range(sides):
        a = 2 * math.pi * j / sides
        drop = 0.03 * (1 - math.cos(a)) / 2  # 0 at the forehead, 3 cm lower at the back
        d = Vector((math.cos(a), math.sin(a), 0))
        col = []
        for z in rows:
            r = m.fit(("head", "hair"), center + Vector((0, 0, z - drop)), a) + 0.004
            col.append(m.bm.verts.new(center + d * r + Vector((0, 0, z - drop))))
        grid.append(col)
    for j in range(sides):
        a, b = grid[j], grid[(j + 1) % sides]
        for k in range(len(rows) - 1):
            m.bm.faces.new((a[k], b[k], b[k + 1], a[k + 1]))
    m.part([v for col in grid for v in col], "head", "Body")
    back = grid[sides // 2][0].co + Vector((0.002, 0, -0.012))
    m.part(uv_ellipsoid(m.bm, back, (0.007, 0.015, 0.012)), "head", "Body")
    for s in (1, -1):
        tail = [back + Vector(d) for d in ((-0.002, s * 0.006, -0.004), (-0.012, s * 0.014, -0.05), (-0.035, s * 0.02, -0.12), (-0.05, s * 0.02, -0.19))]
        verts = tube(m.bm, tail, [0.009, 0.012, 0.012, 0.01], sides=8)
        for v in verts:  # flatten into cloth, edge on to the side
            v.co.y = tail[1].y + (v.co.y - tail[1].y) * 0.35
        m.part(verts, "head", "Body")


# The helmet bowl: an ellipse round the head, its rim tilted down at the back.
KABUTO_C = Vector((-0.015, 0, 0))
KABUTO_TOP = 1.208


def kabuto_r(a):
    return 1 / math.sqrt((math.cos(a) / 0.107) ** 2 + (math.sin(a) / 0.098) ** 2)


def kabuto_rim(a):
    return 1.1 + 0.025 * math.cos(a)


def kabuto(m):
    """The kabuto: a black-lacquered bowl of riveted ridged plates (suji-bachi) with a
    gilt crown ring, a peak, a flared neck guard of laced lamellar rows (shikoro) with
    its front edges turned back beside the face (fukigaeshi), a gold crescent crest
    (maedate) and the chin cord."""
    bm = m.bm
    sides, ridges = 192, 32
    rings = []
    for i in range(19):
        ring = []
        for j in range(sides):
            a = 2 * math.pi * j / sides
            rim = kabuto_rim(a)
            eq = rim + 0.014  # the dome starts above the rim band (koshimaki)
            R = kabuto_r(a)
            if i < 16:
                th = (0.08 + 0.92 * i / 15) * math.pi / 2
                ridge = ((1 + math.cos(ridges * a)) / 2) ** 6
                r = R * math.sin(th) * (1 + 0.014 * ridge * min(1.0, math.sin(th) * 2))
                z = eq + (KABUTO_TOP - eq) * math.cos(th)
            else:
                r, z = R * 1.012, eq - (eq - rim) * (i - 15) / 3
            ring.append(bm.verts.new(KABUTO_C + Vector((math.cos(a) * r, math.sin(a) * r, z))))
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(sides):
            bm.faces.new((r0[j], r0[(j + 1) % sides], r1[(j + 1) % sides], r1[j]))
    # The inside, so the bowl has thickness at the rim.
    inner = [bm.verts.new(KABUTO_C + (v.co - KABUTO_C) * Vector((0.95, 0.95, 1)) + Vector((0, 0, 0.002))) for v in rings[-1]]
    for j in range(sides):
        bm.faces.new((rings[-1][j], rings[-1][(j + 1) % sides], inner[(j + 1) % sides], inner[j]))
    top = bm.verts.new(KABUTO_C + Vector((0, 0, KABUTO_TOP - 0.004)))
    for j in range(sides):
        bm.faces.new((rings[0][(j + 1) % sides], rings[0][j], top))
    bowl = [v for r in rings for v in r] + inner + [top]
    m.part(bowl, "head", "Lacquer")
    for f in {f for v in rings[16] for f in v.link_faces}:
        f.smooth = False  # a crisp edge between the dome and the rim band
    # Gilt crown ring (tehen) and rivets along the rim band.
    crown = [KABUTO_C + Vector((math.cos(a) * kabuto_r(a) * 0.2, math.sin(a) * kabuto_r(a) * 0.2, KABUTO_TOP - 0.006)) for a in (2 * math.pi * j / 24 for j in range(25))]
    m.part(tube(bm, crown, [0.004] * len(crown), sides=6), "head", "Gold")
    for j in range(24):
        a = 2 * math.pi * (j + 0.5) / 24
        p = KABUTO_C + Vector((math.cos(a) * kabuto_r(a) * 1.022, math.sin(a) * kabuto_r(a) * 1.022, kabuto_rim(a) + 0.007))
        m.part(uv_ellipsoid(bm, p, (0.0035,) * 3, segments=(8, 5)), "head", "Gold")

    # Peak (mabizashi): out over the brow and down a little, with a gilt edge.
    grid, edge = [], []
    for k in range(17):
        a = -1.15 + 2.3 * k / 16
        d = Vector((math.cos(a), math.sin(a), 0))
        reach = 0.006 + 0.036 * math.sqrt(max(0.0, 1 - (a / 1.15) ** 2))
        base = KABUTO_C + d * kabuto_r(a) * 1.012 + Vector((0, 0, kabuto_rim(a) + 0.003))
        tip = base + (d * math.cos(math.radians(22)) - Vector((0, 0, math.sin(math.radians(22))))) * reach
        grid.append([base, tip])
        edge.append(tip + Vector((0, 0, 0.001)))
    plate(m, grid, lambda p: Vector((0, 0, 1)), 0.004, "head", "Lacquer")
    m.part(tube(bm, edge, [0.0025] * len(edge), sides=6), "head", "Gold")

    # Neck guard (shikoro): four lamellar rows flaring out round the back and sides.
    a0, a1 = 1.0, 2 * math.pi - 1.0
    for k in range(4):
        grid = []
        for j in range(41):
            a = a0 + (a1 - a0) * j / 40
            d = Vector((math.cos(a), math.sin(a), 0))
            r0 = kabuto_r(a) * 1.012 + 0.007 + 0.019 * k
            z0 = kabuto_rim(a) + 0.002 - 0.03 * k
            grid.append([KABUTO_C + d * (r0 + 0.016 * t) + Vector((0, 0, z0 - 0.04 * t)) for t in (0, 0.5, 1)])
        plate(m, grid, radial(KABUTO_C), 0.004, "head", "Lamellar", tile=LAMELLAR_TILE * 0.85)
    # Turn-backs (fukigaeshi): the top rows' front ends folded out beside the face, each
    # with a gilt crest disc.
    for s in (1, -1):
        a = a0 if s > 0 else a1
        d = Vector((math.cos(a), math.sin(a), 0))
        back = Vector((-math.sin(a), math.cos(a), 0)) * s  # along the rim, toward the back
        root = KABUTO_C + d * (kabuto_r(a) * 1.012 + 0.006)
        flap = (d * 0.5 + back * 0.87).normalized()
        grid = [[root + flap * w + Vector((0, 0, kabuto_rim(a) + 0.004 - 0.05 * t - 0.01 * w / 0.035)) for t in (0, 0.5, 1)] for w in (0, 0.018, 0.036)]
        plate(m, grid, lambda p, n=flap.cross(Vector((0, 0, 1))) * -s: n, 0.004, "head", "Lacquer")
        mon_at = root + flap * 0.019 + Vector((0, 0, kabuto_rim(a) - 0.024)) - flap.cross(Vector((0, 0, 1))) * s * 0.003
        rot = (-flap.cross(Vector((0, 0, 1))) * s).to_track_quat("Z", "Y")
        m.part(uv_ellipsoid(bm, mon_at, (0.008, 0.008, 0.0022), rot, segments=(16, 6)), "head", "Gold")

    # Crest (maedate): a gilt crescent standing on a holder at the front of the bowl.
    base_z = kabuto_rim(0) + 0.022
    front = KABUTO_C.x + kabuto_r(0) * 1.02
    lean = math.tan(math.radians(14))
    R, zc = 0.112, base_z + 0.112
    grid = []
    for k in range(25):
        psi = math.radians(-70 + 140 * k / 24)
        width = 0.026 * max(0.0, math.cos(psi / math.radians(70) * math.pi / 2)) ** 0.7 + 0.0015
        outer = Vector((0, R * math.sin(psi), zc - R * math.cos(psi)))
        inner = Vector((0, (R - width) * math.sin(psi), zc - (R - width) * math.cos(psi) + width * 0.25))
        grid.append([p + Vector((front + 0.006 - (p.z - base_z) * lean, 0, 0)) for p in (outer, inner)])
    plate(m, grid, lambda p: Vector((1, 0, lean)).normalized(), 0.003, "head", "Gold")
    holder = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((front - 0.002, 0, base_z - 0.004)) @ Matrix.Diagonal((0.008, 0.03, 0.022, 1)))["verts"]
    m.part(holder, "head", "Gold", smooth=False)

    # Chin cord: from inside the helmet's sides down along the jaw, knotted under the chin.
    knot = Vector((0.045, 0, 0.94))
    for s in (1, -1):
        cord = [Vector((-0.03, s * 0.085, 1.085)), Vector((-0.03, s * 0.075, 1.02)), Vector((-0.005, s * 0.06, 0.965)), Vector((0.03, s * 0.035, 0.945)), knot + Vector((-0.004, s * 0.008, 0))]
        m.part(tube(bm, cord, [0.0026] * 5, sides=6), "head", "Cord")
    m.part(uv_ellipsoid(bm, knot, (0.007, 0.009, 0.006), segments=(10, 6)), "head", "Cord")
    for s in (1, -1):
        m.part(tube(bm, [knot, knot + Vector((0.004, s * 0.008, -0.03)), knot + Vector((0.002, s * 0.01, -0.05))], [0.0026, 0.0024, 0.002], sides=6), "head", "Cord")


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


DO_AXIS = Vector((0.005, 0, 0))
DO_ROWS = [(0.802 - 0.046 * k, 0.054) for k in range(5)]  # (top z, height) of each laced row


def cuirass(m, on_gi):
    """The dō: five rows of laced lamellar round the torso, each lower one a little
    further out (the rows overlap like that), under a solid lacquered breastplate and
    backplate joined by shoulder straps. Returns radius(angle, row) of its rows."""
    n = 96
    angles = [-math.pi + 2 * math.pi * j / n for j in range(n + 1)]  # seam at the back
    radii = []
    prev = None
    for top, h in DO_ROWS:
        zs = [min(top, 0.775), min(top, 0.775) - h / 2, top - h]
        r = [max(max(m.fit(("gi",), DO_AXIS + Vector((0, 0, z)), a) for z in zs), 0.07) + 0.014 for a in angles[:-1]]
        r = smooth_loop(r, 3)
        if prev is not None:
            r = [max(a, b + 0.004) for a, b in zip(r, prev)]
        radii.append(r)
        prev = r
    for (top, h), r in zip(DO_ROWS, radii):
        grid = []
        for j, a in enumerate(angles):
            d = Vector((math.cos(a), math.sin(a), 0))
            rr = r[j % n]
            grid.append([DO_AXIS + d * (rr + 0.007 * t + 0.002 * math.sin(math.pi * t)) + Vector((0, 0, top - h * t)) for t in (0, 0.5, 1)])
        plate(m, grid, radial(DO_AXIS), 0.005, on_gi, "Lamellar")

    def radius(a, row=-1):
        return radii[row][round((a + math.pi) / (2 * math.pi) * n) % n]

    def lacquered(a_mid, half, top, bottom, dip):
        grid = []
        for k in range(17):
            a = a_mid - half + 2 * half * k / 16
            d = Vector((math.cos(a), math.sin(a), 0))
            edge = top - dip * (1 - ((a - a_mid) / half) ** 2)
            col = []
            for t in (0, 0.33, 0.67, 1):
                z = edge + (bottom - edge) * t
                r = max(m.fit(("gi",), DO_AXIS + Vector((0, 0, z)), a) + 0.011, radius(a, 0) - 0.06)
                r = min(r, radius(a, 0) - 0.004) if t == 1 else r
                col.append(DO_AXIS + d * r + Vector((0, 0, z)))
            grid.append(col)
        plate(m, grid, radial(DO_AXIS), 0.005, on_gi, "Lacquer")
        rim = [col[0] + (col[0] - DO_AXIS).normalized() * 0.0005 for col in grid]
        m.part(tube(m.bm, rim, [0.0028] * len(rim), sides=6), "spine", "Gold")

    lacquered(0.0, 0.8, 0.858, DO_ROWS[0][0] - 0.012, 0.014)  # breastplate (munaita)
    lacquered(math.pi, 0.8, 0.868, DO_ROWS[0][0] - 0.012, -0.006)  # backplate (oshitsuke-ita)
    # Shoulder straps (watagami) over the trapezius, front plate to back.
    for s in (1, -1):
        grid = []
        for k in range(9):
            x = 0.07 - 0.15 * k / 8
            col = []
            for dy in (-0.022, 0.0, 0.022):
                y = s * 0.088 + dy
                hit = m.hit("gi", (x, y, 1.2), (0, 0, -1))[0]
                col.append(Vector((x, y, (hit.z if hit else 0.86) + 0.008)))
            grid.append(col)
        plate(m, grid, lambda p: Vector((0, 0, 1)), 0.006, "spine", "Lacquer")
    # Gilt rivets down the front of each lamellar row's ends at the back seam are
    # hidden; a few on the breastplate show.
    for a in (-0.5, -0.25, 0.25, 0.5):
        z = 0.835
        r = m.fit(("gi",), DO_AXIS + Vector((0, 0, z)), a) + 0.017
        m.part(uv_ellipsoid(m.bm, DO_AXIS + Vector((math.cos(a) * r, math.sin(a) * r, z)), (0.004,) * 3, segments=(8, 5)), "spine", "Gold")

    return radius


def obi(m, do_radius):
    """The outer sash (`Body`) tied round the bottom of the cuirass, knotted at the
    front, holding the scabbard."""
    axis = DO_AXIS
    fit = [do_radius(2 * math.pi * j / 48 - math.pi) + 0.012 for j in range(48)]

    def r(a, z):
        return fit[round((a + math.pi) / (2 * math.pi) * 48) % 48] + 0.004 * math.sin(math.pi * (z - 0.577) / 0.05)

    band = ring_band(m.bm, lambda z: axis + Vector((0, 0, z)), r, 0.577, 0.627, rows=4, sides=48)
    m.part(band, "hips", "Body")
    front = axis + Vector((fit[24] + 0.008, -0.01, 0.6))
    m.part(uv_ellipsoid(m.bm, front, (0.014, 0.028, 0.02)), "hips", "Body")
    for dy, dz in ((0.03, -0.11), (-0.02, -0.09)):  # the knot's two hanging ends
        end = [front + Vector((0.004, 0, -0.01)), front + Vector((0.012, dy * 0.6, dz * 0.5)), front + Vector((0.02, dy, dz))]
        verts = tube(m.bm, end, [0.012, 0.014, 0.013], sides=8)
        for v in verts:
            v.co.x = front.x + 0.012 + (v.co.x - front.x - 0.012) * 0.35
        m.part(verts, "hips", "Body")


def kusazuri(m, do_radius):
    """The skirt of armor: seven panels of four laced rows each, hung on cords below
    the cuirass and flaring out over the hakama. The lower rows follow the thighs, so
    the panels swing up with a kick."""
    panels, gap = 7, 0.05
    tops = [0.548 - 0.042 * k for k in range(4)]

    def weights(p):
        t = max(0.0, min(1.0, (0.55 - p.z) / 0.17))
        left = max(0.0, min(1.0, 0.5 + p.y / 0.14))
        return {"hips": 1 - 0.8 * t, "thigh.L": 0.8 * t * left, "thigh.R": 0.8 * t * (1 - left)}

    for i in range(panels):
        a_mid = 2 * math.pi * i / panels
        half = math.pi / panels - gap / 2
        for k, top in enumerate(tops):
            grid = []
            for j in range(11):
                a = a_mid - half + 2 * half * j / 10
                d = Vector((math.cos(a), math.sin(a), 0))
                r0 = do_radius(a) + 0.01 + 0.011 * k
                grid.append([DO_AXIS + d * (r0 + 0.007 * t + 0.002 * math.sin(math.pi * t)) + Vector((0, 0, top - 0.05 * t)) for t in (0, 0.5, 1)])
            plate(m, grid, radial(DO_AXIS), 0.005, weights, "Lamellar")
        # The hanging cords (yurugi-ito) from the cuirass down to the panel.
        for j in range(5):
            a = a_mid - half * 0.8 + 1.6 * half * j / 4
            d = Vector((math.cos(a), math.sin(a), 0))
            cord = [DO_AXIS + d * (do_radius(a) + 0.006) + Vector((0, 0, 0.585)), DO_AXIS + d * (do_radius(a) + 0.009) + Vector((0, 0, 0.54))]
            verts = tube(m.bm, cord, [0.0032, 0.0032], sides=6)
            m.weigh(verts, weights)
            m.paint(verts, "Cord")


def sode(m, s):
    """A shoulder guard (sode): a lacquered top plate over six laced rows, curved round
    the outside of the upper arm and hanging from the shoulder."""
    y = s * SHOULDER[0]
    axis = Vector((0, y, 0))
    rows = [(0.882, 0.034, "Lacquer")] + [(0.858 - 0.036 * k, 0.044, "Lamellar") for k in range(6)]
    for k, (top, h, mat) in enumerate(rows):
        grid = []
        for j in range(13):
            psi = math.radians(-58 + 116 * j / 12)
            d = Vector((math.sin(psi), s * math.cos(psi), 0))
            r = 0.082 + 0.004 * k
            grid.append([axis + d * (r + 0.006 * t + 0.0015 * math.sin(math.pi * t)) + Vector((0, 0, top - h * t)) for t in (0, 0.5, 1)])
        weights = {f"upper_arm.{'L' if s > 0 else 'R'}": 1.0} if k else {f"upper_arm.{'L' if s > 0 else 'R'}": 0.8, "spine": 0.2}
        plate(m, grid, radial(axis), 0.005, lambda p, w=weights: w, mat)
    # Gilt rivets along the top plate.
    for psi in (-40, 0, 40):
        p = axis + Vector((math.sin(math.radians(psi)), s * math.cos(math.radians(psi)), 0)) * 0.087 + Vector((0, 0, 0.866))
        m.part(uv_ellipsoid(m.bm, p, (0.0035,) * 3, segments=(8, 5)), f"upper_arm.{'L' if s > 0 else 'R'}", "Gold")


def kote_plates(m, s, bone):
    """The armored sleeve's iron splints (shino) along the outside of the forearm, and
    the plate over the back of the hand (tekko)."""
    y = s * SHOULDER[0]
    axis = Vector((0, y, 0))
    for psi in (-34, 0, 34):
        grid = []
        for z in (0.615, 0.57, 0.525, 0.48):
            col = []
            for w in (-0.007, 0.007):
                a = math.radians(psi) + w / 0.045
                r = 0.043 - 0.004 * (0.615 - z) / 0.135
                col.append(axis + Vector((math.sin(a), s * math.cos(a), 0)) * r + Vector((-0.004, 0, z)))
            grid.append(col)
        plate(m, grid, radial(axis), 0.004, bone, "Iron")
    grid = []
    for z in (0.448, 0.425, 0.4):
        col = []
        for x in (-0.03, -0.01, 0.01, 0.03):
            col.append(Vector((x, y + s * (0.023 + 0.006 * math.cos(x / 0.03 * 1.2) - 0.004 * (0.448 - z) / 0.05), z)))
        grid.append(col)
    plate(m, grid, lambda p: Vector((0, s, 0)), 0.004, bone, "Lacquer")
    m.part(uv_ellipsoid(m.bm, Vector((0.0, y + s * 0.03, 0.425)), (0.008, 0.002, 0.008), segments=(10, 5)), bone, "Gold")


def sandal(m, s, bone):
    """A straw sandal under the tabi, with its dark thong."""
    y = s * HIP[0]
    bm = m.bm
    sole = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((0.045, y, 0.006)) @ Matrix.Diagonal((0.23, 0.085, 0.012, 1)))["verts"]
    m.part(sole, bone, "Straw", smooth=False)
    toe = Vector((0.13, y - s * 0.01, 0.03))
    for side in (1, -1):
        strap = [toe + Vector((-0.005, 0, 0.012)), Vector((0.06, y + side * 0.04, 0.05)), Vector((0.03, y + side * 0.045, 0.02))]
        m.part(tube(bm, strap, [0.005, 0.006, 0.005], sides=6), bone, "Kote")


def scabbard(m):
    """The empty scabbard (saya) through the sash on the far (left) hip, its mouth
    forward and up, sloping down behind outside the skirt plates: black lacquer, a
    horn mouth, the knob its purple cord is tied to, and an iron end cap."""
    mouth, end = Vector((0.15, 0.175, 0.61)), Vector((-0.43, 0.31, 0.36))
    axis = (end - mouth).normalized()
    length = (end - mouth).length
    points = [mouth + axis * length * t for t in (0, 0.02, 0.5, 0.97, 1.0)]
    m.part(tube(m.bm, points, [0.019, 0.02, 0.019, 0.018, 0.012], sides=14), "hips", "Saya")
    m.part(tube(m.bm, [points[0] - axis * 0.004, points[1] + axis * 0.012], [0.022, 0.022], sides=14), "hips", "Iron")  # koiguchi
    m.part(tube(m.bm, [end - axis * 0.03, end + axis * 0.004], [0.02, 0.014], sides=14), "hips", "Iron")  # kojiri
    knob = mouth + axis * 0.07 + Vector((0, 0.021, 0))
    m.part(uv_ellipsoid(m.bm, knob, (0.012, 0.006, 0.008), segments=(10, 6)), "hips", "Saya")
    cord = [knob, knob + Vector((0.02, 0.006, 0.01)), knob + Vector((0.05, -0.01, 0.0)), knob + Vector((0.06, -0.03, -0.04)), knob + Vector((0.05, -0.03, -0.08))]
    m.part(tube(m.bm, cord, [0.003] * 5, sides=6), "hips", "Cord")


def katana(m):
    """The sword along +X from the grip: the iron pommel cap, the silk-wrapped hilt over
    ray skin with its gilt ornaments, the iron guard between gilt washers, the collar,
    and a curved shinogi-zukuri blade (ridge line, polished planes, hamon) ending in a
    curved point."""
    bm = m.bm

    def at(x, z=0.0, y=0.0):
        return GRIP + Vector((x, y, z))

    def rod(x0, x1, r, mat, sides=16):
        m.part(tube(bm, [at(x0), at(x1)], [r, r], sides=sides), "katana", mat)

    rod(-0.128, -0.116, 0.0158, "Iron")  # kashira (pommel cap)
    rod(-0.116, TSUBA - 0.008, 0.0135, "Same")  # ray skin under the wrap
    rod(TSUBA - 0.012, TSUBA - 0.003, 0.0158, "Iron")  # fuchi (collar)
    # The cord wrap: two opposite spirals, which leave diamonds of ray skin between them.
    for hand in (1, -1):
        turns, n = 6, 144
        spiral = [at(-0.112 + (TSUBA - 0.124) * i / n, 0.0148 * math.sin(hand * 2 * math.pi * turns * i / n),
                     0.0148 * math.cos(hand * 2 * math.pi * turns * i / n)) for i in range(n + 1)]
        m.part(tube(bm, spiral, [0.0038] * len(spiral), sides=6), "katana", "Wrap")
    for side in (1, -1):  # menuki under the wrap, either side
        m.part(uv_ellipsoid(bm, at(-0.035, 0.002, side * 0.0155), (0.012, 0.005, 0.003), segments=(10, 6)), "katana", "Gold")
    for x, r in ((TSUBA - 0.0035, 0.018), (TSUBA + 0.0075, 0.018)):  # seppa (washers)
        rod(x - 0.0012, x + 0.0012, r, "Gold", sides=20)
    # The guard: an iron disc with a raised rim, two gilt inlays.
    tsuba = bmesh.ops.create_cone(bm, cap_ends=True, segments=40, radius1=0.033, radius2=0.033, depth=0.006,
                                  matrix=Matrix.Translation(at(TSUBA + 0.002)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))["verts"]
    m.part(tsuba, "katana", "Iron")
    rim = [at(TSUBA + 0.002, 0.033 * math.cos(2 * math.pi * k / 40), 0.033 * math.sin(2 * math.pi * k / 40)) for k in range(41)]
    m.part(tube(bm, rim, [0.0028] * 41, sides=6), "katana", "Iron")
    for side in (1, -1):
        m.part(uv_ellipsoid(bm, at(TSUBA + 0.002, 0.018, side * 0.0035), (0.006, 0.006, 0.0012), segments=(10, 5)), "katana", "Gold")
    m.part(tube(bm, [at(TSUBA + 0.009, 0.001), at(TSUBA + 0.026, 0.002)], [0.0125, 0.0118], sides=12), "katana", "Gold")  # habaki
    # The blade. Its section, from the spine round to the edge and back: (across the
    # flat, along the width) fractions, and v for the texture (0 spine, 1 edge). Each
    # face strip has its own vertices so the ridges stay sharp and the planes smooth.
    section = [(0.0, 0.5, 0.0), (-0.32, 0.43, 0.08), (-0.5, 0.22, SHINOGI_V), (0.0, -0.5, 1.0), (0.5, 0.22, SHINOGI_V), (0.32, 0.43, 0.08)]
    base, steps, point = TSUBA + 0.01, 48, 0.07
    rings = []
    for i in range(steps + 1):
        t = i / steps
        x = base + (BLADE - 0.01) * t
        bend = 0.035 * t * t
        width, thick = 0.026 - 0.007 * t, 0.0068 - 0.003 * t
        k = max(0.0, (x - (base + BLADE - 0.01 - point)) / point)  # into the point
        ring = []
        for a, w, v in section:
            ww = w
            if k > 0 and w < 0.5:
                # The edge sweeps up to meet the spine (fukura); the ridge goes with it.
                ww = 0.5 - (0.5 - w) * math.sqrt(max(0.0, 1 - k * k))
            ring.append((at(x, bend + ww * width, a * thick * (1 - 0.85 * k)), v))
        rings.append((ring, x / (BLADE + TSUBA)))
    verts = []
    for j in range(len(section)):
        j2 = (j + 1) % len(section)
        strip = [[bm.verts.new(r[j][0]), bm.verts.new(r[j2][0])] for r, _ in rings]
        for (r, u), (a, b) in zip(rings, strip):
            m.fixed[a], m.fixed[b] = (u, r[j][1]), (u, r[j2][1])
        for (a0, b0), (a1, b1) in zip(strip, strip[1:]):
            f = bm.faces.new((a0, b0, b1, a1))
            f.material_index, f.smooth = MAT["Blade"], True
        verts += [v for pair in strip for v in pair]
    cap = bm.faces.new([bm.verts.new(p) for p, _ in rings[0][0]])
    for v in cap.verts:
        m.fixed[v] = (0.0, 0.5)
    verts += list(cap.verts)
    cap.material_index = MAT["Blade"]
    m.weigh(verts, "katana")


def materials():
    tex = make_textures()
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
        t = tex.get(name, {})
        if "color" in t:
            node = tree.nodes.new("ShaderNodeTexImage")
            node.image = t["color"]
            tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
        if "orm" in t:
            node = tree.nodes.new("ShaderNodeTexImage")
            node.image = t["orm"]
            split = tree.nodes.new("ShaderNodeSeparateColor")
            tree.links.new(node.outputs["Color"], split.inputs["Color"])
            tree.links.new(split.outputs["Green"], bsdf.inputs["Roughness"])
            tree.links.new(split.outputs["Blue"], bsdf.inputs["Metallic"])
        if "normal" in t:
            node = tree.nodes.new("ShaderNodeTexImage")
            node.image = t["normal"]
            nmap = tree.nodes.new("ShaderNodeNormalMap")
            nmap.inputs["Strength"].default_value = t.get("strength", 1.0)
            tree.links.new(node.outputs["Color"], nmap.inputs["Color"])
            tree.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
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


def pitch(value):
    return value[0] if isinstance(value, tuple) else value


def turned(pose, twist):
    """`pose` turned about the vertical by `twist` degrees: negative turns him toward
    the camera when facing right (positive when facing left, as the model is turned
    180 degrees then). Spins go past 360 like the sword's."""
    return with_(pose, hips=(pitch(pose.get("hips", 0)), twist, 0))


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
FOCUS = planted(with_(S, hips_loc=(-0.03, -0.08), spine=4, head=-4, upper_arm_R=118, forearm_R=62, aim=96, upper_arm_L=112, forearm_L=70), 0.22, -0.22)
FOCUS_LOAD = with_(FOCUS, spine=10, head=-8, upper_arm_R=150, forearm_R=50, aim=160, upper_arm_L=140, forearm_L=60)
FOCUS_CUT = lunge(with_(S, spine=-24, head=18, upper_arm_R=100, forearm_R=0, aim=2, upper_arm_L=90, forearm_L=10), 0.16, 0.12, 0.46, -0.26)
FOCUS_THROUGH = with_(FOCUS_CUT, upper_arm_R=70, upper_arm_L=62, aim=-35)
VAULT_CROUCH = with_(crouch(0.24), spine=-20, head=18, upper_arm_R=-30, forearm_R=20, aim=-160, upper_arm_L=30, forearm_L=60)
VAULT_LEAP = with_(AIR_S, spine=-15, head=10, upper_arm_R=-20, forearm_R=30, aim=-150, thigh_R=20, shin_R=-20, foot_R=-20, thigh_L=-30, shin_L=-30, foot_L=-30)
VAULT_TUCK = with_(AIR_TUCK, spine=8, head=-6, upper_arm_R=160, forearm_R=20, aim=100, upper_arm_L=60, forearm_L=60)
VAULT_DROP = with_(AIR_S, thigh_R=40, shin_R=-60, thigh_L=25, shin_L=-50, upper_arm_R=60, forearm_R=40, aim=20)
CYCLONE_LOW = with_(crouch(0.14), spine=-8, upper_arm_R=-20, forearm_R=40, aim=-170, upper_arm_L=40, forearm_L=60)
CYCLONE = {
    "spine": 0,
    "head": -4,
    "upper_arm.R": 90,
    "forearm.R": 0,
    "upper_arm.L": -70,
    "forearm.L": 10,
    "thigh.R": 40,
    "shin.R": -60,
    "thigh.L": -5,
    "shin.L": -10,
    "foot.L": -30,
    "aim": 0,
}
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


# --- Ledge clips ------------------------------------------------------------
# The sim hangs him with his origin LEDGE_HANG_X (0.1 m) outside the edge and the top
# of his hurtbox (HEIGHT) level with the platform, so in model space the ledge corner
# is at (0.1, HEIGHT). Getups slide the origin linearly from there to standing inside
# the edge (`Fighter::ledge_getup_pos`). The getups are designed in "stage space"
# (the corner at the origin, the stage at x > 0, z < 0) and solved with IK every
# frame, then converted to model space by subtracting where the sim has put him.

L_UPPER, L_FORE = SHOULDER[1] - ELBOW[1], WRIST[1] - GRIP.z + (ELBOW[1] - WRIST[1])  # shoulder->elbow, elbow->grip
L_THIGH, L_SHIN = HIP[1] - 0.30, 0.30 - 0.07
CORNER = (0.1, HEIGHT)  # model space, while hanging
HANG_GRIP = (-0.014, 0.018)  # where the fists sit, from the corner (stage space)
HANG_AIM = 5  # the blade lies along the platform while he grips the edge


def rot2(p, deg):
    """(x, z) turned counter-clockwise as seen by the camera (the pose convention)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def limb_ik(root, target, l1, l2, bend):
    """Two-bone IK in the camera plane. Angles are the pose convention's world angles
    for a hanging limb (0 = straight down, + = forward). `bend` +1 folds the lower
    segment counter-clockwise (elbows), -1 clockwise (knees)."""
    dx, dz = target[0] - root[0], target[1] - root[1]
    d = min(max(math.hypot(dx, dz), abs(l1 - l2) + 1e-3), l1 + l2 - 1e-4)
    aim = math.degrees(math.atan2(dx, -dz))
    if aim < -90:
        aim += 360
    a1 = math.degrees(math.acos((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    a2 = math.degrees(math.acos((l2 * l2 + d * d - l1 * l1) / (2 * l2 * d)))
    return (aim - bend * a1, aim + bend * a2)


def hips_head(pose):
    fwd, up = pose.get("hips_loc", (0, 0))
    return (fwd, chef.BONES[0][2][2] + up)


def shoulder_at(pose):
    h = hips_head(pose)
    sp = rot2((0, 0.68 - 0.55), pitch(pose.get("hips", 0)))
    sh = rot2((0, SHOULDER[1] - 0.68), pitch(pose.get("hips", 0)) + pitch(pose.get("spine", 0)))
    return (h[0] + sp[0] + sh[0], h[1] + sp[1] + sh[1])


def hip_joint_at(pose):
    h = hips_head(pose)
    j = rot2((0, HIP[1] - 0.55), pitch(pose.get("hips", 0)))
    return (h[0] + j[0], h[1] + j[1])


def arm_to(pose, side, target):
    """Relative upper arm and forearm angles that put the `side` fist on `target`."""
    upper, fore = limb_ik(shoulder_at(pose), target, L_UPPER, L_FORE, +1)
    chain = pitch(pose.get("hips", 0)) + pitch(pose.get("spine", 0))
    return (upper - chain, fore - upper)


def leg_to(pose, side, target, toe):
    """Relative thigh, shin and foot angles that put the ankle on `target`, knee
    forward, the foot at world angle `toe` (0 = level, - = toes down)."""
    thigh, shin = limb_ik(hip_joint_at(pose), target, L_THIGH, L_SHIN, -1)
    hp = pitch(pose.get("hips", 0))
    return (thigh - hp, shin - thigh, toe - shin)


def pchip(ts, ys, t):
    """Monotone cubic interpolation: no overshoot, flat where neighbors are equal."""
    if t <= ts[0]:
        return ys[0]
    if t >= ts[-1]:
        return ys[-1]
    n = len(ts)
    h = [ts[i + 1] - ts[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    k = bisect.bisect_right(ts, t) - 1
    s = (t - ts[k]) / h[k]
    h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
    return h00 * ys[k] + h10 * h[k] * m[k] + h01 * ys[k + 1] + h11 * h[k] * m[k + 1]


def lerp_pose(a, b, t):
    out = {}
    for key in set(a) | set(b):
        va, vb = a.get(key, 0), b.get(key, 0)
        if key == "hips_loc" or isinstance(va, tuple) or isinstance(vb, tuple):
            va = va if isinstance(va, tuple) else (va, 0, 0)
            vb = vb if isinstance(vb, tuple) else (vb, 0, 0)
            if key == "hips_loc":
                va, vb = (va + (0,))[:2], (vb + (0,))[:2]
            out[key] = tuple(x + (y - x) * t for x, y in zip(va, vb))
        else:
            out[key] = va + (vb - va) * t
    return out


# The hang, in stage space: where everything is while he hangs (the start of every
# getup). Fists on the corner, arms nearly straight, body close to the wall, head up.
HANG = {
    "P": (-0.14, -HEIGHT + 0.55 - 0.06),  # pelvis (the hips bone's head)
    "hips": 0.0, "spine": -2.0, "head": 16.0,
    "Rfoot": (-0.12, -HEIGHT + 0.035, -50.0), "Lfoot": (-0.17, -HEIGHT + 0.02, -65.0),
    "Rleg": 1.0, "Lleg": 1.0,  # IK weight (0 = the explicit angles below)
    "Rlimbs": (0.0, 0.0, 0.0), "Llimbs": (0.0, 0.0, 0.0),
    "Rgrip": 1.0, "Lgrip": 1.0,  # IK weight of each fist onto the corner
    "Rarm": (S["upper_arm.R"], S["forearm.R"]), "Larm": (S["upper_arm.L"], S["forearm.L"]),
    "aim": float(HANG_AIM),
}


def getup(frames, inward, keys, end=S, blend=3):
    """A getup clip: `keys` are (frame, changes) in stage space, each carrying forward
    the previous one's values (frame 0 is the hang). The sim moves his origin from
    (-0.1, -HEIGHT) at frame 0 to (inward, 0) at `frames`, evenly per frame."""
    full, cur = [], dict(HANG)
    for frame, changes in [(0, {})] + keys:
        cur = dict(cur, **changes)
        full.append((frame, cur))
    ts = [f for f, _ in full]

    def value(name, f):
        first = full[0][1][name]
        if isinstance(first, tuple):
            return tuple(pchip(ts, [k[name][i] for _, k in full], f) for i in range(len(first)))
        return pchip(ts, [k[name] for _, k in full], f)

    out = []
    for f in range(1, frames + 1):
        o = (-0.1 + (inward + 0.1) * f / frames, -HEIGHT + HEIGHT * f / frames)
        local = lambda p: (p[0] - o[0], p[1] - o[1])  # noqa: E731
        P = local(value("P", f))
        pose = {"hips_loc": (P[0], P[1] - 0.55), "hips": value("hips", f), "spine": value("spine", f), "head": value("head", f)}
        for side in "RL":
            fx, fz, toe = value(side + "foot", f)
            ik = leg_to(pose, side, local((fx, fz)), toe)
            w = value(side + "leg", f)
            limbs = value(side + "limbs", f)
            pose[f"thigh.{side}"], pose[f"shin.{side}"], pose[f"foot.{side}"] = (a + (b - a) * w for a, b in zip(limbs, ik))
            grip = local(HANG_GRIP)
            ik = arm_to(pose, side, grip)
            w = value(side + "grip", f)
            arm = value(side + "arm", f)
            pose[f"upper_arm.{side}"], pose[f"forearm.{side}"] = (a + (b - a) * w for a, b in zip(arm, ik))
        pose["aim"] = value("aim", f)
        t = max(0.0, (f - (frames - blend)) / blend)
        out.append((f, lerp_pose(pose, end, t * t * (3 - 2 * t))))
    return out


def ledge_hang():
    """80 frames on the world clock, looping: a slow sway and breathing while he hangs,
    the fists fixed on the corner."""
    keys = []
    for f in range(1, 82):
        ph = 2 * math.pi * (f - 1) / 80
        P = (HANG["P"][0] + 0.1 + 0.008 * math.sin(ph), HANG["P"][1] + HEIGHT + 0.004 * math.sin(2 * ph))
        pose = {"hips_loc": (P[0], P[1] - 0.55), "hips": 2.0 * math.sin(ph), "spine": -2 + 1.5 * math.sin(2 * ph), "head": 16 + 3 * math.sin(ph + 0.6)}
        for side, (fx, fz, toe), sway in (("R", HANG["Rfoot"], 0.0), ("L", HANG["Lfoot"], 1.3)):
            target = (fx + 0.1 + 0.014 * math.sin(ph + sway), fz + HEIGHT + 0.006 * math.sin(ph + sway))
            pose[f"thigh.{side}"], pose[f"shin.{side}"], pose[f"foot.{side}"] = leg_to(pose, side, target, toe + 6 * math.sin(ph + sway))
            pose[f"upper_arm.{side}"], pose[f"forearm.{side}"] = arm_to(pose, side, (CORNER[0] + HANG_GRIP[0], CORNER[1] + HANG_GRIP[1]))
        pose["aim"] = HANG_AIM
        keys.append((f, pose))
    return keys


def arm_world(upper, fore, hips, spine):
    """Explicit arm angles given the upper arm's world angle."""
    return (upper - hips - spine, fore)


DECK = 0.07  # ankle height standing on the platform (stage space)
FINAL_CLIMB = 0.8  # LEDGE_CLIMB_IN
FINAL_ROLL = 1.5  # LEDGE_ROLL_IN
FINAL_ATTACK = 1.0  # LEDGE_ATTACK_IN
S_FEET = (0.14, -0.14)  # the stance's front (R) and back (L) feet

# Ledge climb: 20 frames. Hoists himself up the wall with the fists on the corner,
# brings his near knee up onto the platform, lets go and steps up into his guard.
LEDGE_CLIMB = getup(20, FINAL_CLIMB, [
    (1, {"P": (-0.14, -0.69)}),
    (4, {"P": (-0.135, -0.52), "spine": 4.0, "head": 8.0, "Rfoot": (-0.15, -1.0, -40.0)}),
    (7, {"P": (-0.125, -0.26), "hips": -6.0, "spine": 2.0, "head": 4.0, "Rfoot": (-0.13, -0.62, -20.0), "Lfoot": (-0.15, -0.95, -60.0)}),
    (8.5, {"Rfoot": (-0.08, 0.06, -10.0)}),
    (10, {"P": (-0.06, 0.0), "hips": -32.0, "spine": -16.0, "head": 32.0, "Rfoot": (0.13, DECK, 0.0), "Lfoot": (-0.14, -0.6, -50.0)}),
    (11.5, {"Lfoot": (-0.07, 0.08, -10.0), "Rgrip": 1.0, "Lgrip": 1.0}),
    (13, {"P": (0.2, 0.24), "hips": -20.0, "spine": -12.0, "head": 20.0, "Lfoot": (0.2, 0.16, 0.0), "Rgrip": 0.0, "Lgrip": 0.0, "aim": 20.0}),
    (15, {"P": (0.45, 0.4), "hips": -8.0, "spine": -8.0, "head": 10.0, "Lfoot": (FINAL_CLIMB + S_FEET[1], DECK, 0.0), "Rfoot": (0.13, DECK, 0.0)}),
    (17, {"P": (0.66, 0.46), "Rfoot": (0.58, 0.17, 0.0)}),
    (19, {"P": (0.78, 0.495), "hips": 0.0, "spine": -6.0, "head": 6.0, "Rfoot": (FINAL_CLIMB + S_FEET[0], DECK, 0.0), "aim": 35.0}),
    (20, {"P": (FINAL_CLIMB, 0.5)}),
])

# Ledge roll: 25 frames. A quick hoist, a vault over his hands into a tight forward
# roll (a full turn about the pelvis, staying low), and up into his guard.
TUCK = (120.0, -140.0, -10.0)  # thigh, shin, foot (relative)
LEDGE_ROLL = getup(25, FINAL_ROLL, [
    (1, {"P": (-0.14, -0.68)}),
    (3, {"P": (-0.135, -0.5), "spine": 4.0, "head": 6.0}),
    (5, {"P": (-0.125, -0.22), "hips": -6.0, "spine": -4.0, "head": 4.0, "Rfoot": (-0.14, -0.62, -30.0), "Lfoot": (-0.17, -0.66, -50.0)}),
    (6.5, {"P": (-0.08, 0.03), "hips": -30.0, "spine": -30.0, "head": 10.0, "Rleg": 0.4, "Lleg": 0.4, "Rlimbs": TUCK, "Llimbs": TUCK, "aim": -10.0}),
    (8, {"P": (0.06, 0.2), "hips": -70.0, "spine": -55.0, "head": -20.0, "Rleg": 0.0, "Lleg": 0.0, "Rgrip": 0.0, "Lgrip": 0.0,
         "Rarm": (70.0, 100.0), "Larm": (70.0, 100.0), "aim": -190.0}),
    (10.5, {"P": (0.34, 0.3), "hips": -150.0, "aim": -270.0}),
    (13, {"P": (0.64, 0.3), "hips": -235.0, "aim": -355.0}),
    (15.5, {"P": (0.94, 0.3), "hips": -310.0, "aim": -368.0}),
    (18, {"P": (1.2, 0.3), "hips": -352.0, "spine": -40.0, "head": 0.0, "aim": -362.0, "Rfoot": (FINAL_ROLL + 0.12, DECK, 0.0), "Lfoot": (FINAL_ROLL - 0.16, DECK, 0.0)}),
    (19.5, {"P": (1.32, 0.31), "hips": -365.0, "spine": -22.0, "head": 16.0, "Rleg": 1.0, "Lleg": 1.0, "Rarm": (20.0, 60.0), "Larm": (10.0, 50.0), "aim": -360.0}),
    (22.5, {"P": (1.45, 0.44), "hips": -362.0, "spine": -10.0, "head": 8.0, "Rfoot": (FINAL_ROLL + S_FEET[0], DECK, 0.0), "Lfoot": (FINAL_ROLL + S_FEET[1], DECK, 0.0),
            "Rarm": (S["upper_arm.R"], S["forearm.R"]), "Larm": (S["upper_arm.L"], S["forearm.L"]), "aim": -330.0}),
    (25, {"P": (FINAL_ROLL, 0.5), "hips": -360.0, "spine": -6.0, "head": 6.0, "aim": 35.0 - 360}),
], end=with_(S, hips=-360, aim=35 - 360))

# Ledge attack: 30 frames, hit 15-18 at (0.6, 0.6) from his origin. Hoists up, steps
# onto the platform with the blade low in front (gedan), and cuts up from the floor in
# a rising slash, then recovers into his guard.
LEDGE_ATTACK = getup(30, FINAL_ATTACK, [
    (1, {"P": (-0.14, -0.68)}),
    (3, {"P": (-0.135, -0.5), "spine": 4.0, "head": 8.0, "Rfoot": (-0.15, -1.0, -40.0)}),
    (6, {"P": (-0.125, -0.24), "hips": -6.0, "spine": 2.0, "head": 4.0, "Rfoot": (-0.13, -0.6, -20.0), "Lfoot": (-0.15, -0.95, -60.0)}),
    (7.5, {"Rfoot": (-0.08, 0.06, -10.0)}),
    (9, {"P": (-0.05, 0.03), "hips": -30.0, "spine": -16.0, "head": 30.0, "Rfoot": (0.16, DECK, 0.0), "Lfoot": (-0.13, -0.55, -50.0)}),
    (10.5, {"Lfoot": (-0.06, 0.08, -10.0), "Rgrip": 1.0, "Lgrip": 1.0, "aim": float(HANG_AIM)}),
    (12, {"P": (0.2, 0.26), "hips": -22.0, "spine": -18.0, "head": 24.0, "Lfoot": (0.24, DECK, 0.0), "Rgrip": 0.0, "Lgrip": 0.0,
          "Rarm": arm_world(35.0, 5.0, -22.0, -18.0), "Larm": arm_world(-30.0, 40.0, -22.0, -18.0), "aim": -18.0}),
    (14, {"P": (0.4, 0.27), "hips": -20.0, "spine": -20.0, "head": 24.0, "Rfoot": (0.74, DECK, 0.0),
          "Rarm": arm_world(38.0, 4.0, -20.0, -20.0), "Larm": arm_world(-45.0, 30.0, -20.0, -20.0), "aim": -16.0}),
    (15, {"P": (0.46, 0.28), "Rarm": arm_world(46.0, 4.0, -20.0, -20.0), "aim": -12.0}),
    (16, {"P": (0.5, 0.29), "hips": -18.0, "spine": -17.0, "Rarm": arm_world(56.0, 3.0, -18.0, -17.0), "aim": 0.0}),
    (17, {"P": (0.53, 0.31), "hips": -15.0, "spine": -12.0, "head": 20.0, "Rarm": arm_world(68.0, 2.0, -15.0, -12.0), "aim": 16.0}),
    (18, {"P": (0.56, 0.34), "hips": -11.0, "spine": -6.0, "head": 14.0, "Rarm": arm_world(84.0, 0.0, -11.0, -6.0), "Larm": arm_world(-50.0, 30.0, -11.0, -6.0), "aim": 36.0}),
    (19, {"P": (0.6, 0.38), "hips": -8.0, "spine": 0.0, "head": 8.0, "Rarm": arm_world(118.0, 1.0, -8.0, 0.0), "aim": 66.0, "Lfoot": (0.3, 0.12, 0.0)}),
    (21, {"P": (0.66, 0.43), "hips": -4.0, "spine": 6.0, "head": 0.0, "Rarm": arm_world(165.0, 4.0, -4.0, 6.0), "aim": 108.0}),
    (23, {"Lfoot": (FINAL_ATTACK + S_FEET[1], DECK, 0.0), "Rarm": arm_world(168.0, 8.0, -4.0, 6.0), "aim": 118.0}),
    (25, {"P": (0.88, 0.46), "Rfoot": (0.74, DECK, 0.0)}),
    (26.5, {"Rfoot": (0.95, 0.15, 0.0), "hips": 0.0, "spine": -6.0, "head": 6.0, "Rarm": arm_world(80.0, 40.0, 0.0, -6.0), "Larm": (S["upper_arm.L"], S["forearm.L"]), "aim": 70.0}),
    (28, {"P": (0.98, 0.495), "Rfoot": (FINAL_ATTACK + S_FEET[0], DECK, 0.0), "Rarm": (S["upper_arm.R"], S["forearm.R"]), "aim": 35.0}),
    (30, {"P": (FINAL_ATTACK, 0.5)}),
])

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
    # Ledge: the hang loops on the world clock; the getups are keyed every frame from
    # IK (see `getup`): climb 20 frames, roll 25, attack 30 (hit 15-18).
    "ledge_hang": ledge_hang(),
    "ledge_climb": LEDGE_CLIMB,
    "ledge_roll": LEDGE_ROLL,
    "ledge_attack": LEDGE_ATTACK,
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
    # Specials. Focus cut: charge frame 9 (held while charging), hit 13-16.
    "focus_cut": [(1, S), (6, FOCUS), (9, FOCUS), (11, FOCUS_LOAD), (12, with_(FOCUS_CUT, upper_arm_R=140, upper_arm_L=130, aim=70)), (13, FOCUS_CUT), (16, FOCUS_THROUGH), (30, FOCUS_THROUGH), (46, S)],
    # Vault: crouches 1-6, leaps on 7, back down on 22. The sim turns him around on 15,
    # so he twists toward the camera until 14 and from the mirrored side after.
    "vault": [(1, S), (4, VAULT_CROUCH), (6, VAULT_CROUCH), (7, VAULT_LEAP), (11, VAULT_TUCK), (14, turned(VAULT_TUCK, -65)), (15, turned(VAULT_TUCK, 65)), (18, VAULT_TUCK), (22, VAULT_DROP), (34, AIR_S)],
    # Vault strike: hangs 1-3, drops and hits 4-22.
    "vault_strike": [(1, VAULT_TUCK), (3, STAB_WIND), (4, STAB), (22, STAB), (36, AIR_S)],
    # Cyclone: rises 4-20, both sides hit 4-7 then 8-18, then helpless. Four turns
    # toward the camera, fast while it hits.
    "cyclone": [(1, S), (3, CYCLONE_LOW), (4, turned(CYCLONE, 30)), (8, turned(CYCLONE, 360)), (12, turned(CYCLONE, 720)), (18, turned(CYCLONE, 1260)),
                (28, turned(with_(CYCLONE, upper_arm_R=150, aim=120), 1440)), (46, turned(HELPLESS, 1440))],
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
