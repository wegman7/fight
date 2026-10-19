"""Exports an edited hobo.blend to godot/models/hobo.glb with the settings the game
expects (the same as the fighter's, see build_fighter.export):

    blender --background art/hobo/hobo.blend --python art/hobo/export_hobo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_hobo import GLB_PATH, export  # noqa: E402

export(GLB_PATH)
