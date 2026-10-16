# fight_gd

The Godot extension, built with [godot-rust](https://godot-rust.github.io)
(`godot` crate 0.5, Godot API 4.7). It registers one node class, `FightWorld`,
which is the root of `godot/main.tscn`.

Each frame:

1. `physics_process` (fixed 60 Hz) builds one `fight_sim::Input` per player, from the
   keyboard and gamepads for humans or from `Cpu::think` for CPU slots, and calls `World::step`.
2. `process` (every rendered frame) mirrors the sim state onto 3D nodes: the fighter
   model posed by `pose()`, hitbox spheres, hit sparks, HUD, and the Smash-style camera that zooms
   to fit everyone.

Gameplay logic doesn't belong here. This layer only reads the sim, except that it builds the inputs.

## Build and run

```sh
cargo build                       # → target/debug/libfight_gd.dylib (.dll / .so)
godot --path godot                # from the repo root
FIGHT_CPU=1 godot --path godot    # P2 is an easy CPU (toggle in game with C / pad View)
FIGHT_DEMO=1 godot --path godot   # every player is a CPU, hitboxes on
```

`godot/fight.gdextension` points Godot at `../target/{debug,release}/`, so
`cargo build --release` plus a release export uses the optimized library.

## Things to know

- The node tree is built in code: `build_stage`, `build_fighters` and `build_hud`
  in `ready()`. Only the light, environment and `Camera3D` live in `main.tscn`, so
  they can be tweaked in the editor.
- Controls are hard-coded in `read_input` (table in the root README). Gamepads go to
  human players in order (with P2 as CPU, the first pad drives P1). Triggers are
  axes, so shield is "trigger past 0.3". The right stick acts as a C-stick. On the
  frame it is pushed, it sends `SMASH` with the left-stick direction replaced by the
  right stick's, so it gives a smash attack on the ground and an aerial in the air.
  It needs releasing before it fires again (`FightWorld::cstick_out`). Debug keys and the pad Start (reset) /
  Back (toggle CPU) buttons are in `unhandled_input`.
- Connected joypads are printed to the console at startup and whenever they change,
  which is the quickest way to check a controller is detected.
- `SCALE` converts sim units to meters (0.1).
- Fighters are instances of `res://models/fighter.glb` (made in Blender, see
  [`art/fighter/README.md`](../art/fighter/README.md)). The `AnimationPlayer` is in
  manual mode. `pose()` plays the clip named `Fighter::anim()` and seeks it to the
  sim's frame, so visuals match frame data, freeze in hitlag and pause, and work after a
  rollback. Clips switch instantly (no blending yet). The `Body` material is
  replaced per player for the color and state tints: white hit flash, pale blue
  while a dodge is invincible, flashing while charging a smash attack (the model also
  shakes), yellow flicker when dizzy.
- The shield is a translucent sphere per fighter that shrinks with `Fighter::shield`.
  Projectiles come from `World::projectiles` and are drawn from a pool of glowing
  spheres. With **H**, hitboxes are red and grab boxes purple.
- Smoke test with no window: `godot --headless --path godot --quit-after 600`. It
  should print no `ERROR` lines.
