"""Builds the stage models (the main stage and the raft used for every soft platform),
saves `stage.blend` next to this script and exports `stage.glb` and `raft.glb` to
`godot/models/`.

    blender --background --factory-startup --python art/stage/build_stage.py

Conventions (see README.md):
- Coordinates in this script are Godot's (x right, y up, z toward the camera), in
  meters; `G()` converts to Blender's z-up when making vertices.
- Each model's walkable top is at y = 0, centered on x = 0, at the width of the
  battlefield's platforms (`STAGE_WIDTH`, `RAFT_WIDTH`). gdext stretches it in x to fit.
- Wood UVs carry the grain for `godot/shaders/wood.gdshader`: u runs along the grain in
  meters and v is the board's index plus 0..1 across it. Stone UVs carry the block's
  index in u for `godot/shaders/stone.gdshader`.
- Everything is seeded, so rebuilding gives the same meshes.
"""

import math
import os
import random

import bmesh
import bpy
from mathutils import Vector, noise

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BLEND_PATH = os.path.join(HERE, "stage.blend")
MODELS = os.path.join(ROOT, "godot", "models")

# Platform widths in meters (sim units * 0.1), from `Stage::battlefield()`.
STAGE_WIDTH = 13.6
RAFT_WIDTH = 3.7

# name: (base color in sRGB, roughness, metallic, double sided). `Planks`, `Driftwood`
# and `Stone` are replaced by shader materials on import (see README.md); their colors
# here are only for viewing in Blender.
MATERIALS = {
    "Planks": ((0.50, 0.35, 0.22, 1), 0.85, 0.0, False),
    "Driftwood": ((0.62, 0.57, 0.50, 1), 0.9, 0.0, False),
    "Stone": ((0.70, 0.60, 0.46, 1), 0.9, 0.0, False),
    "Mortar": ((0.27, 0.23, 0.19, 1), 1.0, 0.0, False),
    "Iron": ((0.16, 0.14, 0.13, 1), 0.55, 0.6, False),
    "Rope": ((0.66, 0.55, 0.38, 1), 0.95, 0.0, False),
    "Vine": ((0.16, 0.33, 0.10, 1), 0.7, 0.0, True),
    "Starfish": ((0.88, 0.42, 0.20, 1), 0.7, 0.0, False),
    "Barnacle": ((0.74, 0.72, 0.66, 1), 0.8, 0.0, False),
}


def G(p):
    """Godot (x, y up, z toward camera) -> Blender (x, y back, z up)."""
    return Vector((p[0], -p[2], p[1]))


def from_blender(v):
    return Vector((v.x, v.z, -v.y))


def linear(c):
    """sRGB -> linear, which is what Blender's color inputs (and the glTF export) hold."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def make_materials():
    mats = {}
    for name, (srgb, rough, metal, two_sided) in MATERIALS.items():
        color = tuple(linear(c) for c in srgb[:3]) + (1,)
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        if mat.node_tree is None:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        mat.use_backface_culling = not two_sided
        mats[name] = mat
    return mats


class Builder:
    """Collects faces per material (with UVs), then becomes one mesh object."""

    def __init__(self, mats):
        self.mats = mats
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.slots = []

    def slot(self, mat):
        if mat not in self.slots:
            self.slots.append(mat)
        return self.slots.index(mat)

    def style(self, faces, mat, smooth, uv_fn=None):
        """Sets material and shading, and UVs from `uv_fn(point, normal)` in Godot coordinates."""
        index = self.slot(mat)
        for f in faces:
            f.material_index = index
            f.smooth = smooth
            if uv_fn:
                f.normal_update()
                n = from_blender(f.normal)
                for loop in f.loops:
                    loop[self.uv].uv = uv_fn(from_blender(loop.vert.co), n)

    def face(self, points, mat, smooth=True, uv_fn=None):
        f = self.bm.faces.new([self.bm.verts.new(G(p)) for p in points])
        self.style([f], mat, smooth, uv_fn)
        return f

    def hull(self, points, mat, smooth=False, uv_fn=None):
        """The convex hull of `points`, for chamfered blocks and boards."""
        verts = [self.bm.verts.new(G(p)) for p in points]
        ret = bmesh.ops.convex_hull(self.bm, input=verts)
        loose = list({v for v in ret["geom_interior"] + ret["geom_unused"] if isinstance(v, bmesh.types.BMVert)})
        bmesh.ops.delete(self.bm, geom=loose, context="VERTS")
        faces = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
        self.style(faces, mat, smooth, uv_fn)
        return faces

    def block(self, lo, hi, mat, bevel, uv_fn=None, jitter=0.0, rng=None):
        """A box from corner `lo` to `hi` with chamfered edges (each corner is cut by a triangle)."""
        points = []
        for corner in range(8):
            signs = [(corner >> axis) & 1 for axis in range(3)]
            c = [hi[a] if s else lo[a] for a, s in enumerate(signs)]
            for keep in range(3):
                p = [c[a] if a == keep else c[a] + (-bevel if signs[a] else bevel) for a in range(3)]
                if jitter:
                    p = [x + rng.uniform(-jitter, jitter) for x in p]
                points.append(Vector(p))
        return self.hull(points, mat, uv_fn=uv_fn)

    def tube(self, rings, mat, smooth=True, uv_fn=None, cap=True):
        """Quads between consecutive rings of points (each ring closed)."""
        n = len(rings[0])
        verts = [[self.bm.verts.new(G(p)) for p in ring] for ring in rings]
        faces = []
        for r in range(len(rings) - 1):
            for i in range(n):
                j = (i + 1) % n
                faces.append(self.bm.faces.new([verts[r][i], verts[r][j], verts[r + 1][j], verts[r + 1][i]]))
        if cap:
            faces.append(self.bm.faces.new(list(reversed(verts[0]))))
            faces.append(self.bm.faces.new(verts[-1]))
        self.style(faces, mat, smooth, uv_fn)
        return faces

    def strip(self, left, right, mat):
        """Quads between two polylines of equal length (a ribbon)."""
        faces = []
        for i in range(len(left) - 1):
            pts = [G(left[i]), G(right[i]), G(right[i + 1]), G(left[i + 1])]
            faces.append(self.bm.faces.new([self.bm.verts.new(p) for p in pts]))
        self.style(faces, mat, True)

    def rope(self, path, radius, mat="Rope"):
        """A three-strand rope along `path`: the radius bulges three times around and the
        bulges twist along the length."""
        sides, pitch = 12, radius * 7.0
        tangent = (path[1] - path[0]).normalized()
        ref = Vector((0, 1, 0)) if abs(tangent.y) < 0.9 else Vector((1, 0, 0))
        normal = tangent.cross(ref).normalized()
        rings, dist = [], 0.0
        for i, p in enumerate(path):
            if i:
                dist += (p - path[i - 1]).length
            tangent = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
            normal = (normal - tangent * normal.dot(tangent)).normalized()
            binormal = tangent.cross(normal)
            phase = dist / pitch * 2 * math.pi
            ring = []
            for s in range(sides):
                a = 2 * math.pi * s / sides
                r = radius * (0.86 + 0.14 * math.cos(3 * a - phase))
                ring.append(p + (normal * math.cos(a) + binormal * math.sin(a)) * r)
            rings.append(ring)
        self.tube(rings, mat)

    def finish(self, name):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for slot in self.slots:
            mesh.materials.append(self.mats[slot])
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj


# --- UV mappings -------------------------------------------------------------


def across(value, lo, hi):
    return min(max((value - lo) / (hi - lo), 0.02), 0.98)


def wood_uv(grain, lo, hi, board):
    """Grain along Godot axis `grain` (0 = x, 2 = z) for a board spanning `lo`..`hi`.
    Faces along the board map v across their width; the end grain gets v up its height."""
    side = 2 if grain == 0 else 0

    def fn(p, n):
        n = [abs(c) for c in n]
        if n[1] >= max(n[0], n[2]):
            return (p[grain], board + across(p[side], lo[side], hi[side]))
        if n[grain] > n[side]:
            return (p[side] * 3.0, board + across(p[1], lo[1], hi[1]))
        return (p[grain], board + across(p[1], lo[1], hi[1]))

    return fn


def stone_uv(block):
    return lambda p, n: (block + 0.5, 0.5)


# --- Pieces ------------------------------------------------------------------


def path_round_rect(x0, x1, y0, y1, z, corner, steps=12):
    """Closed loop around a rectangle in the xy plane at depth z, with rounded corners."""
    pts = []
    corners = [(x1 - corner, y1 - corner, 0), (x0 + corner, y1 - corner, 90),
               (x0 + corner, y0 + corner, 180), (x1 - corner, y0 + corner, 270)]
    for cx, cy, start in corners:
        for k in range(steps + 1):
            a = math.radians(start + 90 * k / steps)
            pts.append(Vector((cx + corner * math.cos(a), cy + corner * math.sin(a), z)))
    # Densify the straight runs so the rope's twist shows along them too.
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n = max(1, int((b - a).length / 0.012))
        out.extend(a.lerp(b, k / n) for k in range(n))
    out.append(out[0])
    return out


def helix(axis_point, axis, radius, start, length, turns, dense=0.012):
    """Points winding around a straight line (`axis` = 0 for x, 1 for y)."""
    n = int(turns * 2 * math.pi * radius / dense)
    pts = []
    for k in range(n + 1):
        t = k / n
        a = turns * 2 * math.pi * t
        along = start + length * t
        u, v = math.cos(a) * radius, math.sin(a) * radius
        if axis == 0:
            pts.append(Vector((along, axis_point[1] + u, axis_point[2] + v)))
        else:
            pts.append(Vector((axis_point[0] + u, along, axis_point[2] + v)))
    return pts


def starfish(b, center, size, turn, rng):
    """A puffy five-armed star stuck flat to a wall facing +z."""
    outline = []
    for k in range(10):
        a = turn + math.pi * k / 5
        r = size * (1.0 if k % 2 == 0 else 0.38) * rng.uniform(0.92, 1.08)
        outline.append((math.cos(a) * r, math.sin(a) * r))
    # Resample the outline so the arms get rounded, swollen sides.
    rings = []
    for level, (scale, lift) in enumerate(((1.0, 0.0), (0.92, 0.035), (0.6, 0.06), (0.25, 0.075))):
        ring = []
        for x, y in outline:
            ring.append(center + Vector((x * scale, y * scale, lift * size / 0.18)))
        rings.append(ring)
    b.tube(rings, "Starfish")


def barnacle(b, base, normal, size):
    """A little volcano-shaped shell sticking out of a surface along `normal`."""
    normal = normal.normalized()
    t = normal.cross(Vector((0, 1, 0)) if abs(normal.y) < 0.9 else Vector((1, 0, 0))).normalized()
    s = normal.cross(t)
    rings = []
    for radius, height in ((1.0, -0.2), (0.9, 0.35), (0.55, 0.8), (0.4, 0.75)):
        rings.append([base + (t * math.cos(a) + s * math.sin(a)) * radius * size + normal * height * size
                      for a in (2 * math.pi * k / 7 for k in range(7))])
    b.tube(rings, "Barnacle", smooth=False)


def vine(b, top, length, rng):
    """A ribbon of hanging seaweed, swaying a little as it falls."""
    n = 14
    phase = rng.uniform(0, 6.28)
    left, right = [], []
    for k in range(n + 1):
        t = k / n
        p = top + Vector((0.12 * math.sin(phase + t * 5.0) * t, -length * t, 0.06 * t + 0.04 * math.sin(phase * 2 + t * 4)))
        w = 0.06 * (1 - 0.6 * t) + 0.01
        tw = 0.6 * math.sin(phase + t * 3)
        d = Vector((math.cos(tw) * w, 0, math.sin(tw) * w))
        left.append(p - d)
        right.append(p + d)
    b.strip(left, right, "Vine")


# --- Main stage ----------------------------------------------------------------


def main_stage(mats):
    """A boardwalk on two courses of sandstone blocks, over a rock that tapers to a
    point underneath, like Battlefield's."""
    rng = random.Random(7)
    b = Builder(mats)
    half = STAGE_WIDTH / 2
    deck_x = half + 0.05
    board_id = 1

    # Deck boards run front to back, nailed onto the stringers below them.
    boards = 30
    pitch = 2 * deck_x / boards
    stringers_z = (2.09, 0.7, -0.7, -2.09)
    for i in range(boards):
        x0 = -deck_x + i * pitch + 0.018
        x1 = x0 + pitch - 0.036
        lo = (x0, -0.11 - rng.uniform(0, 0.01), -2.32 - rng.uniform(-0.05, 0.06))
        hi = (x1, -0.006 - rng.uniform(0, 0.006), 2.32 + rng.uniform(-0.05, 0.07))
        b.block(lo, hi, "Planks", 0.014, wood_uv(2, lo, hi, board_id), jitter=0.003, rng=rng)
        for z in stringers_z:
            for x in (x0 + 0.07, x1 - 0.07):
                zz = z + rng.uniform(-0.03, 0.03)
                b.block((x - 0.018, hi[1] - 0.006, zz - 0.018), (x + 0.018, hi[1] + 0.002, zz + 0.018), "Iron", 0.006)
        board_id += 1

    # Shadowy fill between the stringers, so the gaps between boards look dark, not lit.
    b.block((-half + 0.05, -0.33, -2.0), (half - 0.05, -0.14, 2.0), "Mortar", 0.01)
    for z in stringers_z:
        lo, hi = (-half - 0.02, -0.33, z - 0.11), (half + 0.02, -0.11, z + 0.11)
        b.block(lo, hi, "Planks", 0.02, wood_uv(0, lo, hi, board_id))
        board_id += 1

    # Two courses of sandstone blocks over a dark mortar core that shows in the joints.
    b.block((-half + 0.1, -1.33, -2.07), (half - 0.1, -0.31, 2.07), "Mortar", 0.02)
    block_id = 1
    for course, (y0, y1) in enumerate(((-0.83, -0.33), (-1.33, -0.83))):
        x = -half + 0.02
        while x < half - 0.02:
            length = rng.uniform(0.85, 1.6)
            if half - 0.02 - (x + length) < 0.6:
                length = half - 0.02 - x
            out = rng.uniform(-0.03, 0.03)
            lo = (x + 0.025, y0 + 0.025, -2.15 - out)
            hi = (x + length - 0.025, y1 - 0.025, 2.15 + out)
            b.block(lo, hi, "Stone", 0.055, stone_uv(block_id), jitter=0.012, rng=rng)
            block_id += 1
            x += length

    # The rock underneath: rings tapering to a point, lumpy and flat-shaded so it reads
    # as broken stone. It starts inside the blocks, so the joint is hidden.
    rings_n, sides, depth = 16, 56, 5.6
    rings = []
    for k in range(rings_n + 1):
        t = k / rings_n
        y = -1.2 - depth * t
        shrink = (1 - t) ** 1.35
        ax, az = (half - 0.25) * shrink + 0.15, 1.95 * shrink + 0.15
        exp = 4.0 - 2.0 * t
        ring = []
        for s in range(sides):
            a = 2 * math.pi * s / sides
            c, sn = math.cos(a), math.sin(a)
            x = ax * math.copysign(abs(c) ** (2 / exp), c)
            z = az * math.copysign(abs(sn) ** (2 / exp), sn)
            p = Vector((x, y, z))
            lobes = 1 + t * (0.16 * math.sin(3 * a + 1.0) + 0.09 * math.sin(5 * a + 2.0))
            bump = noise.noise(p * 0.5 + Vector((3.1, 0.0, 7.7))) * 0.45 + noise.noise(p * 1.4) * 0.15
            grow = min(1.0, t * 5)
            radial = Vector((x, 0, z))
            radial = radial.normalized() if radial.length > 1e-6 else Vector((1, 0, 0))
            q = Vector((x * lobes, y, z * lobes)) + radial * bump * grow
            q.y += noise.noise(p * 0.8 + Vector((9.0, 1.0, 4.0))) * 0.35 * grow
            ring.append(q)
        rings.append(ring)
    verts = [[b.bm.verts.new(G(p)) for p in ring] for ring in rings]
    tip = b.bm.verts.new(G(Vector((0.3, -1.2 - depth - 0.9, 0.1))))
    faces = []
    for r in range(rings_n):
        for i in range(sides):
            j = (i + 1) % sides
            # Triangles, split in alternating directions, so every facet is flat.
            a, bb, c, d = verts[r][i], verts[r][j], verts[r + 1][j], verts[r + 1][i]
            if (i + r) % 2:
                faces += [b.bm.faces.new([a, bb, c]), b.bm.faces.new([a, c, d])]
            else:
                faces += [b.bm.faces.new([a, bb, d]), b.bm.faces.new([bb, c, d])]
    for i in range(sides):
        faces.append(b.bm.faces.new([verts[-1][i], verts[-1][(i + 1) % sides], tip]))
    faces.append(b.bm.faces.new(list(reversed(verts[0]))))
    b.style(faces, "Stone", False, stone_uv(0))

    # Stalactite-like spurs hanging off the underside.
    for x, z, length in ((-3.6, 0.6, 1.3), (2.9, -0.3, 1.0), (-1.4, -0.7, 0.8), (4.6, 0.4, 0.7)):
        # Start well inside the rock, where its profile (before the lumps) passes x.
        top_y = -1.2 - depth * (1 - ((abs(x) - 0.15) / (half - 0.25)) ** (1 / 1.35)) + 0.6
        rings, n = [], 7
        for k in range(4):
            t = k / 3
            r = 0.55 * (1 - t) + 0.05
            ring = []
            for s in range(n):
                a = 2 * math.pi * s / n
                jag = 1 + 0.25 * noise.noise(Vector((x * 3 + s, k, z)))
                ring.append(Vector((x + math.cos(a) * r * jag, top_y - length * t, z + math.sin(a) * r * jag * 0.8)))
            rings.append(ring)
        b.tube(rings, "Stone", smooth=False, uv_fn=stone_uv(0))

    # Rope wrapped around both ends of the front stringer, and seaweed hanging off the blocks.
    for x0 in (-half + 0.25, half - 0.6):
        b.rope(helix((0, -0.22, 2.09), 0, 0.15, x0, 0.32, 5), 0.026)
    for x in (-5.9, -4.1, -3.7, -0.9, 1.6, 3.4, 5.2, 5.5):
        vine(b, Vector((x + rng.uniform(-0.2, 0.2), -1.3, 2.12)), rng.uniform(0.8, 2.2), rng)

    # Shore life: starfish and barnacle clusters on the block faces.
    starfish(b, Vector((-4.75, -0.6, 2.19)), 0.22, 0.3, rng)
    starfish(b, Vector((3.95, -1.08, 2.19)), 0.17, 1.1, rng)
    for cx, cy, count in ((-2.2, -1.2, 9), (2.6, -1.15, 7), (6.2, -0.75, 6), (-6.1, -1.22, 5)):
        for _ in range(count):
            p = Vector((cx + rng.uniform(-0.3, 0.3), cy + rng.uniform(-0.05, 0.12), 2.16))
            barnacle(b, p, Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.2), 1)), rng.uniform(0.03, 0.06))

    # Mooring posts at the back corners, with a few turns of rope near the top.
    for side in (-1, 1):
        x, z = side * (half - 0.35), -2.2
        rings = []
        for y, r in ((-1.0, 0.15), (0.38, 0.15), (0.48, 0.13), (0.52, 0.06)):
            rings.append([Vector((x + math.cos(a) * r, y, z + math.sin(a) * r)) for a in (2 * math.pi * k / 12 for k in range(12))])

        def post_uv(p, n, x=x, z=z, board=board_id):
            return (p[1], board + (math.atan2(p[2] - z, p[0] - x) / (2 * math.pi) + 0.5) * 0.96 + 0.02)

        b.tube(rings, "Planks", uv_fn=post_uv)
        board_id += 1
        b.rope(helix((x, 0, z), 1, 0.175, 0.16, 0.14, 4), 0.026)
    return b.finish("Stage")


# --- Raft ----------------------------------------------------------------------


def driftwood_board(b, z_center, half_width, length, x_shift, board, rng):
    """A worn board lofted along x: a rounded-rectangle section that narrows and thins
    toward rounded ends. The top stays at y = 0 except where the ends wear away."""
    sections, sides, half_thick = 20, 16, 0.07
    phase = rng.uniform(0, 6.28)
    rings = []
    for k in range(sections + 1):
        t = k / sections
        x = x_shift - length / 2 + length * t
        end = min(t, 1 - t) * length
        wear = math.sqrt(min(end / 0.14, 1.0))
        w = half_width * (0.55 + 0.45 * wear) * (1 + 0.04 * math.sin(phase + t * 9))
        h = half_thick * (0.5 + 0.5 * wear)
        cz = z_center + 0.025 * math.sin(phase + t * 3.0)
        ring = []
        for s in range(sides):
            a = 2 * math.pi * s / sides
            c, sn = math.cos(a), math.sin(a)
            ring.append(Vector((x, -half_thick + h * math.copysign(abs(sn) ** 0.35, sn) - (half_thick - h),
                                cz + w * math.copysign(abs(c) ** 0.35, c))))
        rings.append(ring)

    def uv(p, n):
        return (p[0], board + 0.5 + 0.47 * max(-1.0, min(1.0, (p[2] - z_center) / half_width)))

    b.tube(rings, "Driftwood", uv_fn=uv)


def raft(mats):
    """Four driftwood boards lashed with rope onto two cross battens."""
    rng = random.Random(11)
    b = Builder(mats)
    half_width = 0.34
    zs = (-1.08, -0.36, 0.36, 1.08)
    for i, z in enumerate(zs):
        driftwood_board(b, z, half_width, RAFT_WIDTH + rng.uniform(-0.12, 0.1), rng.uniform(-0.05, 0.05), i + 1, rng)
    battens_x = (-1.25, 1.25)
    for i, x in enumerate(battens_x):
        lo, hi = (x - 0.09, -0.27, -1.4), (x + 0.09, -0.135, 1.4)
        b.block(lo, hi, "Driftwood", 0.025, wood_uv(2, lo, hi, 10 + i), jitter=0.006, rng=rng)
        for z in (zs[0], zs[-1]):
            for turn in (-0.06, 0.0, 0.06):
                b.rope(path_round_rect(x - 0.115, x + 0.115, -0.29, 0.02, z + turn, 0.045), 0.02)
    return b.finish("Raft")


def export(obj, path):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_animations=False,
        export_cameras=False,
        export_lights=False,
    )


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    models = {"stage.glb": main_stage(mats), "raft.glb": raft(mats)}
    os.makedirs(MODELS, exist_ok=True)
    for file, obj in models.items():
        export(obj, os.path.join(MODELS, file))
    # Lift the raft above the stage so the .blend is easy to look at; exports above used the origin.
    models["raft.glb"].location.z = 3
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)


if __name__ == "__main__":
    main()
