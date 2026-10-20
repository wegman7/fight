# fight_sim

The whole game's rules as a plain Rust library. It has no Godot, no floats and no
I/O, so everything can be tested in milliseconds with `cargo test`.

## API in one screen

```rust
let mut world = World::new(StageId::Sandbar.stage(), &[Character::Chef, Character::Pug], /* stocks */ 3);

// Once per frame (60 Hz), one Input per player:
world.step(&[p1_input, p2_input]);

world.fighters[1].percent;   // damage
world.fighters[1].state;     // State::Ground, State::Shield, State::Attack { mv, .. }, ...
world.fighters[1].shield;    // shield health, out of SHIELD_MAX
world.projectiles;           // pies and sneeze clouds in flight
world.events;                // Event::Hit / ShieldHit / ShieldBreak / Grab / Counter / Shatter / ProjectileLanded / Ko from the last step
world.active_hitboxes();     // hitboxes and grab boxes, for debug drawing
let snapshot = world.clone(); // full save state (rollback, replays)

// A computer player is just another input source:
let mut cpu = Cpu::with_level(1, 9);   // drives fighter 1, at Melee-style level 9 (1-9; Cpu::easy is 3)
let p2_input = cpu.think(&world);
world.step(&[p1_input, p2_input]);
```

## Modules

| File | Contents |
|---|---|
| `fixed.rs` | `Fx` Q16.16 fixed-point type, `sin_deg` / `cos_deg` lookup table |
| `input.rs` | `Input`: stick (-100..=100) and button bits (attack, jump, special, shield, grab, smash). The only thing entering the sim. |
| `character.rs` | `Character` (Chef, Pug, Samurai, Ninja, Soldier, Hobo): each one's `FighterParams`, its `Moveset` (which move each input starts) and `moves()` (moveset plus follow-ups) |
| `fighter.rs` | `FighterParams` (tuning, one const per character), `State` machine, input reading (buffers, smash flicks), which move each input picks, movement physics, ledge hang and getups (`LedgeHang` / `LedgeClimb` / `LedgeRoll` / `LedgeAttack`), shield/grab/charge constants, `knockback()` |
| `moves.rs` | Frame data: every attack, special, grab and throw as `MoveData` (hitboxes, grab boxes, command grabs, scripted motion, projectiles and their charge growth, shattering projectiles, throws, landing behaviour, charge frame, jab combos, counters), plus dodge timings (`DodgeData`) |
| `stage.rs` | Platforms, blast zones, spawn points. `StageId` lists the selectable stages (`ALL`, `name()`, `stage()`): Boardwalk (`Stage::battlefield()`), Sandbar (`flat()`), Driftwood (`single_platform()`). |
| `world.rs` | `World::step`: fighters → grab bookkeeping → ledge occupancy (`sync_ledges`: one per edge, a fresh grab steals it) → throws → projectiles → hits and grabs (shields absorb hits) → blast zones |
| `cpu.rs` | `Cpu` computer opponent: reads the `World`, returns an `Input`. It walks, tilts, hops into nair, grabs and throws, sometimes shields, mashes out of grabs, recovers with double jump then up special, and climbs back up from a ledge. Difficulty knobs in `CpuLevel`: `CpuLevel::level(1..=9)` from the `LEVELS` table (reaction time, and how often it approaches, attacks, grabs and shields). `EASY` is level 3. Plans that take longer than a level's reaction time (hop attacks, shielding, jumps) are finished before it re-plans. |

## How a move works

A move is a `MoveId` plus a `static MoveData`. While it runs the fighter is in
`State::Attack { mv, frame, .. }`, and the frame counts up from 1. Everything else is data:

- `hitboxes` / `grabbox`: active frame ranges and offsets from the feet. A grab box
  with `misses_shields` doesn't catch shielding fighters. With `on_grab`, a catch
  starts that move instead of holding (a command grab: the pug's tackle → ride).
- `motion`: overrides velocity on some frames (lunges, the uppercut's rise, the
  ground pound's plunge). A `vy` also turns gravity off for that frame.
- `projectile`: fired once, on the frame it names. It flies at `speed`; with `gravity`
  it is lobbed (starts rising at `vy`, arcs down) and is gone when it comes down on a
  platform (`Event::ProjectileLanded`, the chef's pie). If the move was charged, its
  `growth` adds radius, damage, knockback and lifetime in proportion to the charge, and
  can push the shooter back (`Projectile::radius()` / `damage()` / `base_kb()`).
  With an `explosion`, it blows up when it lands (or, with `on_contact`, the moment it
  touches a fighter) and hits everyone in its radius (`Event::Explosion`, the
  soldier's grenade).
- `shatter`: a shattering projectile bursts when it lands or expires — everyone within
  `radius` of where it stopped takes the hit, sent away from the burst point
  (`Event::Shatter`, the hobo's bottle). Declared on the move (`MoveData::shatter`), so
  any character's lobbed projectile can use it. A direct hit mid-flight still applies
  the projectile's own hit and never shatters.
- `throws`: each applied once to the held fighter on its frame. A pummel only deals
  damage; a releasing throw launches and ends the hold, so later entries are skipped.
  Several in one move make a multi-hit ride (the pug's tackle).
- `landing`: keep going, landing lag (aerials, specials), or switch to another move.
- `charge_frame`: holding `charge_with` (attack or smash by default; special for the
  pug's sneeze) freezes the move there for up to `MAX_CHARGE` frames.
- `combo` (jab chains; a move can chain into itself,
  like the pug's nibbles), `special_fall` (helpless afterwards).
- `counter`: hit during its window, the fighter takes nothing, turns toward the
  attacker and switches to another move, briefly intangible (the pug's play dead →
  pounce, the soldier's riot shield → bash). Handled in `World::resolve_hits`, which sends `Event::Counter`.

Which move an input starts depends on the fighter's `Character`: `Fighter::step`
reads the input, then picks the slot from `character.moveset()`.

Dodges are `State::Dodge { kind, frame }` with timings in `DodgeData`.

Smash-attack input: the stick goes from neutral to 0.8 or more within 3 frames of
the attack press, or the press is the `SMASH` button. A tilt is the same direction
without the flick, so the CPU (and tests) use a stick value of 60 for tilts.

## Units

Melee-style: 1 unit ≈ 0.1 m in Godot. The main stage is laid out at 5/6 scale
(≈113 units wide, down from 136) so characters read ~20% larger relative to it;
every stage coordinate goes through `stage.rs`'s `s()`. Speeds are in units per
frame, and frame numbers are 1-based like Smash frame data (a hitbox with
`first: 2` is a "frame 2 jab").

## Run tests

```sh
cargo test -p fight_sim              # from the repo root
cargo test -p fight_sim knockback    # filter by test name
cargo test -p fight_sim -- --nocapture
```

## Writing tests

Gameplay tests live in `tests/gameplay.rs` (the chef), `tests/pug.rs` (the pug's
moves, tuning and play-dead counter), `tests/samurai.rs` (the samurai's moves, reach,
tipper, charged focus cut, vault and its strike, cyclone and parry), `tests/ninja.rs`
(the ninja's moves, tuning, shuriken, shadow dash, smoke bomb and substitution counter),
`tests/soldier.rs` (the soldier's moves, tuning, rifle shot, grenade blast, blast jump
and riot-shield counter) and `tests/hobo.rs` (the hobo's moves, tuning, bottle shatter,
cart charge, fizz rocket and passed-out counter). CPU behaviour tests (engages,
recovers with and without a double jump, doesn't self-destruct at any level on any stage,
higher levels attack more, mashes out of grabs, grabs, shields, stays deterministic) live
in `tests/cpu.rs`.
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
