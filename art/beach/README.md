# Beach backdrop props

Static scenery for the beach behind the stage: two palm trees, a rock and a sailboat.
They are generated in Blender by a script and exported as one `.glb` each to
`godot/models/` (`palm.glb`, `palm2.glb`, `rock.glb`, `sailboat.glb`). `godot/main.tscn`
places copies of them under `Beach`, varying the position, turn and scale of each.

| File | What it is |
|---|---|
| `build_beach.py` | Generates every prop from code (seeded, so rebuilds are identical). Saves `beach.blend` and exports the `.glb`s. |
| `beach.blend` | The Blender file, with the props spread out side by side for viewing. |

```sh
blender --background --factory-startup --python art/beach/build_beach.py
godot --headless --path godot --import
```

Rebuilding overwrites hand edits to `beach.blend`. Unlike the characters, these props
have no rig or animations, and the game never reads them. They're purely decorative.

## How it's built

- **Palms**: a trunk made of rings along a curve that leans out and straightens up,
  tapering, flaring at the base, with a ridge every 0.3 units for leaf scars. The
  fronds arch out and sag under a simple gravity curve, with 30 leaflet pairs each,
  folded into a V and drooping at the tips. The last three fronds are dead, hanging
  and brown. There are coconuts under the crown. `palm` is tall and straight-ish;
  `palm2` is shorter, leans more and droops more.
- **Rock**: a noise-displaced icosphere, flattened, with the bottom cut off and
  flat-shaded so the facets read as stone.
- **Sailboat**: a hull lofted from five cross-sections, a mast and two sails. It's
  only ever seen far out on the water.

Sizes are in Godot units, base at the origin: palms are about 9 to 11 tall, next to
a stage about 14 wide. Leaves and sails are double-sided materials.

## The rest of the backdrop

The sand and water aren't models. They're shaders on plain planes in `main.tscn`:

- `godot/shaders/sand.gdshader` raises low dunes under the stage and slopes the beach
  into the sea past `shore_start` (70 units behind the stage), and darkens wet sand
  near the water level.
- `godot/shaders/ocean.gdshader` uses the depth buffer to tint shallow water (with the
  sand showing through) through to deep blue, draws foam where the water meets
  anything (the beach, rocks, boat hulls), and slowly raises and lowers the surface so
  the waterline washes up and down the slope.

To move the shoreline, change `shore_start` in the sand shader and move the `Ocean`
node's near edge to match. The ocean has to start past the dunes, or their dips
show up as puddles.
