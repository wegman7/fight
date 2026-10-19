# Ninja model

The ninja (`Character::Ninja`): the lightest, fastest fighter — a lean figure in a dark
gi with a face wrap over nose and mouth, a headband knotted at the back, a shuriken
pouch on his hip and open knife-hands with separate fingers. Rigged and animated in
Blender and exported to `godot/models/ninja.glb`. His moveset is in the sim
(`sim/src/character.rs`, frame data at the end of `sim/src/moves.rs`; the root README
lists the moves).

| File | What it is |
|---|---|
| `build_ninja.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `ninja.blend` and exports the `.glb`. |
| `ninja.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_ninja.py` | Exports `ninja.blend` to `godot/models/ninja.glb` (same glTF settings as the chef). |

```sh
blender --background --factory-startup --python art/ninja/build_ninja.py      # rebuild from the script
blender --background art/ninja/ninja.blend --python art/ninja/export_ninja.py   # or export hand edits
godot --headless --path godot --import                                            # then reimport
```

As with the chef, rebuilding from the script overwrites hand edits to `ninja.blend`.
Choose one approach per change.

## Built on the chef

He stands on the chef's skeleton (same joints, 1.2 m), so `build_ninja.py` imports
`art/fighter/build_fighter.py` for the metaball shapes (`Blob`), the skinning helpers
and the pose helpers (`guard`, `crouch`, `walk_key`, `leg_ik`, `planted`, `with_`,
`AIR`, `FLINCH`). Changing those in the chef's script changes the ninja too, so rebuild
both. The chef's pose convention applies (see
[`art/fighter/README.md`](../fighter/README.md#pose-convention-in-build_fighterpy)).

There is no extra bone like the samurai's katana: the ninja's shuriken is drawn as a
projectile orb (see `gdext/src/lib.rs`), and his specials — the shadow dash, smoke bomb
and substitution counter — are body moves, so the hands stay free.

The rules in [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on)
apply here too, except for the move names: the ninja needs the shared state and dodge
animations plus one per ninja move (`Character::Ninja.moves()`: `ninja_kunai`,
`ninja_kunai2`, `ninja_kunai3`, `ninja_palm_thrust`, `ninja_rising_chop`, `ninja_sweep`,
`ninja_dash_slice`, `ninja_chop`, `ninja_flip_kick`, `ninja_spin_kick`, `ninja_air_spin`,
`ninja_flying_kick`, `ninja_back_hook`, `ninja_up_flip`, `ninja_axe_kick`,
`ninja_shuriken`, `ninja_shadow_dash`, `ninja_smoke_bomb`, `ninja_substitution`,
`ninja_substitution_strike`, `ninja_grab`, `ninja_dash_grab`, `ninja_pummel`,
`ninja_throw_forward`, `ninja_throw_back`, `ninja_throw_up`, `ninja_throw_down`). Unlike
the samurai, every slot is his own — he does not reuse the chef's `grab`, `dashgrab` or
`pummel`. The game logs an `ERROR` at startup for any animation it can't find.
`godot/models/ninja.glb.import` must keep `animation/fps=60`.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece so the limbs don't fuse to
  the body: the lean head (high cheekbones, square chin, straight nose, full mouth), the
  hair, the gi's body, each close-fitting sleeve, each fitted trouser leg and each
  split-toe tabi. Each is polygonized, smoothed, decimated and skinned by distance to
  its bones (`by_distance`).
- **More detail than the cast:** the hands are modeled as a palm plus four **separate
  fingers** and a thumb (tubes skinned to the forearm), so every chop reads. The face
  has narrowed eyes, scowling brows, a nose and a mouth. The gi has a crossed front
  seam and two side seams, and the face wrap is a fitted band with a back seam and a
  side knot.
- **The face wrap** (`Wrap`) hugs the head from just under the eyes to the neck,
  covering nose, mouth and chin. **The headband** (`Body`) sits across the brow,
  knotted at the back with two cloth tails hanging behind — it, and the belt, get the
  player's color in game. The **shuriken pouch** on the back-right hip has a flap and a
  steel shuriken peeking out.
- **Materials:** `Body` (headband and belt) gets the player's color in game, and only
  it shows hit flashes and other state tints. `Gi`, `Wrap`, `Skin`, `Lip`, `Hair`,
  `Eye`, `Iris`, `Pupil`, `Steel` and `Sole` keep their own.
