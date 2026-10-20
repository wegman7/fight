"""Renders preview images of the soldier from `soldier.blend`, so the model can be
inspected without launching Godot.

    blender --background art/soldier/soldier.blend --python art/soldier/preview.py -- <outdir>

Writes `<outdir>/soldier_front.png`, `_three_quarter.png`, `_side.png`, `_back.png` and
close-ups (`_head.png`, `_torso.png`, `_legs.png`, `_rifle.png`). It adds a camera, lights
and a backdrop to a throwaway scene; the .blend on disk is not modified. Animation frames
are rendered by `preview_poses.py`, which reuses `studio()`.
"""

import os
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "/tmp/soldier_preview"


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def studio():
    """A camera, four lights and a dark floor, framed on a 1.2 m character."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 96
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 540
    scene.render.resolution_y = 720
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -0.6

    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.055, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 70
    cam_data.clip_start = 0.01
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    def light(name, loc, energy, size, color=(1, 1, 1)):
        data = bpy.data.lights.new(name, type="AREA")
        data.energy = energy
        data.size = size
        data.color = color
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        scene.collection.objects.link(obj)
        look_at(obj, (0, 0, 0.65))
        return obj

    light("key", (1.6, -1.9, 2.1), 48, 1.4, (1.0, 0.96, 0.9))
    light("fill", (-1.9, -1.4, 1.2), 15, 2.2, (0.72, 0.80, 1.0))
    light("rim", (-0.8, 2.2, 1.9), 38, 1.2, (0.9, 0.94, 1.0))
    light("kicker", (1.9, 1.4, 0.7), 12, 1.0, (1.0, 0.9, 0.8))

    # A dark studio floor, so the boots read.
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, -0.005))
    floor = bpy.context.object
    mat = bpy.data.materials.new("Floor")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.09, 0.09, 0.10, 1)
    bsdf.inputs["Roughness"].default_value = 0.55
    floor.data.materials.append(mat)
    return cam


def render(cam, out, name, loc, look, lens=70):
    scene = bpy.context.scene
    cam.location = loc
    cam.data.lens = lens
    look_at(cam, look)
    scene.render.filepath = os.path.join(out, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)


def main():
    cam = studio()
    target = (0, 0, 0.68)
    os.makedirs(OUT, exist_ok=True)
    # name -> (camera position, look-at target, lens)
    views = {
        "soldier_front": ((3.3, -0.35, 0.95), target, 70),
        "soldier_three_quarter": ((2.6, -2.1, 1.0), target, 70),
        "soldier_side": ((0.0, -3.3, 0.95), target, 70),
        "soldier_back": ((-2.6, 2.1, 1.0), target, 70),
        "soldier_head": ((0.75, -0.62, 1.19), (0.0, 0.0, 1.10), 120),
        "soldier_head_side": ((0.05, -0.9, 1.12), (0.0, 0.0, 1.08), 120),
        "soldier_torso": ((0.85, -1.0, 0.92), (0.0, 0.0, 0.76), 110),
        "soldier_legs": ((0.75, -1.25, 0.42), (0.0, 0.0, 0.33), 100),
        "soldier_rifle": ((0.5, -0.85, 0.62), (0.08, -0.02, 0.42), 110),
    }
    for name, (loc, look, lens) in views.items():
        render(cam, OUT, name, loc, look, lens)


if __name__ == "__main__":
    main()
