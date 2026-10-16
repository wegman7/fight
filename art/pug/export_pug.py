"""Exports an edited pug.blend to godot/models/pug.glb with the settings the game
expects (the same as the fighter's, see build_fighter.export):

    blender --background art/pug/pug.blend --python art/pug/export_pug.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_pug import GLB_PATH, export  # noqa: E402

export(GLB_PATH)
