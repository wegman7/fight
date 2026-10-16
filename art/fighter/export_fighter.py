"""Exports an edited fighter.blend to godot/models/fighter.glb with the settings
the game expects (see build_fighter.export):

    blender --background art/fighter/fighter.blend --python art/fighter/export_fighter.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_fighter import GLB_PATH, export  # noqa: E402

export(GLB_PATH)
