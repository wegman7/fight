"""Exports an edited samurai.blend to godot/models/samurai.glb with the settings the
game expects (the same as the fighter's, see build_fighter.export):

    blender --background art/samurai/samurai.blend --python art/samurai/export_samurai.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_samurai import GLB_PATH, export  # noqa: E402

export(GLB_PATH)
