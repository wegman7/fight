# Soldier model

The soldier (`Character::Soldier`): a heavy infantryman in a helmet, webbing and
baggy fatigues, with a two-handed rifle that ends in a bayonet. Rigged and animated
in Blender and exported to `godot/models/soldier.glb`; the same script builds the
grenade he lobs (his side special) as `godot/models/grenade.glb`. His moveset is in
the sim (`sim/src/character.rs`, frame data at the end of `sim/src/moves.rs`; the
root README lists the moves).

| File | What it is |
|---|---|
| `build_soldier.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `soldier.blend`, exports `soldier.glb`, then builds and exports `grenade.glb`. |
| `soldier.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_soldier.py` | Exports `soldier.blend` to `godot/models/soldier.glb` (same glTF settings as the chef). |

```sh
blender --background --factory-startup --python art/soldier/build_soldier.py      # rebuild from the script
blender --background art/soldier/soldier.blend --python art/soldier/export_soldier.py   # or export hand edits
godot --headless --path godot --import                                            # then reimport
```

As with the chef, rebuilding from the script overwrites hand edits to `soldier.blend`.
Choose one approach per change.

## Built on the chef

He stands on the chef's skeleton (same joints, 1.2 m tall), so `build_soldier.py`
imports `art/fighter/build_fighter.py` for the metaball shapes (`Blob`), the skinning
helpers and the pose helpers (`guard`, `crouch`, `walk_key`, `leg_ik`, `planted`,
`with_`, `AIR`, `FLINCH`). Changing those in the chef's script changes the soldier
too, so rebuild both. The chef's pose convention applies (see
[`art/fighter/README.md`](../fighter/README.md#pose-convention-in-build_fighterpy)).

The rules in [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on)
apply here too, except for the move names: the soldier needs the shared state and
dodge animations plus one per soldier move (`Character::Soldier.moves()`: all 26 of
them, since every slot — grab, dash grab, pummel and all four throws included — is
his own). The game logs an `ERROR` at startup for any it can't find.
`godot/models/soldier.glb.import` must keep `animation/fps=60`.

## The rifle

- **The `rifle` bone** (child of `forearm.R`) runs along +X through the right fist,
  the barrel forward. Every pose gives `aim`: the rifle's direction as seen by the
  game camera with the fighter facing right (0 = forward, 90 = up, 180 = backward).
  `apply_pose` subtracts the arm's chain (hips, spine, upper arm, forearm) to get the
  bone's own angle, so a pose can move the arm and keep the rifle pointing the same
  way. Missing `aim` defaults to 12 (the ready stance).
- **Two hands.** The right hand grips the trigger; the left arm is posed separately to
  support the barrel (it doesn't track the rifle exactly, so it drifts a little on
  big swings — a stylized concession like the chef's off-hand).
- **Parts.** The rifle is one prop built from several materials: a wooden stock, a
  metal receiver, a dark barrel, a polymer fore-end and grip, a curved magazine, a
  front sight and a flattened steel bayonet at the muzzle. The whole thing is ~1.06 m
  from stock to point, which puts the bayonet tip near the sim's `soldier_bayonet`
  hitbox on the thrust frames.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece, skinned by distance to
  their bones like the chef's: the lean face (square jaw, cheekbones), the cropped
  hair, the fatigue shirt, each baggy sleeve (bunched above the cuff), each gloved
  hand with **four separate fingers plus a thumb**, each trouser leg (bloused into
  the boot) and each combat boot.
- **Details** are bmesh parts placed on those surfaces by ray casting: the narrowed
  eyes and brows, the lips, the helmet (a fitted dome, a brim band and a chinstrap),
  the chest webbing with two pouches, the stitching seams along the sleeve and leg,
  the `Body` armband, and the rifle.
- **Materials:** `Body` (the armband) gets the player's color in game, and only it
  shows hit flashes and other state tints. `Camo` (the fatigues) is swapped for a
  procedural camo shader on import (see below). `Skin`, `Lip`, `Hair`, `Eye`, `Iris`,
  `Pupil`, `Helmet`, `HelmetBand`, `Boot`, `Glove`, `Web`, `Seam` and the rifle's
  `Wood`, `Gunmetal`, `Barrel`, `Steel` and `Polymer` keep their own colors, as does
  the grenade's `Grenade`.
- **Camo shading in game:** `godot/models/soldier.glb.import` swaps the `Camo`
  material for `godot/models/soldier_camo.tres`, which uses `godot/shaders/camo.gdshader`
  (a procedural woodland camo in object space, so the metaball fatigues need no UVs).
  The Blender `Camo` material only matters for the `.blend` and the exported fallback.
  Keep that `_subresources` entry when changing the import settings.
- **The grenade** (`build_grenade`) is a pineapple body with a fuze, a pin ring and a
  spoon, drawn by the game as the side special's projectile.
