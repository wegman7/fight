# Fighter model

A basic jointed mannequin, rigged and animated in Blender, exported to
`godot/models/fighter.glb` for the game.

| File | What it is |
|---|---|
| `build_fighter.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `fighter.blend` and exports the `.glb`. |
| `fighter.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_fighter.py` | Exports `fighter.blend` to `godot/models/fighter.glb` with the settings the game expects. |

## Two ways to change it

**Edit the script** (poses are a few lines of numbers each), then rebuild:

```sh
blender --background --factory-startup --python art/fighter/build_fighter.py
```

**Or edit `fighter.blend` in Blender**, save, then export:

```sh
blender --background art/fighter/fighter.blend --python art/fighter/export_fighter.py
```

Choose one approach per change. Running `build_fighter.py` regenerates `fighter.blend` from scratch
and **overwrites hand edits**. If you start editing the `.blend` by hand, from then
on use only the export script, or move your edits into the script.

In both cases, Godot reimports the `.glb` the next time the editor opens or on
`godot --headless --path godot --import`.

## Rules the game relies on

- **Animation names = `Fighter::anim()` names.** States: `idle`, `walk`, `run`,
  `crouch`, `jumpsquat`, `air`, `specialfall`, `land`, `hitstun`, `shield`, `dizzy`,
  `grab_hold`, `grabbed`. Dodges (`DodgeData::name`): `spotdodge`, `roll_f`, `roll_b`,
  `airdodge`. Every mannequin move's `MoveData::name` (`Character::Mannequin.moves()`): `jab`, `jab2`, `jab3`, `ftilt`, `utilt`,
  `dtilt`, `dashattack`, `fsmash`, `usmash`, `dsmash`, `nair`, `fair`, `bair`, `uair`,
  `dair`, `special_n`, `special_s`, `special_u`, `special_d`, `special_d_land`, `grab`,
  `dashgrab`, `pummel`, `fthrow`, `bthrow`, `uthrow`, `dthrow`. A pose with no
  animation stays frozen on its last frame, and the game logs an `ERROR` for it at
  startup. A new move needs a new action with the same name. (Other characters'
  models, like the pug, have their own move names.)
- **60 fps, frame 1 = sim frame 1.** Moves are keyed on their sim frames (Blender
  frame 5 of `ftilt` is FTilt's frame 5). The export slides each action so frame 1
  is time 0. `godot/models/fighter.glb.import` has `animation/fps=60`; Godot's
  default 30 would halve the precision.
- **How each pose is timed** (`pose()` in `gdext/src/lib.rs`): moves, dodges and
  `jumpsquat` follow the state's frame counter (a charging smash attack holds its
  `charge_frame` pose), `land` plays its *last* N frames as landing lag
  counts down, and the rest loop on the world frame. Make loops start and end on the
  same pose.
- **Scale and facing:** meters, feet at the origin, facing +X, 1.2 m tall (sim
  hurtbox height 12 × `SCALE` 0.1). Keep fists and feet near the sim hitboxes in
  `sim/src/moves.rs` on active frames (press **H** in game to compare).
- **Materials:** surfaces using the material named `Body` get the player's color in
  game. `Skin`, `Accent` and `Eye` keep their own colors.
- **Visual only.** Hurtboxes and hitboxes stay in the sim, and nothing reads collision
  from this mesh.
- **New actions made in Blender** must be stashed (Action Editor → Stash) or be on an
  NLA track, so the exporter includes them.

## Pose convention (in `build_fighter.py`)

Angles are degrees, counter-clockwise as seen by the game camera with the fighter
facing right. `+` swings a hanging limb forward, tips the spine/head back, and raises
the toes. Child angles are relative to the parent. `leg_ik(pose, side, foot_x)` plants a
foot and solves the knee, so stances stay on the ground. `planted(pose, front, back)`
re-solves both legs after moving `hips_loc`. The near (camera-side) limbs
are `.R`.
