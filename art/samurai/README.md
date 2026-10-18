# Samurai model

The samurai (`Character::Samurai`): a lean swordsman with a topknot and headband, in an
indigo kimono top, wide hakama, tabi and straw sandals, with a katana in his near hand
and its empty scabbard through his sash. Rigged and animated in Blender and exported to
`godot/models/samurai.glb`. His moveset is in the sim (`sim/src/character.rs`, frame data
at the end of `sim/src/moves.rs`; the root README lists the moves).

| File | What it is |
|---|---|
| `build_samurai.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `samurai.blend` and exports the `.glb`. |
| `samurai.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_samurai.py` | Exports `samurai.blend` to `godot/models/samurai.glb` (same glTF settings as the chef). |

```sh
blender --background --factory-startup --python art/samurai/build_samurai.py      # rebuild from the script
blender --background art/samurai/samurai.blend --python art/samurai/export_samurai.py   # or export hand edits
godot --headless --path godot --import                                            # then reimport
```

As with the chef, rebuilding from the script overwrites hand edits to `samurai.blend`.
Choose one approach per change.

## Built on the chef

He stands on the chef's skeleton (same joints, 1.2 m tall), so `build_samurai.py`
imports `art/fighter/build_fighter.py` for the metaball shapes (`Blob`), the hand, the
skinning helpers and the pose helpers (`guard`, `crouch`, `walk_key`, `leg_ik`,
`planted`, `with_`, `AIR`, `FLINCH`). Changing those in the chef's script changes the
samurai too, so rebuild both. The chef's pose convention applies (see
[`art/fighter/README.md`](../fighter/README.md#pose-convention-in-build_fighterpy)).

The rules in [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on)
apply here too, except for the move names: the samurai needs the shared state and dodge
animations plus one per samurai move (`Character::Samurai.moves()`: `slash`, `slash2`,
`thrust`, `forward_cut`, `rising_cut`, `low_cut`, `dash_cut`, `cleave`, `sky_cut`,
`spin_sweep`, `air_spin`, `air_cut`, `back_cut`, `sky_arc`, `plunge_stab`, `wind_slash`,
`dash_strike`, `rising_dragon`, `parry`, `riposte`, `hip_throw`, `shoulder_throw`,
`toss_up`, `pin`, and the chef's shared `grab`, `dashgrab` and `pummel`). The game logs
an `ERROR` at startup for any it can't find. `godot/models/samurai.glb.import` must keep
`animation/fps=60`.

## The katana

- **The `katana` bone** (child of `forearm.R`) runs along +X through the right fist,
  the blade's edge down. Every pose gives `aim`: the blade's direction as seen by the
  game camera with the fighter facing right (0 = forward, 90 = up, 180 = backward).
  `apply_pose` subtracts the arm's chain (hips, spine, upper arm, forearm) to get the
  bone's own angle, so a pose can move the arm and keep the blade pointing the same way.
  Missing `aim` defaults to 35 (the guard).
- **Reach.** The blade is 0.64 m, which puts its tip 12-14 sim units out on a level cut.
  The sim's sword hitboxes are placed to match: the first listed one is the tip (it wins
  when both touch). Keep the blade over its hitboxes on active frames (press **H** in
  game to compare). The comments above each entry in `ANIMATIONS` give the sim frames.
- Spins go past 360 degrees (`air_spin` ends at `upper_arm.R` 405, the same as 45)
  so the keys interpolate the right way round.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece, skinned by distance to their
  bones like the chef's: the lean head (high cheekbones, square chin), the hair, the
  kimono top, each wide sleeve (with its pouch hanging behind the forearm), each hakama
  leg (overlapping capsules that flare to the hem) and each split-toe tabi.
- **Details** are bmesh parts placed on those surfaces by ray casting: the narrowed eyes
  and scowling brows, a drooping mustache and short beard, the topknot and its white tie,
  the headband with its knot and tails at the back, the crossed collar, the obi with a
  flat knot, the sandals, the scabbard (on the hips, sloping down behind) and the katana
  (gold pommel, a cord-wrapped hilt that leaves white diamonds, an iron guard, the gold
  collar, and a curved blade of 28 lens-shaped sections with a polished edge).
- **Materials:** `Body` (the headband and obi) gets the player's color in game, and only
  it shows hit flashes and other state tints. `Gi`, `Collar`, `Hakama`, `Skin`, `Lip`,
  `Hair`, `Eye`, `Iris`, `Pupil`, `Tabi`, `Straw`, `Steel`, `Edge`, `Iron`, `Gold`, `Wrap`
  and `Saya` keep their own.
