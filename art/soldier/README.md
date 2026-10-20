# Soldier model

The soldier (`Character::Soldier`): a heavy infantryman with his face hidden behind a
balaclava and tactical goggles, in a combat helmet and a plate carrier hung with magazine
pouches, pads on his shoulders, elbows and knees, a drop-leg holster and a knife, laced
combat boots — and a two-handed rifle that ends in a bayonet. Rigged and animated in
Blender and exported to `godot/models/soldier.glb`; the same script builds the grenade he
lobs (his side special) as `godot/models/grenade.glb`. His moveset is in the sim
(`sim/src/character.rs`, frame data at the end of `sim/src/moves.rs`; the root README
lists the moves).

| File | What it is |
|---|---|
| `build_soldier.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `soldier.blend`, exports `soldier.glb`, then builds and exports `grenade.glb`. |
| `soldier.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_soldier.py` | Exports `soldier.blend` to `godot/models/soldier.glb` (same glTF settings as the chef). |
| `preview.py` | Renders stills of `soldier.blend` — front, three-quarter, side, back and close-ups — without launching Godot. |
| `preview_poses.py` | Renders animation frames, to check how the gear deforms in poses. |

```sh
blender --background --factory-startup --python art/soldier/build_soldier.py      # rebuild from the script
blender --background art/soldier/soldier.blend --python art/soldier/export_soldier.py   # or export hand edits
godot --headless --path godot --import                                            # then reimport
blender --background art/soldier/soldier.blend --python art/soldier/preview.py -- /tmp/soldier   # look at it
blender --background art/soldier/soldier.blend --python art/soldier/preview_poses.py -- /tmp/poses
```

As with the chef, rebuilding from the script overwrites hand edits to `soldier.blend`.
Choose one approach per change. The preview scripts only add a camera, lights and a floor
to a throwaway scene — they never write to the `.blend`.

## Built on the chef

He stands on the chef's skeleton (same joints, 1.2 m tall), so `build_soldier.py`
imports `art/fighter/build_fighter.py` for the metaball shapes (`Blob`), the skinning
helpers and the pose helpers (`guard`, `crouch`, `walk_key`, `leg_ik`, `planted`,
`with_`, `AIR`, `FLINCH`). Changing those in the chef's script changes the soldier
too, so rebuild both. The chef's pose convention applies (see
[`art/fighter/README.md`](../fighter/README.md#pose-convention-in-build_fighterpy)).

## The rifle

- **The `rifle` bone** (child of `forearm.R`) runs along +X through the right fist.
  Every pose gives `aim`: the rifle's direction as seen by the game camera with the
  fighter facing right (0 = forward, 90 = up, 180 = backward). `apply_pose` subtracts
  the arm's chain (hips, spine, upper arm, forearm) to get the bone's own angle, so a
  pose can move the arm and keep the rifle pointing the same way. Missing `aim`
  defaults to 12 (the ready stance).
- **Where the barrel sits.** The *geometry* is built around `AXIS`, 5 cm above the
  `GRIP` the bone starts at, so the barrel and receiver run above the fist and the hand
  wraps the pistol grip below it, the way a real grip works. Moving `AXIS` moves the
  whole rifle without touching a single pose.
- **Two hands.** The right hand grips the pistol grip; the left arm is posed separately
  to support the handguard (it doesn't track the rifle exactly, so it drifts a little on
  big swings — a stylized concession like the chef's off-hand).
- **Parts.** A polymer stock with a butt pad and a raised cheek rest, a railed receiver
  with rail teeth, rear sight and charging handle, an angled pistol grip, a trigger and
  its guard, a curved magazine, a vented handguard with a gas block and a front sight, the
  barrel and a muzzle device, then the bayonet: a socket at the muzzle and a flattened
  steel blade. A sling hangs down the near side. The whole thing is ~1.08 m from butt to
  point, which puts the bayonet tip near the sim's `soldier_bayonet` hitbox on the thrust
  frames.

## How it's built

- **Cloth** is metaball surfaces, one family per piece so the limbs don't fuse to the
  torso: the balaclava (crown, jaw, the cloth tenting over the nose, a gaiter bunched over
  the collar), the field shirt (thick chest, hard taper to the waist), each sleeve, each
  gloved fist with **four separate fingers plus a thumb** and a gauntlet cuff, each
  trouser leg (with a cargo pocket, bloused over the boot), each combat boot, and the
  magazine pouches. Negative elements crease the cloth — waist, armpit, elbow, behind the
  knee, where the cuffs gather — so it doesn't read as plastic.
- **Curved gear** is a `hug_patch`: a plate laid on a cloth surface by ray casting it
  over a grid of angles and heights, pushed out a few millimetres and given a thickness.
  That is the plate carrier's front and back plates, the shoulder, elbow and knee pads,
  the goggle frame and its lens, the helmet's side rails, the MOLLE rows and the
  player-colored flag patch. `register()` makes the helmet shell ray-castable so its rails
  and NVG shroud can be laid on it.
- **Hard gear** is `box`/`slab` parts: pouch flaps and buckles, the NVG shroud, the
  helmet rails' ends, the holster and knife, the boot soles and heel blocks.
- **The helmet** is a dome fitted to the head (`Model.fit` at the rim), capped with a fan
  at the crown, over a cloth cover band that stands proud at the brow.
- **Straps** — the goggle strap, chinstrap with its buckle, belt, knee-pad straps,
  holster and knife straps, boot laces, sling, seams — are tubes and bands fitted to the
  surface they sit on (`strap`), and take the weights of the piece they are sewn onto
  (`Model.weights_near`), so they move with it.
- **The grenade** (`build_grenade`) is a pineapple body with a fuze, a pin ring and a
  spoon, drawn by the game as the side special's projectile.

## Materials and shading

A material per part, listed in `MATERIALS` in `build_soldier.py`. The Blender colors
matter for the `.blend` and as the exported fallback; the game swaps most of the big
surfaces for shaders, keyed by material name in `godot/models/soldier.glb.import`:

| Material | In game |
|---|---|
| `Camo` (fatigues) | `soldier_camo.tres` → `godot/shaders/camo.gdshader`: a procedural woodland camo in object space (no UVs needed), with sun-fade blotches, a cloth grain and dirt gathered towards the boots. |
| `Vest`, `VestPouch`, `Balaclava`, `Boot`, `Helmet`, `Polymer`, `Pad`/`HelmetBand`/`GoggleFrame`/`Glove`/`Strap`/`Sole` | `godot/shaders/gear.gdshader`: one worn-fabric-and-leather shader in object space, in each material's own color and roughness (`soldier_vest.tres`, `soldier_vest_pouch.tres`, `soldier_balaclava.tres`, `soldier_boot.tres`, `soldier_helmet.tres`, `soldier_polymer.tres`, and `soldier_hardware.tres` for the near-black hardware). |
| `Body` | **Not** swapped: the game tints it with the player's color, and only it shows hit flashes and other state tints. It is the armband and the flag patch. |

`Buckle`, `Lace`, `GoggleGlass`, `Steel`, `Gunmetal`, `Barrel` and the grenade's
`Grenade` keep their own PBR values. The weapon metals are deliberately only mildly
metallic: the stage is lit by a bright sky, and a shiny rifle mirrored it and read as
blue-grey rather than black.

The cloth shaders set their own `ROUGHNESS` and `SPECULAR` rather than taking them from
the glTF material, because Godot's default specular lifts dark matte surfaces with the
sky's ambient light — which is what made the pads and helmet look pale grey-blue before
they were swapped.

## What the game relies on

- **Animation names = `Fighter::anim()` names**, 60 fps, frame 1 = sim frame 1, and every
  soldier move: the rules in
  [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on) apply here in
  full, except that every slot is his own (all 26 moves, grab, dash grab, pummel and all
  four throws included). `godot/models/soldier.glb.import` must keep `animation/fps=60`,
  and its `_subresources` block is what swaps the shader materials.
- **`Body` must exist**, or the player color and the hit flash go somewhere else.
- **He stays 1.2 m to the top of the head** (sim hurtbox height 12 × `SCALE` 0.1), with
  his fists and feet near the sim hitboxes in `sim/src/moves.rs` on active frames (press
  **H** in game to compare). The helmet rises a little above the hurtbox, like the chef's
  toque.
- **Visual only.** Nothing reads collision from this mesh.
