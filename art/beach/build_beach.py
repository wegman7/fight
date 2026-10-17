"""Builds the beach backdrop props (two palm trees, a rock, a sailboat), saves
`beach.blend` next to this script and exports one .glb per prop to `godot/models/`.

    blender --background --factory-startup --python art/beach/build_beach.py

Conventions (see README.md):
- Units are Godot units (the stage is ~14 wide), base of each prop at the origin, z up.
- Props are static scenery: no rig, no animations, nothing the game reads.
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
BLEND_PATH = os.path.join(HERE, "beach.blend")
MODELS = os.path.join(ROOT, "godot", "models")

# name: (base color, roughness, double sided)
MATERIALS = {
    "Bark": ((0.36, 0.28, 0.20, 1), 0.95, False),
    "Frond": ((0.16, 0.38, 0.10, 1), 0.65, True),
    "DeadFrond": ((0.47, 0.37, 0.20, 1), 0.85, True),
    "Coconut": ((0.30, 0.22, 0.10, 1), 0.6, False),
    "Rock": ((0.42, 0.39, 0.35, 1), 0.9, False),
    "Hull": ((0.92, 0.92, 0.90, 1), 0.4, False),
    "Wood": ((0.45, 0.32, 0.20, 1), 0.7, False),
    "Sail": ((0.97, 0.96, 0.92, 1), 0.8, True),
}


def make_materials():
    mats = {}
    for name, (color, rough, two_sided) in MATERIALS.items():
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        if mat.node_tree is None:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = rough
        mat.use_backface_culling = not two_sided
        mats[name] = mat
    return mats


class Builder:
    """Collects faces per material, then becomes one mesh object."""

    def __init__(self, mats):
        self.mats = mats
        self.bm = bmesh.new()
        self.slots = []

    def slot(self, mat):
        if mat not in self.slots:
            self.slots.append(mat)
        return self.slots.index(mat)

    def face(self, points, mat):
        f = self.bm.faces.new([self.bm.verts.new(p) for p in points])
        f.material_index = self.slot(mat)
        return f

    def strip(self, left, right, mat):
        """Quads between two polylines of equal length (a ribbon)."""
        for i in range(len(left) - 1):
            a, b, c, d = left[i], right[i], right[i + 1], left[i + 1]
            if (a - d).length < 1e-6:
                self.face([a, b, c], mat)
            elif (b - c).length < 1e-6:
                self.face([a, b, d], mat)
            else:
                self.face([a, b, c, d], mat)

    def tube(self, rings, mat, cap=True):
        """Quads between consecutive rings of points (each ring closed)."""
        n = len(rings[0])
        verts = [[self.bm.verts.new(p) for p in ring] for ring in rings]
        index = self.slot(mat)
        for r in range(len(rings) - 1):
            for i in range(n):
                j = (i + 1) % n
                f = self.bm.faces.new([verts[r][i], verts[r][j], verts[r + 1][j], verts[r + 1][i]])
                f.material_index = index
        if cap:
            f = self.bm.faces.new(list(reversed(verts[0])))
            f.material_index = index
            f = self.bm.faces.new(verts[-1])
            f.material_index = index

    def sphere(self, center, radius, mat, squash=1.0):
        index = self.slot(mat)
        geom = bmesh.ops.create_uvsphere(self.bm, u_segments=12, v_segments=8, radius=radius)
        for v in geom["verts"]:
            v.co.z *= squash
            v.co += Vector(center)
            for f in v.link_faces:
                f.material_index = index

    def finish(self, name, smooth=True):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for slot in self.slots:
            mesh.materials.append(self.mats[slot])
        if smooth:
            mesh.shade_smooth()
        else:
            mesh.shade_flat()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj


# --- Palm -------------------------------------------------------------------


def palm(mats, name, seed, height, lean, fronds, droop):
    rng = random.Random(seed)
    b = Builder(mats)

    # Trunk: rings along a curve that leans out in +x and straightens toward the top.
    def center(t):
        return Vector((lean * (2 * t - t * t), 0, height * t))

    rings = []
    steps, sides = 70, 14
    for k in range(steps + 1):
        t = k / steps
        p = center(t)
        tangent = (center(min(t + 0.01, 1)) - center(max(t - 0.01, 0))).normalized()
        side = Vector((0, 1, 0))
        normal = side.cross(tangent).normalized()
        # Tapering, a flared base, and a ridge every leaf scar.
        s = t * height
        scar = (s / 0.3) % 1.0
        radius = 0.38 * (1 - 0.45 * t) + 0.32 * math.exp(-t * 16)
        radius *= 1 + 0.07 * (1 - scar) ** 3
        ring = []
        for i in range(sides):
            a = 2 * math.pi * i / sides
            ring.append(p + (normal * math.cos(a) + side * math.sin(a)) * radius)
        rings.append(ring)
    b.tube(rings, "Bark")

    top = center(1)
    b.sphere(top + Vector((0, 0, 0.05)), 0.42, "Frond", squash=0.8)
    for _ in range(6):
        a = rng.uniform(0, 2 * math.pi)
        off = Vector((math.cos(a) * 0.28, math.sin(a) * 0.28, rng.uniform(-0.45, -0.25)))
        b.sphere(top + off, 0.2, "Coconut")

    golden = math.radians(137.5)
    for k in range(fronds):
        dead = k >= fronds - 3
        azimuth = k * golden + rng.uniform(-0.15, 0.15)
        if dead:
            elevation = math.radians(rng.uniform(-75, -55))
            length = rng.uniform(3.0, 3.8)
        else:
            elevation = math.radians(30 - 40 * k / fronds + rng.uniform(-6, 6))
            length = rng.uniform(4.4, 5.4)
        frond(b, top, azimuth, elevation, length, droop, "DeadFrond" if dead else "Frond", rng)
    return b.finish(name)


def frond(b, base, azimuth, elevation, length, droop, mat, rng):
    """A rachis arching out and down under gravity, with leaflets along both sides."""
    out = Vector((math.cos(azimuth), math.sin(azimuth), 0))
    side = Vector((-math.sin(azimuth), math.cos(azimuth), 0))
    up = Vector((0, 0, 1))

    def rachis(s):
        return (base + out * (length * s * math.cos(elevation))
                + up * (length * s * math.sin(elevation) - droop * length * s * s))

    def forward(s):
        return (rachis(min(s + 0.01, 1)) - rachis(max(s - 0.01, 0))).normalized()

    n = 24
    spine = [rachis(i / n) for i in range(n + 1)]
    width = [0.05 * (1 - i / n) + 0.01 for i in range(n + 1)]
    b.strip([p - side * w for p, w in zip(spine, width)], [p + side * w for p, w in zip(spine, width)], mat)

    count = 30
    for i in range(count):
        s = 0.1 + 0.88 * i / (count - 1)
        p = rachis(s)
        f = forward(s)
        across = f.cross(up).normalized() if abs(f.z) < 0.99 else side
        leaf_len = 1.35 * math.sin(math.pi * min(s, 0.95)) ** 0.6 + 0.15
        for sign in (-1, 1):
            # Leaflets point outward and forward, fold down into a V, and sag at the tip.
            d = (across * sign * 0.85 + f * 0.5 - up * 0.3).normalized()
            sag = 0.35 + rng.uniform(-0.1, 0.1)
            pts = [p + d * (leaf_len * u) - up * (sag * leaf_len * u * u) for u in (0, 0.5, 1)]
            w = [0.07, 0.09, 0.0]
            b.strip([q - f * wi for q, wi in zip(pts, w)], [q + f * wi for q, wi in zip(pts, w)], mat)


# --- Rock -------------------------------------------------------------------


def rock(mats, name, seed):
    b = Builder(mats)
    geom = bmesh.ops.create_icosphere(b.bm, subdivisions=3, radius=1.0)
    index = b.slot("Rock")
    offset = Vector((seed * 7.1, seed * 3.3, seed * 5.7))
    for v in geom["verts"]:
        co = v.co.copy()
        bump = 0.28 * noise.noise(co * 1.2 + offset) + 0.09 * noise.noise(co * 3.5 + offset)
        v.co = co * (1 + bump)
        v.co.z = max(v.co.z * 0.65, -0.25)
        v.co.x *= 1.3
    for f in b.bm.faces:
        f.material_index = index
    return b.finish(name, smooth=False)


# --- Sailboat ---------------------------------------------------------------


def sailboat(mats):
    b = Builder(mats)
    # Hull: a few cross-sections, pointed bow at +x.
    sections = []
    for x, half, depth in ((-2.0, 0.55, 0.45), (-1.0, 0.75, 0.55), (0.5, 0.7, 0.55), (1.6, 0.4, 0.45), (2.4, 0.02, 0.3)):
        sections.append([Vector((x, -half, 0.5)), Vector((x, -half * 0.7, 0.5 - depth)),
                         Vector((x, half * 0.7, 0.5 - depth)), Vector((x, half, 0.5))])
    b.tube(sections, "Hull")
    deck = [s[3] for s in sections][::-1] + [s[0] for s in sections]
    b.face(deck, "Wood")
    mast_base, mast_top = Vector((0.2, 0, 0.5)), Vector((0.2, 0, 6.5))
    rings = [[c + Vector((math.cos(a) * 0.06, math.sin(a) * 0.06, 0)) for a in (0, 2.1, 4.2)] for c in (mast_base, mast_top)]
    b.tube(rings, "Wood")
    b.face([Vector((0.25, 0, 1.1)), Vector((-1.9, 0, 1.1)), Vector((0.25, 0, 6.3))], "Sail")
    b.face([Vector((0.3, 0, 1.0)), Vector((0.3, 0, 5.9)), Vector((2.3, 0, 0.8))], "Sail")
    return b.finish("Sailboat", smooth=False)


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
    props = {
        "palm.glb": palm(mats, "Palm", seed=1, height=11.0, lean=2.2, fronds=14, droop=0.55),
        "palm2.glb": palm(mats, "Palm2", seed=2, height=9.0, lean=3.4, fronds=12, droop=0.7),
        "rock.glb": rock(mats, "Rock", seed=3),
        "sailboat.glb": sailboat(mats),
    }
    os.makedirs(MODELS, exist_ok=True)
    for file, obj in props.items():
        export(obj, os.path.join(MODELS, file))
    # Spread the props out so the .blend is easy to look at; exports above used the origin.
    for i, obj in enumerate(props.values()):
        obj.location.x = i * 12
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)


if __name__ == "__main__":
    main()
