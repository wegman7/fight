# Chef model

The chef (`Character::Chef`): a portly, ruddy cook with a handlebar mustache, in a
double-breasted jacket (seams, drag folds, creased sleeves, a pen and thermometer in
the near sleeve's pocket), pleated toque, neckerchief, bistro apron with a striped
kitchen towel tucked in at the hip, check trousers that break over the shoe, and
polished black shoes with stitched soles and laces. He's rigged and animated in Blender and exported to `godot/models/fighter.glb`.
The same script also builds the cream pie he throws (his neutral special) as
`godot/models/pie.glb`, which the game draws as the flying projectile.

| File | What it is |
|---|---|
| `build_fighter.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `fighter.blend` and exports the `.glb`, then builds and exports `pie.glb`. |
| `fighter.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_fighter.py` | Exports `fighter.blend` to `godot/models/fighter.glb` with the settings the game expects (`CHEF_EXPORT`). (`pie.glb` only comes from the build script.) |
| `godot/shaders/chef_*.gdshader` | His surfaces in game: `chef_skin` (skin, lips), `chef_cloth` (jacket and toque, trousers, towel), `chef_hair`, `chef_plain` (shoes, soles, laces, nails, eyes, buttons, the pie), sharing `chef_common.gdshaderinc`. |
| `godot/models/fighter_*.tres`, `pie_*.tres` | One `ShaderMaterial` per glTF material, with its colors and settings; `fighter.glb.import` and `pie.glb.import` swap them in by material name. |

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
  `grab_hold`, `grabbed`, and the ledge clips `ledge_hang`, `ledge_climb`, `ledge_roll`,
  `ledge_attack` (see below). Dodges (`DodgeData::name`): `spotdodge`, `roll_f`, `roll_b`,
  `airdodge`. Every chef move's `MoveData::name` (`Character::Chef.moves()`): `jab`, `jab2`, `jab3`, `ftilt`, `utilt`,
  `dtilt`, `dashattack`, `fsmash`, `usmash`, `dsmash`, `nair`, `fair`, `bair`, `uair`,
  `dair`, `pie_throw`, `special_s`, `special_u`, `special_d`, `special_d_land`, `grab`,
  `dashgrab`, `pummel`, `fthrow`, `bthrow`, `uthrow`, `dthrow`. A pose with no
  animation stays frozen on its last frame, and the game logs an `ERROR` for it at
  startup. A new move needs a new action with the same name. (Other characters'
  models, like the pug and the samurai, have their own move names.)
- **60 fps, frame 1 = sim frame 1.** Moves are keyed on their sim frames (Blender
  frame 5 of `ftilt` is FTilt's frame 5). The export slides each action so frame 1
  is time 0. `godot/models/fighter.glb.import` has `animation/fps=60`; Godot's
  default 30 would halve the precision.
- **How each pose is timed** (`pose()` in `gdext/src/lib.rs`): moves, dodges and
  `jumpsquat` follow the state's frame counter (a charging smash attack holds its
  `charge_frame` pose), `land` plays its *last* N frames as landing lag
  counts down, and the rest loop on the world frame. Make loops start and end on the
  same pose.
- **Scale and facing:** meters, feet at the origin, facing +X, 1.2 m tall to the top
  of the head (sim hurtbox height 12 × `SCALE` 0.1); the toque rises to about 1.38 m. Keep fists and feet near the sim hitboxes in
  `sim/src/moves.rs` on active frames (press **H** in game to compare).
- **Materials:** surfaces using the material named `Body` (the apron, its ties and the
  neckerchief) get the player's color in game, and only they show hit flashes and other
  state tints. `Jacket` (also the toque and sleeve pocket), `Pants`, `Towel`, `Skin`,
  `Lip`, `Nail`, `Hair` (also brows, lashes, mustache), `Shoe`, `Sole`, `Lace`, `Button`
  (also the pen), `Eye`, `Iris`, `Pupil` and the pie's `Tin` (also the thermometer),
  `Crust`, `Cream` and `Cherry` keep their own look. Every one but `Body` is replaced on
  import by its `.tres` shader material, so the colors in `MATERIALS` only show in
  Blender. A new material needs a `.tres` and an entry in `fighter.glb.import`.
- **Shader inputs:** glTF drops Blender's procedural node trees, so detail lives in the
  Godot shaders, which read two things the script bakes into the mesh
  (`surface_data`): UV = (rest x, rest z) and UV2.x = rest y, the rest-pose position,
  so weave, pores and the trouser check stick to the surface as it deforms (no UV
  unwrap); and the color attribute, R = ambient occlusion baked in the rest pose (only
  from parts that move together, `AO_GROUP`), G/B = per-material masks (`masks`:
  flushed cheeks/nose/ears and stubble on the skin, stains on the jacket, gray temples
  and strand direction on the hair, creases on the shoes, pink corners on the eyes).
  The export needs `CHEF_EXPORT` (`export_vertex_color="ACTIVE"`) to keep the colors.
- **The pie bone.** `pie` (child of `forearm.R`) carries the pie he holds. Its scale is
  keyed in every action: 0 everywhere except `pie_throw` frames 4-11, so it never
  lingers when a move is interrupted. On frame 12 it vanishes as the sim fires the
  projectile. `holding_pie(pose, facing)` aims its cream (0 = forward, 90 = up).
- **Ledge clips.** On a ledge the sim puts the origin 0.1 m outside the edge with the
  top of the 1.2 m hurtbox level with the deck, so the corner is at model (0.1, 1.2).
  `ledge_hang` (80 frames) loops on the world clock: fists on the corner, dangling with
  a slow sway. The getups follow their state's frame and the sim slides the origin
  linearly onto the stage (`ledge_getup_pos`): `ledge_climb` 20 frames / 0.8 m in,
  `ledge_roll` 25 / 1.6 m (a hoist, then a tucked forward roll, one full turn of the
  hips), `ledge_attack` 30 / 1.1 m (hoist, then a low sweeping kick on the active
  frames 15-18). `ledge_clip` keys them in ledge space (origin = the corner) and
  converts every frame to model space, re-solving the arms (`arm_ik`) and legs while
  hands grip the corner or feet are planted, and each ends exactly on `guard()` (idle).
  `joints(pose)` is the side-view forward kinematics they use.
- **Visual only.** Hurtboxes and hitboxes stay in the sim, and nothing reads collision
  from this mesh.
- **New actions made in Blender** must be stashed (Action Editor → Stash) or be on an
  NLA track, so the exporter includes them.

The samurai, ninja, soldier and hobo scripts import this script's skeleton (`BONES`),
`Model`, `Blob`, `hand_blob` (the samurai), `export` and pose helpers, so changing the
joint positions, `guard`, `crouch`, `AIR` or the like changes them too. Keep those
backward compatible (their materials are still `(color, roughness, metallic)` tuples)
and rebuild them after such a change.

## Pose convention (in `build_fighter.py`)

Angles are degrees, counter-clockwise as seen by the game camera with the fighter
facing right. `+` swings a hanging limb forward, tips the spine/head back, and raises
the toes. Child angles are relative to the parent. `leg_ik(pose, side, foot_x)` plants a
foot and solves the knee, so stances stay on the ground. `planted(pose, front, back)`
re-solves both legs after moving `hips_loc`. The near (camera-side) limbs
are `.R`.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece so the limbs don't fuse to
  the body: head (cheeks, cheekbones, jowls, a big nose with wings and nostrils, smile
  lines, cupid's-bow lips, double chin, ears with a rolled rim, lobe and bowl, eye
  sockets), hair, the jacket's body (chest, belly, shoulders, drag folds), each sleeve
  (elbow creases), fist (`chef_hand_blob`: three-segment fingers, knuckles, tendons;
  the plainer `hand_blob` is the samurai's), trouser leg (folds at the knee, the break
  over the shoe) and shoe. Creases are negative metaballs.
  Each is polygonized, smoothed, decimated, and skinned by distance to its own bones
  (`by_distance`), so joints bend smoothly. Fists, hair and shoes are rigid.
- **Details** are modeled in bmesh and placed by ray casting onto those surfaces
  (`Model.hit`, `Model.fit`): the eyes (an iris and pupil set into the eyeball, upper and
  lower lids with rounded margins, a lid crease and lashes, `eye_and_lids`), the brows
  and handlebar mustache (a base tube with seeded individual hairs over it, `strands`)
  sit on the face, the thumbnail on the fist, seams (`surface_line`) and the pen pocket
  on the jacket, soles and laces on the shoes,
  the toque's band is fitted to the head, the buttons and the front panel's edge are
  sewn on the jacket and take the weights of the nearest jacket vertex.
- **The apron** hangs straight down from the widest point above it in soft folds. Its
  top follows the hips and its hem follows the thighs most of the way, which keeps the
  legs behind it in most poses. High kicks still push through it.
- **The pie** (`pie_parts`) is a tin, a crimped crust rim, a cream top with ten piped
  swirls and a cherry. It's 0.26 m across, deliberately big for slapstick.
