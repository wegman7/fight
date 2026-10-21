# Ninja model

The ninja (`Character::Ninja`): the lightest, fastest fighter, a lean figure in a dark
shinobi shozoku. He wears a wrap-front jacket with crossed lapels, bloused over an obi
tied at the back, and baggy trousers gathered into wound shin wraps (kyahan). His feet
are in split-toe tabi with rubber soles and metal clasps. A face mask is draped over his
nose and chin and knotted behind his head, and a headband is knotted at the back. His
forearms are wrapped, cloth guards (tekko) cover the backs of his open hands, and a
leather shuriken pouch hangs on his hip. Rigged and animated in Blender and exported to
`godot/models/ninja.glb`. His moveset is in the sim (`sim/src/character.rs`, frame data
at the end of `sim/src/moves.rs`; the root README lists the moves).

| File | What it is |
|---|---|
| `build_ninja.py` | Generates the whole asset from code: mesh, UVs, textures, armature, every animation. Saves `ninja.blend` and `textures/`, and exports the `.glb`. |
| `ninja.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_ninja.py` | Exports `ninja.blend` to `godot/models/ninja.glb` (same glTF settings as the chef). |
| `textures/` | The generated tiling maps (`*_normal.png`, `*_albedo.png`). They are embedded in the `.glb`, and Godot extracts them on import as `godot/models/ninja_*.png`. |

```sh
blender --background --factory-startup --python art/ninja/build_ninja.py      # rebuild from the script
blender --background art/ninja/ninja.blend --python art/ninja/export_ninja.py   # or export hand edits
godot --headless --path godot --import                                            # then reimport
```

As with the chef, rebuilding from the script overwrites hand edits to `ninja.blend`.
Choose one approach per change. Everything is seeded (integer-hashed noise, no
`random`), so a rebuild gives the same model and textures.

## Built on the chef

He stands on the chef's skeleton (same joints, 1.2 m; his sim hurtbox is 1.1 m, `H` in
the script). So `build_ninja.py` imports `art/fighter/build_fighter.py` for the metaball
shapes (`Blob`), the skinning helpers and the pose helpers (`guard`, `crouch`,
`walk_key`, `leg_ik`, `planted`, `with_`, `AIR`, `FLINCH`). Changing those in the chef's
script changes the ninja too, so rebuild both. The chef's pose convention applies (see
[`art/fighter/README.md`](../fighter/README.md#pose-convention-in-build_fighterpy)), with
one difference: the ninja's bones rotate in `YXZ` order (twist about the bone first),
where the chef's use `XYZ`. The two agree whenever twist is 0. Only the ledge clips
twist a bone: the forearms turn the palms to the ledge, and the hips spin the ledge
attack.

There is no extra bone like the samurai's katana: the ninja's shuriken is drawn as a
projectile orb (see `gdext/src/lib.rs`), and his specials (the shadow dash, smoke bomb
and substitution counter) are body moves, so the hands stay free.

The rules in [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on)
apply here too, except for the move names. The ninja needs the shared state and dodge
animations, including the four ledge clips `ledge_hang`, `ledge_climb`, `ledge_roll`
and `ledge_attack`, plus one per ninja move (`Character::Ninja.moves()`):
`ninja_kunai`, `ninja_kunai2`, `ninja_kunai3`, `ninja_palm_thrust`, `ninja_rising_chop`,
`ninja_sweep`, `ninja_dash_slice`, `ninja_chop`, `ninja_flip_kick`, `ninja_spin_kick`,
`ninja_air_spin`, `ninja_flying_kick`, `ninja_back_hook`, `ninja_up_flip`,
`ninja_axe_kick`, `ninja_shuriken`, `ninja_shadow_dash`, `ninja_smoke_bomb`,
`ninja_substitution`, `ninja_substitution_strike`, `ninja_grab`, `ninja_dash_grab`,
`ninja_pummel`, `ninja_throw_forward`, `ninja_throw_back`, `ninja_throw_up`,
`ninja_throw_down`. Unlike the samurai, every slot is his own: he does not reuse the
chef's `grab`, `dashgrab` or `pummel`. The game logs an `ERROR` at startup for any
animation it can't find. `godot/models/ninja.glb.import` must keep `animation/fps=60`.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece so the limbs don't fuse to
  the body: the lean head, the hair, the jacket's body, each sleeve, each trouser leg,
  each tabi and its sole, each hand and each finger. Each is polygonized and smoothed.
  Then (`blob_mesh`) it is **displaced** along its normals before decimating: cloth
  folds from stretched ridged noise (`folds`) bloused above the obi and the shin wraps,
  drag lines across the chest, folds down the thighs and upper sleeves and bunching at
  the elbows. The hair gets combed strands. Each piece is then skinned by distance to
  its bones (`by_distance`).
- **Hands** hang in line with the forearm (fingers down at rest, palm toward the body):
  a palm with its pads and the ball of the thumb, the thumb tucked along the index
  finger, and four separate three-jointed fingers with a relaxed curl. All of it is
  skinned to the forearm, since there are no hand bones.
- **The face mask** (`face_mask`) is one sheet of cloth. Each horizontal slice of it is
  the convex hull of the head there, so it stretches across the cheeks. Its front hangs
  from the nose and chin instead of following the mouth and throat. It creases loosely
  round the neck, its top edge rises over the bridge of the nose, dips under the eyes
  and covers the ears, and it is knotted at the back.
- **Eyes**: an eyeball in an almond-shaped socket, iris and pupil, and upper and lower
  lids cut from skin shells (the upper one slanting down toward the nose). A dark lash
  line runs along the upper lid, and the brows are flat, tapering strokes.
- **Wraps** (`wrap_bands`): overlapping, tilted turns of cloth wound up each forearm and
  shin, each turn laid over the one below. A cord ties the shin wrap under the knee.
  The hand guards cover the back of each hand and loop round the middle finger.
- **Lapels** (`lapels`): thick collar bands laid on the jacket, standing round the base
  of the neck, the wearer's left crossing over the right down to the obi.
- **Materials:** `Body` (the headband and the obi) gets the player's color in game, and
  only it shows hit flashes and other state tints. `Gi`, `Wrap`, `Skin`, `Hair`, `Eye`,
  `Iris`, `Pupil`, `Steel`, `Leather` and `Sole` keep their own. Colors in `MATERIALS`
  are sRGB and are converted to linear.
- **Textures** survive the glTF export because they are images, not node trees. Tiling
  normal maps (a plain cloth weave with slubs and creases, skin pores, hair strands,
  brushed steel, pebbled leather) and albedo maps (faded, uneven dye on the cloth, faint
  blotches on the skin) are generated at build time into `textures/`. They are wired
  into each material's Principled BSDF through an Image Texture and a Normal Map node.
  The whole mesh is Smart-UV-unwrapped (`unwrap`), and its UVs are scaled so one repeat
  covers `TILE` = 0.1 m everywhere. Subsurface scattering on the skin is set in Blender
  only, since glTF has no channel for it.

## Ledge clips

The sim hangs the fighter's origin 0.1 m outside the edge, with the top of the hurtbox
(H = 1.1 m) level with the stage, so the ledge corner is at model (0.1, H). A getup
slides the origin linearly onto the stage: climb 20 frames, 0.9 m in; roll 25 frames,
1.6 m; attack 30 frames, 1.1 m, with its hit on frames 15-18. While a getup runs,
`pose()` shows Blender frame k when the origin is (k − 1)/n of the way there.

So the clips are authored **on the stage**. Each key places the hips in stage
coordinates (origin at the ledge corner) and sets the joint angles. Keys are joined
by a Catmull-Rom spline (`_spline`), and every frame is converted back to model space
against where the origin is on that frame. Hands holding the ledge are solved by
analytic two-bone IK (`arm_ik`, elbows out to the sides). Planted feet are solved by
`leg_ik`. Over the stage, `_keep_above_floor` lifts the hips so no part of the body
sinks into the floor. Every frame is keyed.

- `ledge_hang` loops every 80 frames: hands over the corner with palms to the wall, a
  slow sway, breathing, trailing legs.
- `ledge_climb`: pulls up, presses over the edge, plants the near knee on the stage,
  steps up through it and ends on `idle`.
- `ledge_roll`: springs up on the hands, dives over them into a tight forward roll (a
  full turn round the hips, staying low) and pops up into `idle`.
- `ledge_attack`: hoists into a low crouch, winds round and sweeps the near leg along
  the floor in a spin through the hit point on 15-18, then stands into `idle`.
