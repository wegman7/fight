"""Exports an edited soldier.blend to godot/models/soldier.glb with the settings the
game expects (the same as the fighter's, see build_fighter.export):

    blender --background art/soldier/soldier.blend --python art/soldier/export_soldier.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_soldier import GLB_PATH, export  # noqa: E402

export(GLB_PATH)
