# Stage models

The platforms of the battlefield stage, generated in Blender by a script and exported
to `godot/models/`:

- `stage.glb`: the main stage. A plank boardwalk nailed onto stringers, over two courses
  of sandstone blocks, over a lumpy rock that tapers to a point underneath (like
  Battlefield's). Mooring posts with rope at the back corners, rope wound round the front
  stringer's ends, seaweed hanging off the blocks, starfish and barnacles on them.
- `raft.glb`: every soft platform. Four worn driftwood boards lashed with rope onto two
  cross battens.

| File | What it is |
|---|---|
| `build_stage.py` | Generates both models from code (seeded, so rebuilds are identical). Saves `stage.blend` and exports the `.glb`s. |
| `stage.blend` | The Blender file, with the raft lifted above the stage for viewing. |

```sh
blender --background --factory-startup --python art/stage/build_stage.py
godot --headless --path godot --import
```

Rebuilding overwrites hand edits to `stage.blend`. The models are purely visual: the
sim's `Stage::battlefield()` decides where the platforms are and how they collide.

## Rules the game relies on

- The walkable top of each model is at its origin (y = 0), centered on x = 0.
- Each is built at the width of its platform in `Stage::battlefield()` (`STAGE_WIDTH`
  13.6 and `RAFT_WIDTH` 3.7 meters). `build_stage` in `gdext/src/lib.rs` stretches it in
  x to the platform's actual width (`STAGE_MODEL_WIDTH`, `RAFT_MODEL_WIDTH`), so keep
  those constants equal to the script's if either changes. It also turns every other
  raft around, so the copies don't look identical.

## Textures

There are no image textures. The wood and stone are shaders, swapped in for the Blender
materials of the same name by each model's `.import` file (`_subresources`), the way the
pug's fur is:

| Blender material | Godot material | Shader |
|---|---|---|
| `Planks` | `godot/models/stage_planks.tres` | `godot/shaders/wood.gdshader` |
| `Driftwood` | `godot/models/stage_driftwood.tres` (paler, more weathered) | `godot/shaders/wood.gdshader` |
| `Stone` | `godot/models/stage_stone.tres` | `godot/shaders/stone.gdshader` |

The other materials (`Mortar`, `Iron`, `Rope`, `Vine`, `Starfish`, `Barnacle`) are plain
colors from the script.

The shaders read the UVs the script writes, so keep them when adding pieces:

- **Wood**: u runs along the grain in meters; v is the board's index plus 0..1 across
  the board. The index gives each board its own tint, knot and bleaching; the fraction
  darkens worn edges. Use `wood_uv()` for blocks, or set them by hand as the posts and
  driftwood boards do.
- **Stone**: u is the block's index (`stone_uv()`), for a slight tint per block; 0 for
  the rough rock. Everything else (sediment layers, pits, algae toward the tip, sand dust
  on upward faces) comes from the model-space position.

Both shaders bump the normal from the screen-space slope of a procedural height, so
they need no tangents. If the re-import ever drops the material swap, the stage shows
the flat Blender colors: check the `_subresources` entries in `stage.glb.import` and
`raft.glb.import`.
