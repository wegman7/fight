# Pug model

A realistic black pug on four legs, rigged and animated in Blender,
exported to `godot/models/pug.glb`. It draws `Character::Pug`, which has its own
moveset in the sim (`sim/src/character.rs`, frame data at the end of
`sim/src/moves.rs`; the root README lists the moves). Pick it on the character select screen to play it.

| File | What it is |
|---|---|
| `build_pug.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `pug.blend` and exports the `.glb`. |
| `pug.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_pug.py` | Exports `pug.blend` to `godot/models/pug.glb` (same glTF settings as the chef). |

```sh
blender --background --factory-startup --python art/pug/build_pug.py      # rebuild from the script
blender --background art/pug/pug.blend --python art/pug/export_pug.py    # or export hand edits
godot --headless --path godot --import                                   # then reimport
```

As with the chef, rebuilding from the script overwrites hand edits to `pug.blend`.
Choose one approach per change.

The rules in [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on)
apply here too, except for the move names: the pug needs the shared state and dodge
animations plus one per pug move (`Character::Pug.moves()`: `bite`, `bite2`, `nibbles`,
`paw_swipe`, `head_toss`, `scoot`, `belly_slide`, `ram`, `howl`, `shake`, `tail_spin`,
`air_headbutt`, `buck`, `snap`, `pancake`, `sneeze`, `tackle`, `tackle_ride`, `ear_copter`,
`play_dead`, `pounce`, `bite_grab`, `dash_bite_grab`, `nom`, `toss`, `tug_spin`,
`fling_up`, `sit`). The game logs an `ERROR` at startup for any it can't find. Also
60 fps with frame 1 = sim frame 1, facing +X with paws on
the ground at the origin, and the model is visual only.
`godot/models/pug.glb.import` must keep `animation/fps=60`.

## How it's built

- **Fur** is one surface made of metaballs (`fur_blob`), so the body, legs and head
  blend like flesh. It's converted to a mesh, decimated, and skinned with Blender's
  automatic (heat) weights. Face detail (the nose roll draped over the nose, forehead
  wrinkles, worried brows, muzzle pads, flews, eye sockets) comes from small positive
  and negative metaballs. Positions shared with the rigid parts (`NOSE`, `NOSE_ROLL`,
  the toes) are constants at the top of the mesh section.
- **Rigid parts** each follow one bone: the eyes (pupil, dark iris and a sliver of
  white inside an almond opening, black lids, a small catchlight), the flat-fronted nose
  with nostrils, the button ears, the tail (a tight double curl lying on the hip), black
  nails on every toe, the lower jaw (its own blob, so the mouth can open onto the mouth
  interior and tongue), and the flat collar band with its tag. The ears are laid onto
  the finished fur surface (`Surface`, a nearest-point lookup), so they follow the
  skull wherever the head's metaballs put it.
- **Materials:** `Body` is the collar, which gets the player's color in game. `Fur`,
  `Nose`, `Skin` (eyelids), `Nail`, `Eye` (the pupil), `Iris`, `Sclera`, `Catchlight`,
  `Tongue`, `Mouth` and `Accent` (the gold tag) keep their own. Hit flashes and other
  state tints only show on the collar.
- **Fur shading in game:** `godot/models/pug.glb.import` swaps the `Fur` material for
  `godot/models/pug_fur.tres`, which uses `godot/shaders/fur.gdshader` (a soft sheen and
  a fuzzy, lighter silhouette instead of a plastic highlight). The Blender `Fur`
  material only matters for the `.blend` and the exported fallback. Keep that
  `_subresources` entry when changing the import settings.
- **Size:** about 0.8 m tall at the top of the head and 0.85 m from rump to nose,
  close to the pug's 0.9 × 0.8 m hurtbox capsule (`FighterParams::PUG`). Attack poses put
  the head or paws roughly where the sim's hitboxes are (comments in `ANIMATIONS` give
  each one); press **H** in game to compare.

## Rig and poses

Bones: `body` (root, moved by `loc`), `chest` → `neck` → `head` → `jaw`, `ear.L/R`,
`pelvis` → `tail`, and per side `upper_arm` → `forearm` → `hand` (front legs) and
`thigh` → `shin` → `hock` → `foot` (hind legs). `.R` is the camera side.

A pose is a dict of bone angles in degrees, counter-clockwise as seen by the game
camera with the pug facing right (+ tips the head or chest up, swings a hanging leg
forward, tucks the pelvis down; `jaw` negative opens the mouth). A tuple gives
`(pitch, twist, spread)`: `head=(0, 20, 0)` tilts the head for the sneeze's head shake.
Ears take `(lift, twist, spread)` in their own axes; + lift flaps them out.

Helpers in `build_pug.py`:

- `stand(drop, fwd, front, hind, ...)` plants all four paws by IK (`plant`), so the
  body can lean, crouch or lunge while the feet stay put. `feet={"FR": (dx, lift)}`
  moves one paw. Setting any of a leg's bone angles directly turns its IK off.
- `flying(tuck)` and `splayed()` are the airborne leg sets (loose / tucked, starfish).
- `gait(...)` generates the walk (lateral sequence) and run (gallop) loops one key per
  frame. `tackle_ride()` keys the ride: the pug is drawn 0.6 m ahead and 0.5 m up,
  clinging to the opponent the game holds 0.9 m in front. `spin(pose, first, last)` turns a pose about the
  vertical (tail spin, tug spin). `body=(0, 0, 180)` rolls it belly-up (play dead).
- `P(base, **changes)` copies a pose with changes; `ear_L=` means `"ear.L"`, `ears=` sets both.
