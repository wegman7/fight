# Soldier model

The soldier (`Character::Soldier`): a heavy infantryman with his face hidden behind a
balaclava and tactical goggles, electronic ear-pro with a boom mic under a combat
helmet, a plate carrier with MOLLE webbing hung with sewn magazine, admin, radio,
medical and hydration pouches, pads on his shoulders, elbows and knees, a battle belt,
a drop-leg holster and a knife, gloves with hard knuckles, laced and lugged combat boots
— and a scoped carbine that ends in a bayonet. Rigged and animated in
Blender and exported to `godot/models/soldier.glb`; the same script builds the grenade he
lobs (his side special) as `godot/models/grenade.glb`. His moveset is in the sim
(`sim/src/character.rs`, frame data at the end of `sim/src/moves.rs`; the root README
lists the moves).

| File | What it is |
|---|---|
| `build_soldier.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `soldier.blend`, exports `soldier.glb`, then builds and exports `grenade.glb`. |
| `soldier.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_soldier.py` | Exports `soldier.blend` to `godot/models/soldier.glb` (the chef's glTF settings, plus the baked vertex colors and both UV maps the shaders read). |
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
- **Parts.** Built like an AR carbine: a collapsible stock with a cheek riser and a
  rubber pad on its buffer tube, upper and lower receivers (ejection port cover, forward
  assist, charging handle, magwell, selector, trigger and guard), a raked pistol grip, a
  curved polymer magazine with grip ribs, a full-length top rail with its cross slots and
  folding sights, an octagonal free-float handguard with M-LOK slots, a weapon light and a
  vertical grip, a variable optic on a cantilever mount, the barrel and a birdcage flash
  hider, then the bayonet: a socket at the muzzle and a flattened steel blade. A flat
  webbing sling hangs down the near side. The hard parts are bevelled (`chamfered`).
  The whole thing is ~1.08 m from butt to point, which puts the bayonet tip near the sim's `soldier_bayonet` hitbox on the thrust
  frames.

## How it's built

- **Cloth** is metaball surfaces, one family per piece so the limbs don't fuse to the
  torso: the balaclava (crown, jaw, the cloth tenting over the nose, a gaiter bunched over
  the collar), the field shirt (thick chest, hard taper to the waist), each sleeve, each
  gloved fist with **four separate fingers plus a thumb** and a gauntlet cuff, each
  trouser leg (with a cargo pocket, bloused over the boot) and each combat boot. Negative elements crease the cloth — waist, armpit, elbow, behind the
  knee, where the cuffs gather — so it doesn't read as plastic.
- **Seams and pockets.** Cloth seams are fine ridges of the same cloth ray-cast along
  the sleeves and trouser legs (`seam`); the cargo pockets have buttoned flaps and the far
  sleeve a shoulder pocket with a loop-velcro flap.
- **Curved gear** is a `hug_patch`: a plate laid on a cloth surface by ray casting it
  over a grid of angles and heights, pushed out a few millimetres and given a thickness.
  That is the cummerbund, the shoulder, elbow and knee pads, the goggle frame and its
  lens, the helmet's side rails and velcro panels, the side MOLLE rows and the
  player-colored flag patch. `register()` makes a part ray-castable (the helmet shell,
  the plates) so later details can be laid on it.
- **The plates** are a `panel`: cast straight in along X over a grid, then pulled toward
  a flat, gently bowed sheet the way a ballistic plate holds the cloth, with a shooter's
  cut at the front's top corners and rolled edges. MOLLE webbing (`molle_rows`) is laid on
  them as 1-inch tape with bar tacks, and the pouches are sewn boxes (`soft_box`) with
  flaps, pull tabs and a line of `stitches` round each face.
- **Hard gear** is bevelled boxes and slabs (`chamfered`): buckles, the NVG shroud and
  helmet rail ends, the holster, knife and pistol grip, knuckle guards, soles, heels and
  the tread lugs under them, and every part of the rifle. Real machined and moulded parts
  never have knife edges, and the bevel catches the light. The mesh is shaded smooth with
  edges over 65° kept sharp, so a bevel reads as a rounded edge.
- **The helmet** is a dome fitted to the head (`Model.fit` at the rim), capped with a fan
  at the crown, over a cloth cover band that stands proud at the brow.
- **Straps** — the goggle strap, chinstrap with its buckle, belts, knee-pad straps,
  holster and knife straps, wrist straps, boot laces, the welt stitching — are tubes and bands fitted to the
  surface they sit on (`strap`), and take the weights of the piece they are sewn onto
  (`Model.weights_near`), so they move with it.
- **The grenade** (`build_grenade`) is a pineapple body with a fuze, a pin ring and a
  spoon, drawn by the game as the side special's projectile.

## Materials and shading

A material per part, listed in `MATERIALS` in `build_soldier.py`. The Blender colors
matter for the `.blend` and as the exported fallback; the game swaps most surfaces for
shaders, keyed by material name in `godot/models/soldier.glb.import`:

| Material | In game |
|---|---|
| `Camo` (fatigues) | `soldier_camo.tres` → `godot/shaders/camo.gdshader`: a domain-warped woodland camo with black branch strokes, sun fade, thread speckle and dirt gathered towards the boots. |
| `Vest`, `VestPouch`/`Thread`, `Balaclava`, `Boot`, `Helmet`, `Polymer`, `Pad`/`HelmetBand`/`GoggleFrame`/`Glove`/`Strap`/`Sole`/`Buckle`/`Lace` | `godot/shaders/gear.gdshader`: one worn fabric / leather / coated-shell shader in each material's own color, finish, weave, scuffing and dirt (`soldier_vest.tres`, `soldier_vest_pouch.tres`, `soldier_balaclava.tres`, `soldier_boot.tres`, `soldier_helmet.tres`, `soldier_polymer.tres`, and `soldier_hardware.tres` for the near-black hardware). |
| `Gunmetal`, `Barrel` | `soldier_metal.tres`, `soldier_barrel.tres` → `godot/shaders/weapon.gdshader`: dark anodized aluminium and parkerized steel, rough enough not to mirror the sky, with finish rubbed through in streaks along the gun. |
| `Body` | **Not** swapped: the game tints it with the player's color, and only it shows hit flashes and other state tints. It is the armband and the flag patch. |

`GoggleGlass` (the goggle lens, the optic's glass, the light's lens), `Steel` (the
bayonet) and the grenade's `Grenade` keep their own PBR values.

The three shaders share `godot/shaders/soldier.gdshaderinc` and read two things baked
into the mesh by `build_soldier.py`:

- **The rest position** of every vertex, in the UV maps (`UVMap` = (x, z), `Rest` =
  (y, 0)). Godot skins the mesh before the shader runs, so a pattern drawn at the
  skinned position would slide over the cloth as he moves; drawn at the rest position the
  camo stays printed on the fabric. Don't add real UVs to these maps.
- **Ambient occlusion** in the vertex color (`bake_occlusion`): 40 short rays per vertex,
  so creases, the gaps between pouches and under the helmet go dark. Each group — the
  body, each arm, the rifle — is only shadowed by itself, since in the rest pose the arms
  hang beside the body where they never are in the game.

Surface detail (weave, grain, wrinkles) is bump-mapped from the rest position without
tangents and fades out below a pixel, so it shows up close and doesn't shimmer at the
game's camera distance. The shaders set their own `ROUGHNESS` and `SPECULAR` rather than
taking them from the glTF material, because Godot's default specular lifts dark matte
surfaces with the sky's light — which is why the buckles and laces are swapped too.

## Ledge animations

`ledge_hang`, `ledge_climb`, `ledge_roll` and `ledge_attack` follow the sim
(`try_grab_ledge` / `ledge_getup_pos` in `sim/src/fighter.rs`, `LEDGE_ATTACK_HITBOX` in
`sim/src/world.rs`). The hanging origin sits 0.1 m outside the edge with the top of his
hurtbox level with the platform, so the corner is at model-local (0.1, 1.2). A getup
slides the origin linearly onto the stage (0.9 m in over 20 frames for the climb, 1.6
over 25 for the roll, 1.1 over 30 for the attack, and up 1.2 m); on getup frame k it has
moved (k − 1) / total of the way.

The getups are authored in *ledge space* — fixed to the stage — as a few keys
(`ledge_key`: a pose, where it stands, and contacts it holds: a fist on the corner, a
foot on the floor), then `getup` splines them and keys **every frame** with the root
motion taken back out, re-solving the held contacts by IK (`arm_ik`, the chef's `leg_ik`)
so a hand or foot stays put while the origin slides under it. The last frame is `idle`
shifted by the motion still to come, so the switch to `idle` doesn't pop.

- **Hang** (72-frame loop): the far (left) hand wrapped over the corner, the rifle held
  upright against his chest in the near hand (port arms — the only carry that clears the
  wall), swaying and breathing a little.
- **Climb**: a one-arm pull, the right knee onto the stage, up over the right foot, a
  step into the stance; the rifle comes down to the ready as he rises.
- **Roll**: a quick hoist on the corner, a full 360° forward roll in a tight tuck with
  the rifle hugged along his body (`grip` keeps it fixed to the forearm), up into the
  stance. The hips end at −360°, the same orientation as `idle`'s 0.
- **Attack**: vaults up, lands crouched with the rifle wound back, and swings it over and
  down across the stage top through the hitbox on frames 15-18.

To look at them without the game, render side views with the stage corner drawn where
the sim has it (a throwaway script: set each action, put a box at x = 0.1 − dx, top at
1.2 − dz for the frame's root motion).

## What the game relies on

- **Animation names = `Fighter::anim()` names**, 60 fps, frame 1 = sim frame 1, and every
  soldier move: the rules in
  [`art/fighter/README.md`](../fighter/README.md#rules-the-game-relies-on) apply here in
  full, except that every slot is his own (all 26 moves, grab, dash grab, pummel and all
  four throws included), plus the four ledge clips above. `godot/models/soldier.glb.import` must keep `animation/fps=60`,
  and its `_subresources` block is what swaps the shader materials.
- **`Body` must exist**, or the player color and the hit flash go somewhere else.
- **He stays 1.2 m to the top of the head** (sim hurtbox height 12 × `SCALE` 0.1), with
  his fists and feet near the sim hitboxes in `sim/src/moves.rs` on active frames (press
  **H** in game to compare). The helmet rises a little above the hurtbox, like the chef's
  toque.
- **Visual only.** Nothing reads collision from this mesh.
