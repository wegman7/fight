# fight_sim

The whole game's rules as a plain Rust library. It has no Godot, no floats and no
I/O, so everything can be tested in milliseconds with `cargo test`.

## API in one screen

```rust
let mut world = World::new(Stage::battlefield(), /* players */ 2, /* stocks */ 3);

// Once per frame (60 Hz), one Input per player:
world.step(&[p1_input, p2_input]);

world.fighters[1].percent;   // damage
world.fighters[1].state;     // State::Ground, State::Shield, State::Attack { mv, .. }, ...
world.fighters[1].shield;    // shield health, out of SHIELD_MAX
world.projectiles;           // energy shots in flight
world.events;                // Event::Hit / ShieldHit / ShieldBreak / Grab / Ko from the last step
world.active_hitboxes();     // hitboxes and grab boxes, for debug drawing
let snapshot = world.clone(); // full save state (rollback, replays)

// A computer player is just another input source:
let mut cpu = Cpu::easy(1);   // drives fighter 1
let p2_input = cpu.think(&world);
world.step(&[p1_input, p2_input]);
```

## Modules

| File | Contents |
|---|---|
| `fixed.rs` | `Fx` Q16.16 fixed-point type, `sin_deg` / `cos_deg` lookup table |
| `input.rs` | `Input`: stick (-100..=100) and button bits (attack, jump, special, shield, grab, smash). The only thing entering the sim. |
| `fighter.rs` | `FighterParams` (tuning), `State` machine, input reading (buffers, smash flicks), which move each input picks, movement physics, shield/grab/charge constants, `knockback()` |
| `moves.rs` | Frame data: every attack, special, grab and throw as `MoveData` (hitboxes, grab boxes, scripted motion, projectiles, throws, landing behaviour, charge frame, jab combos), plus dodge timings (`DodgeData`) |
| `stage.rs` | Platforms, blast zones, spawn points |
| `world.rs` | `World::step`: fighters → grab bookkeeping → throws → projectiles → hits and grabs (shields absorb hits) → blast zones |
| `cpu.rs` | `Cpu` computer opponent: reads the `World`, returns an `Input`. It walks, tilts, hops into nair, grabs and throws, sometimes shields, mashes out of grabs, and recovers with double jump then up special. Difficulty knobs in `CpuLevel` (only `EASY` so far). |

## How a move works

A move is a `MoveId` plus a `static MoveData`. While it runs the fighter is in
`State::Attack { mv, frame, .. }`, and the frame counts up from 1. Everything else is data:

- `hitboxes` / `grabbox`: active frame ranges and offsets from the feet.
- `motion`: overrides velocity on some frames (lunges, the uppercut's rise, the
  ground pound's plunge). A `vy` also turns gravity off for that frame.
- `projectile`: fired once, on the frame it names. `throw`: applied once to the
  held fighter (a pummel just deals damage).
- `landing`: keep going, landing lag (aerials, specials), or switch to another move.
- `charge_frame` (smash attacks), `combo` (jab chains), `special_fall` (helpless afterwards).

Dodges are `State::Dodge { kind, frame }` with timings in `DodgeData`.

Smash-attack input: the stick goes from neutral to 0.8 or more within 3 frames of
the attack press, or the press is the `SMASH` button. A tilt is the same direction
without the flick, so the CPU (and tests) use a stick value of 60 for tilts.

## Units

Melee-style: 1 unit ≈ 0.1 m in Godot. The main stage is 136 units wide. Speeds
are in units per frame, and frame numbers are 1-based like Smash frame data
(a hitbox with `first: 2` is a "frame 2 jab").

## Run tests

```sh
cargo test -p fight_sim              # from the repo root
cargo test -p fight_sim knockback    # filter by test name
cargo test -p fight_sim -- --nocapture
```

## Writing tests

Gameplay tests live in `tests/gameplay.rs`. CPU behaviour tests (engages,
recovers with and without a double jump, doesn't self-destruct, mashes out of grabs,
grabs, shields, stays deterministic) live in `tests/cpu.rs`.
The helpers at the top of `gameplay.rs` (`world()`, `press()`, `stick()`,
`run()`) keep tests short. The pattern is: set up, feed inputs frame by frame,
then assert.

```rust
#[test]
fn ftilt_kos_at_high_percent() {
    let mut w = world();
    w.fighters[0].x = Fx::int(40);       // P1 near the right ledge
    w.fighters[1].x = Fx::int(48);       // P2 just in front
    w.fighters[1].percent = 150;

    w.step(&[Input { stick_x: 100, ..press(Input::ATTACK) }, NONE]);
    run(&mut w, 400, NONE, NONE);

    assert_eq!(w.fighters[1].stocks, 2);
}
```

Helpers `input(x, y, buttons)`, `airborne()` (put a fighter in mid-air) and `mv()`
(the current move, if any) are there too, plus `grabbed()` for grab/throw tests.

When you change frame data or physics on purpose, update the test that pins it.
When you add a mechanic, add a test describing it in Smash terms ("jab comes out
frame 2", "short hop peaks lower than full hop").
