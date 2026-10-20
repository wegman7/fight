"""Renders animation frames of the soldier from `soldier.blend`, to check how the gear
deforms in poses the still previews can't show.

    blender --background art/soldier/soldier.blend --python art/soldier/preview_poses.py -- <outdir>

Writes one image per pose, e.g. `<outdir>/pose_soldier_bayonet_7.png`.
"""

import os
import sys

import bpy

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "/tmp/soldier_poses"
sys.argv = [sys.argv[0], "--", OUT]  # preview reads the outdir from argv

POSES = [
    ("idle", 1), ("crouch", 1), ("run", 1), ("air", 1),
    ("soldier_bayonet", 7), ("soldier_leg_sweep", 7), ("roll_f", 10), ("soldier_grenade", 14),
]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview  # noqa: E402

scene = bpy.context.scene
cam = preview.studio()
rig = bpy.data.objects["Fighter"]
rig.animation_data_create()
os.makedirs(OUT, exist_ok=True)
for action_name, frame in POSES:
    rig.animation_data.action = bpy.data.actions[action_name]
    scene.frame_set(frame)
    preview.render(cam, OUT, f"pose_{action_name}_{frame}", (2.3, -2.4, 1.0), (0, 0, 0.62), 65)
