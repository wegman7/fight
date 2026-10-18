# Chef model

The chef (`Character::Chef`): a portly cook with a handlebar mustache, in a
double-breasted jacket, pleated toque, neckerchief, bistro apron, dark trousers and
black shoes. He's rigged and animated in Blender and exported to `godot/models/fighter.glb`.
The same script also builds the cream pie he throws (his neutral special) as
`godot/models/pie.glb`, which the game draws as the flying projectile.

| File | What it is |
|---|---|
| `build_fighter.py` | Generates the whole asset from code: mesh, armature, every animation. Saves `fighter.blend` and exports the `.glb`, then builds and exports `pie.glb`. |
| `fighter.blend` | The Blender file. Open it to look at or edit the model by hand. |
| `export_fighter.py` | Exports `fighter.blend` to `godot/models/fighter.glb` with the settings the game expects. (`pie.glb` only comes from the build script.) |

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
  state tints. `Jacket` (also the toque), `Pants`, `Skin`, `Lip`, `Hair`, `Shoe`,
  `Button`, `Eye`, `Iris`, `Pupil` and the pie's `Tin`, `Crust`, `Cream` and `Cherry`
  keep their own colors.
- **The pie bone.** `pie` (child of `forearm.R`) carries the pie he holds. Its scale is
  keyed in every action: 0 everywhere except `pie_throw` frames 4-11, so it never
  lingers when a move is interrupted. On frame 12 it vanishes as the sim fires the
  projectile. `holding_pie(pose, facing)` aims its cream (0 = forward, 90 = up).
- **Visual only.** Hurtboxes and hitboxes stay in the sim, and nothing reads collision
  from this mesh.
- **New actions made in Blender** must be stashed (Action Editor → Stash) or be on an
  NLA track, so the exporter includes them.

The samurai (`art/samurai/build_samurai.py`) imports this script's shapes, skeleton
and pose helpers, so changing the joint positions, `guard`, `crouch`, `AIR` or the like
changes him too. Rebuild both after such a change.

## Pose convention (in `build_fighter.py`)

Angles are degrees, counter-clockwise as seen by the game camera with the fighter
facing right. `+` swings a hanging limb forward, tips the spine/head back, and raises
the toes. Child angles are relative to the parent. `leg_ik(pose, side, foot_x)` plants a
foot and solves the knee, so stances stay on the ground. `planted(pose, front, back)`
re-solves both legs after moving `hips_loc`. The near (camera-side) limbs
are `.R`.

## How it's built

- **Cloth and flesh** are metaball surfaces, one per piece so the limbs don't fuse to
  the body: head (cheeks, bulbous nose, double chin, ears, eye sockets), hair, the
  jacket's body (chest, belly, shoulders), each sleeve, fist, trouser leg and shoe.
  Each is polygonized, smoothed, decimated, and skinned by distance to its own bones
  (`by_distance`), so joints bend smoothly. Fists, hair and shoes are rigid.
- **Details** are modeled in bmesh and placed by ray casting onto those surfaces
  (`Model.hit`, `Model.fit`): the eyes, brows and handlebar mustache sit on the face,
  the toque's band is fitted to the head, the buttons and the front panel's edge are
  sewn on the jacket and take the weights of the nearest jacket vertex.
- **The apron** hangs straight down from the widest point above it in soft folds. Its
  top follows the hips and its hem follows the thighs most of the way, which keeps the
  legs behind it in most poses. High kicks still push through it.
- **The pie** (`pie_parts`) is a tin, a crimped crust rim, a cream top with ten piped
  swirls and a cherry. It's 0.26 m across, deliberately big for slapstick.
