"""Exports an edited ninja.blend to godot/models/ninja.glb with the settings the
game expects (the same as the fighter's, see build_fighter.export):

    blender --background art/ninja/ninja.blend --python art/ninja/export_ninja.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_ninja import GLB_PATH, export  # noqa: E402

export(GLB_PATH)
