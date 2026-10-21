# Samurai model

The samurai (`Character::Samurai`): a lean, weathered swordsman in black-lacquered
lamellar armor laced with purple silk (cuirass, skirt plates, shoulder guards, armored
sleeves) and a ridged kabuto with a gold crescent crest, over an indigo kimono and wide
striped hakama, with tabi and straw sandals, a katana in his near hand and its empty
scabbard through his sash. Rigged and animated in Blender and exported to
`godot/models/samurai.glb`. His moveset is in the sim (`sim/src/character.rs`, frame data
at the end of `sim/src/moves.rs`; the root README lists the moves).

| File | What it is |
|---|---|
| `build_samurai.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `samurai.blend` and exports the `.glb`. |
| `samurai.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_samurai.py` | Exports `samurai.blend` to `godot/models/samurai.glb` (same glTF settings as the chef). |

The textures are packed into `samurai.blend` and embedded in the `.glb`; Godot extracts
them on import to `godot/models/samurai_*.png` (commit those with the `.glb`).

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
skinning helpers and the pose helpers (`guard`, `crouch`, `walk_key`,
`planted`, `with_`, `AIR`, `FLINCH`). Changing those in the chef's script changes the
samurai too, so rebuild both. The chef's pose convention applies (see
[`art/fighter/README.md`](../fighter/README.md#pose-convention-in-build_fighterpy)).

The rules in [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on)
apply here too, except for the move names: the samurai needs the shared state and dodge
animations plus one per samurai move (`Character::Samurai.moves()`: `slash`, `slash2`,
`thrust`, `forward_cut`, `rising_cut`, `low_cut`, `dash_cut`, `cleave`, `sky_cut`,
`spin_sweep`, `air_spin`, `air_cut`, `back_cut`, `sky_arc`, `plunge_stab`, `focus_cut`,
`vault`, `vault_strike`, `cyclone`, `parry`, `riposte`, `hip_throw`, `shoulder_throw`,
`toss_up`, `pin`, and the chef's shared `grab`, `dashgrab` and `pummel`), and the
four ledge clips `ledge_hang`, `ledge_climb`, `ledge_roll` and `ledge_attack`. The game logs
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
- **Turning the body.** `turned(pose, twist)` turns the hips (and so everything) about
  the vertical; negative turns him toward the camera while facing right. `cyclone` spins
  him four times this way. `vault` turns him around: the sim flips his facing on its
  frame 15, and the game turns the model 230 degrees then (from the right-facing 3/4
  view to the left-facing one), so the keys go to -65 on 14 and jump to +65 on 15: both
  face the camera, and no snap shows.

## Ledge clips

The sim hangs him with his origin 0.1 m outside the edge and the top of his hurtbox
(1.2 m) level with the platform, so in model space the ledge corner is at (0.1, 1.2).
The getups slide the origin linearly from there to standing inside the edge (0.8 m for
the climb over 20 frames, 1.5 m for the roll over 25, 1.0 m for the attack over 30;
`Fighter::ledge_getup_pos`), and the clips move him against that.

- They're designed in "stage space" (the corner at the origin) as sparse keys of where
  his pelvis, feet and fists are (`getup`), interpolated with a monotone cubic (no
  overshoot, so planted feet stay put) and solved with two-bone IK (`arm_to`,
  `leg_to`) on every frame, then shifted into model space by where the sim has put him
  that frame. So the fists stay on the corner while he hoists, and feet stay planted on
  the platform. The last three frames blend into the guard (`S`), so each ends exactly on
  `idle`.
- `ledge_hang` loops over 80 frames on the world clock: fists on the corner, a slow
  sway and breathing. While he grips the edge, the katana in his right fist lies along
  the platform (`HANG_AIM`).
- `ledge_roll` turns him a full 360 degrees about the pelvis in the tuck; it ends with
  `hips` at -360 (the same rotation as 0) and `aim` at 35 - 360, so the katana's own
  angle carries on smoothly into `idle`.
- `ledge_attack` steps up with the blade low in front and cuts upward through the
  sim's hit point (0.6, 0.6) from his origin on frames 15-18 (`LEDGE_ATTACK_HITBOX`,
  radius 0.6); the blade stays within 0.2-0.5 m of it on those frames.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece, skinned by distance to their
  bones like the chef's: the lean head (high cheekbones, square chin, nostrils, the folds
  beside the mouth), the hair under the helmet, the kimono top, each upper sleeve
  (creased where it bunches into the armored sleeve), each armored sleeve (kote), each
  hakama leg (overlapping capsules that flare to the hem, displaced into knife pleats
  before decimating) and each split-toe tabi. Metaball surfaces already face outward,
  so only the hand-built parts get their normals recalculated.
- **Armor** is built from solid curved plates (`plate`: an outer surface grid, a
  thickness and sharp rims, with UVs laid out along each row): the cuirass (five laced
  rows, each lower one a little further out, under a lacquered breastplate and backplate
  with gilt edges and shoulder straps), seven skirt panels of four rows hung on cords
  below the sash (their lower rows follow the thighs, so they swing up with a kick), the
  shoulder guards (a lacquered top plate over six laced rows round each upper arm), the
  sleeves' iron splints and hand plates.
- **The kabuto**: a ridged, riveted, black-lacquered bowl with a gilt crown ring, a peak
  with a gilt edge, a four-row laced neck guard with its front ends turned back beside
  the face (each with a gilt crest disc), the gold crescent crest and the chin cord.
- **Details** are bmesh parts placed on those surfaces by ray casting: the narrowed eyes
  with lid folds, scowling brows, a drooping mustache and short beard, the headband
  (tilted down at the back like the helmet's rim, so it shows across the forehead and its
  tails hang out below the neck guard), the crossed collar, the sash with its knot and
  ends, the sandals, the scabbard (lacquer, an iron mouth and end cap, the knob and
  purple cord) and the katana: an iron pommel cap, a silk-wrapped hilt over ray skin
  with gilt ornaments, an iron guard with a rim between gilt washers, the gilt collar,
  and a curved shinogi-zukuri blade (spine, ridge line, polished planes and edge, each
  face strip shading smooth with sharp ridges) ending in a curved point.
- **Materials** are physically based. `Body` (the headband and sash) gets the player's
  color in game, and only it shows hit flashes and other state tints. The others keep
  their own; the ones that need surface detail have seeded textures generated by the
  script with numpy (`make_textures`), since glTF keeps image textures but not
  procedural node trees:
  - `Lamellar`: rows of lacquered scales (kozane) laced with purple silk cords, with
    worn red-brown undercoat at the scale heads (color, normal, roughness). One texture
    tile is `LAMELLAR_TILE` m of row.
  - `Gi`, `Hakama`, `Kote`, `Tabi`, `Collar`: a woven cloth normal map with slubs and
    creases; the kimono's faded indigo and the hakama's fine stripes in color.
  - `Skin`: the face in the head's cylindrical UVs (`head_uv`): sun-darkened skin with
    pores, crow's feet, frown lines, nasolabial folds, stubble and a scar down his right
    cheek.
  - `Blade`: mirror-polished steel, a burnished ridge plane, and the frosty hardened
    edge below a wavy hamon (color and metallic-roughness, in UVs along the blade).
  - `Iron` (hammered and pitted) and `Lacquer` / `Saya` (a faint unevenness).
  - Plain: `Hand`, `Lip`, `Hair`, `Beard`, `Eye`, `Iris`, `Pupil`, `Straw`, `Gold`,
    `Wrap`, `Same`, `Cord`.
