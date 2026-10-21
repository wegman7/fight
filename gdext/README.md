# fight_gd

The Godot extension, built with [godot-rust](https://godot-rust.github.io)
(`godot` crate 0.5, Godot API 4.7). It registers one node class, `FightWorld`,
which is the root of `godot/main.tscn`.

It starts in the menus (`Mode::Menu`) and switches to `Mode::Match` once one is chosen.

In the menus, `physics_process` reads each port's controls (`read_menu_input`) into
`menu::Menu::update`, and `process` draws the result with `MenuView`. In a match, each frame:

1. `physics_process` (fixed 60 Hz) builds one `fight_sim::Input` per player, from the
   keyboard and gamepads for humans or from `Cpu::think` for CPU slots, and calls `World::step`.
2. `process` (every rendered frame) mirrors the sim state onto 3D nodes: the fighter
   model posed by `pose()`, debug hitbox spheres (**H**), hit sparks, HUD, and the Smash-style camera that zooms
   to fit everyone.

Gameplay logic doesn't belong here. This layer only reads the sim, except that it builds the inputs.

## Build and run

```sh
cargo build                       # → target/debug/libfight_gd.dylib (.dll / .so)
cargo test -p fight_gd            # menu logic tests (no Godot needed)
godot --path godot                # from the repo root
FIGHT_CPU=3 godot --path godot    # skip the menus: P2 is a level-3 CPU (any of 1-9)
FIGHT_DEMO=1 godot --path godot   # skip the menus: both players are level-3 CPUs, hitboxes on
FIGHT_STAGE=driftwood FIGHT_DEMO=1 godot --path godot   # stage for the two above (default Boardwalk)
FIGHT_CHARACTERS=samurai,pug FIGHT_DEMO=1 godot --path godot   # P1's and P2's characters for them (default chef, pug)
FIGHT_MUSIC_VOLUME=50 godot --path godot   # music volume 0-100 (default 70)
```

`godot/fight.gdextension` points Godot at `../target/{debug,release}/`, so
`cargo build --release` plus a release export uses the optimized library.

## Menus

| File | Contents |
|---|---|
| `menu.rs` | `Menu`: the screen (`Screen::Stocks` → `Characters` → `Stages`), stock count, the four player `Slot`s (`SlotKind` HMN / CPU / N/A, character, CPU level, where its coin sits), the four `Hand`s (position, which coin it carries), the stage cursor. `update` takes one `PortInput` per port (held buttons; it finds the presses itself) and returns `MenuEvent::StartMatch(MatchSetup)` or `Quit`. Also the layout: `portrait_rect`, `slot_rect`, `toggle_rect`, `level_rect`, `stocks_rect`, `card_rect`, used for both hit tests and drawing. No Godot nodes, so its tests run under `cargo test`. |
| `menu_view.rs` | `MenuView`: builds the Control nodes once (on a `CanvasLayer` over the beach) and each frame moves, recolors and shows them from `Menu`. Characters are drawn by `Render`, a `SubViewport` with its own 3D world holding the model, posed on the menu's frame counter (never free-running). Stage cards show a schematic drawn from the sim's `Stage` platforms. |

A `MatchSetup` lists the players by port. Fighter `i` of the `World` is
`setup.players[i]`, so with P1 off, fighter 0 is P2: it keeps P2's color, name and
controls. `FightWorld::start_match` builds a match from a setup, `new_match` restarts
it (**R**), and `leave_match` frees it and returns to character select. `Menu::enter`
makes the next screen ignore buttons still held from before, so the press that left a
screen doesn't also act on the next one.

## Things to know

- The node tree is built in code. The menus are built once in `ready()`. A match's
  nodes (`build_stage`, `build_fighters`, `build_hud`, plus effects) all go under
  `FightWorld::arena`, which `clear_arena` empties when the match ends. `build_stage` puts a model from [`art/stage/`](../art/stage/README.md)
  on each sim platform (`stage.glb` for the solid one, `raft.glb` for soft ones),
  stretched in x from the width it was built at (`STAGE_MODEL_WIDTH`, `RAFT_MODEL_WIDTH`) and
  shrunk in height and depth by the sim's `STAGE_SCALE`, so the models keep the layout's proportions. Only the light, environment, `Camera3D` and the decorative backdrop
  live in `main.tscn`, so they can be tweaked in the editor. The backdrop (`Beach`,
  `Clouds`) is a subdivided plane shaped by `shaders/sand.gdshader`, an ocean plane
  using `shaders/ocean.gdshader`, and props from `art/beach/` (palms, rocks,
  sailboats). Its ground sits at y = −12, just under the bottom blast zone, so
  fighters are KO'd before they'd reach the sand. The water animates on shader
  `TIME`; that's fine because it's scenery, never gameplay.
- Controls are hard-coded in `KEYS`, `read_input` and `read_menu_input` (tables in the
  root README). The nth connected gamepad is port n, like Melee's ports; ports 1 and 2
  also have keyboard keys. Face buttons follow the Switch layout by position: SDL's
  `JoyButton::B` (right) is attack / confirm and `JoyButton::A` (bottom) is special /
  back. Triggers are
  axes, so shield is "trigger past 0.3". The right stick acts as a C-stick. On the
  frame it is pushed, it sends `SMASH` with the left-stick direction replaced by the
  right stick's, so it gives a smash attack on the ground and an aerial in the air.
  It needs releasing before it fires again (`FightWorld::cstick_out`). In-match keys
  (debug keys, R, Esc) and the pad Start (pause, or menu once someone has won) / Back
  (menu while paused) buttons are in `unhandled_input`; the menus poll instead.
- Connected joypads are printed to the console at startup and whenever they change,
  which is the quickest way to check a controller is detected.
- `SCALE` converts sim units to meters (0.1).
- Background music lives in `music.rs`: a single `AudioStreamPlayer` swaps between
  `godot/music/untitled.mp3` (menus) and `godot/music/rising_motif.mp3` (matches), both
  set to loop. `start_match` starts the stage track, `leave_match` and startup start the
  menu track. Volume is `FIGHT_MUSIC_VOLUME` (0-100) and the `-` / `=` keys (in
  `unhandled_input`, so they work in both modes).
- Each player plays the `fight_sim::Character` chosen in the menus. `look()` maps it to
  a model, `res://models/fighter.glb`, `pug.glb`, `samurai.glb`, `ninja.glb`,
  `soldier.glb` or `hobo.glb` (made in Blender, see [`art/fighter/README.md`](../art/fighter/README.md),
  [`art/pug/README.md`](../art/pug/README.md),
  [`art/samurai/README.md`](../art/samurai/README.md),
  [`art/ninja/README.md`](../art/ninja/README.md),
  [`art/soldier/README.md`](../art/soldier/README.md) and
  [`art/hobo/README.md`](../art/hobo/README.md)); `tinted_model` loads it with the `Body`
  material swapped for the player's color (in game and in the menus). At startup,
  `check_models` logs an `ERROR` for every animation a character can need
  (`STATE_ANIMS`, `Character::moves()`, dodges) that its model lacks. The HUD shows each
  player's character. The `AnimationPlayer` is in
  manual mode. `pose()` plays the clip named `Fighter::anim()` and seeks it to the
  sim's frame, so visuals match frame data, freeze in hitlag and pause, and work after a
  rollback. Clips switch instantly (no blending yet). The `Body` material is
  replaced per player for the color and state tints: white hit flash, pale blue
  while a dodge is invincible, flashing while charging a smash attack (the model also
  shakes), yellow flicker when dizzy. On the pug, `Body` is only the collar; on the
  samurai, his headband and sash; on the ninja, his headband and belt; on the soldier,
  his armband; on the hobo, the sweater under his coat.
- The shield is a translucent sphere per fighter that shrinks with `Fighter::shield`.
  Projectiles come from `World::projectiles` and are drawn from a pool, each as its
  owner's `shot_for(character, move)` (a character with one projectile just falls back
  to `look().shot`; the soldier has two): `Shot::Orb` is a glowing sphere (the pug's
  sneeze, a pale puff; the ninja's shuriken, a pale steel; the soldier's bullet; and the
  hobo's bottle, a green glass orb; sized by `Projectile::radius()`, which grows with
  charge); `Shot::Model` loads a model
  (the chef's `res://models/pie.glb`, the soldier's `res://models/grenade.glb`), turns it
  the way it flies and tilts it with its arc. Model shots burst into cream blobs (`Splat`)
  where they hit (`Event::Hit` /
  `ShieldHit` with `projectile: true`) or land (`Event::ProjectileLanded`, a puddle on
  the floor); other hits make a spark. `Event::Counter` (the pug's play dead, the samurai's parry,
  the soldier's riot shield) and `Event::Shatter` (the hobo's bottle bursting as it lands)
  make a spark and a small shake, and `Event::Explosion` (the grenade's blast) a bigger
  spark and shake. With **H**, hitboxes are red and grab boxes purple.
- A hit spark (`spawn_spark` / `update_sparks`) is a Smash-style impact starburst, not a
  sphere: one camera-facing quad drawn by `godot/shaders/hit_spark.gdshader` as a white-hot
  core flash, alternating long and short tapered spikes that fly outward and thin away, and
  a faint shock ring. It pops on its first frame and is gone after 8-12 render frames;
  `update_sparks` sets the shader's `age` each frame, so nothing free-runs. `SparkKind`
  picks the look (`SparkKind::style`): a hit grows with knockback (still `0.3 + kb / 150`,
  scaled up) and turns redder, brighter and spikier, and from `SPARK_STREAK_KB` adds long
  streaks along the defender's launch direction (read from its `kb_x` / `kb_y` right after
  the hit). Shield hits are small, dim and cool blue; explosions big and red-orange;
  counters gold; shatters glassy green.
- Smoke test with no window: `godot --headless --path godot --quit-after 600` (sits in
  the menus) and `FIGHT_DEMO=1 godot --headless --path godot --quit-after 900` (plays a
  match). They should print no `ERROR` lines.
