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
let mut cpu = Cpu::with_level(1, 9).with_seed(42);   // same, but its own stream of choices (the balance harness)
let p2_input = cpu.think(&world);
world.step(&[p1_input, p2_input]);
```

## Modules

| File | Contents |
|---|---|
| `fixed.rs` | `Fx` Q16.16 fixed-point type, `sin_deg` / `cos_deg` lookup table |
| `input.rs` | `Input`: stick (-100..=100) and button bits (attack, jump, special, shield, grab, smash). The only thing entering the sim. |
| `character.rs` | `Character` (Chef, Pug, Samurai, Ninja, Soldier, Hobo): each one's `FighterParams`, its `Moveset` (which move each input starts) and `moves()` (moveset plus follow-ups) |
| `fighter.rs` | `FighterParams` (tuning, one const per character, including the whole-character balance knobs `damage_scale` / `knockback_scale`: percent of the damage and knockback its hits deal), `State` machine, input reading (buffers, smash flicks), which move each input picks (and the up-special reversal: a back tilt on its first `UP_SPECIAL_TURN_FRAMES`), movement physics (solid platforms' sides stop an airborne fighter below the top: `stop_at_stage_side`), ledge hang and getups (`LedgeHang` / `LedgeClimb` / `LedgeRoll` / `LedgeAttack`), jump takeoff speed (`liftoff_vx`), shield/grab/charge constants, `knockback()`, trajectory DI (`di_angle`, `world_angle`, `Fighter::di_pending`) |
| `moves.rs` | Frame data: every attack, special, grab and throw as `MoveData` (hitboxes, grab boxes, command grabs, scripted motion, projectiles and their charge growth, shattering projectiles, throws, landing behaviour, charge frame, jab combos, counters), plus dodge timings (`DodgeData`) |
| `stage.rs` | Platforms, blast zones, spawn points. `StageId` lists the selectable stages (`ALL`, `name()`, `stage()`): Boardwalk (`Stage::battlefield()`), Sandbar (`flat()`), Driftwood (`single_platform()`). |
| `world.rs` | `World::step`: fighters → grab bookkeeping → ledge occupancy (`sync_ledges`: one per edge, a fresh grab steals it) → throws → projectiles → hits and grabs (shields absorb hits) → blast zones |
| `cpu.rs` | `Cpu` computer opponent: reads the `World`, returns an `Input`. It walks or runs in to its own reach, picks moves from the move data (every hitbox, grab box, scripted motion and projectile is played forward against where it predicts the opponent will be, and scored on damage, speed, end lag and whether the knockback formula says the launch KOs or leaves the opponent offstage), anti-airs or waits under an airborne opponent rather than chasing its jumps, edge-guards from level 4 (ground moves and projectiles from the ledge; from level 7 it also jumps off after the recovering opponent, keeping a jump to come back with), picks throws the same way, mixes up ledge getups and mashes out of grabs. It defends (`guard`): once it has seen an attack for `react` frames (or a projectile is about to arrive) it plays a copy of the world forward (`rollout`) with each guard it has (`Guard`: shield, spot dodge, rolls, air dodges, its counter) and takes one that isn't hit (`guard_score`: shield health kept, frames free before the attacker within punish reach, out of a corner); out of shield it grabs, up-smashes or up-specials an attacker in its end lag (`out_of_shield`). It DIs each launch (`best_di` / `di_score`: room before a blast zone, how far offstage it ends, distance from the attacker), chases a launched opponent with the hop whose aerial a rollout lands (`chase`), and picks a `Recovery` per trip offstage by playing candidates out (`pick_recovery`: plain, high, low, an air dodge in near the ledge or for distance, drifting to the ledge), then follows it (`recover`). Moves are chosen by input slot (`Slot`) from `Character::moveset()`, never by name: `evaluate` / `simulate` play a move forward against the opponent's predicted path (`predict`), `score` and `launch` rate the hit. Difficulty knobs in `CpuLevel`: `CpuLevel::level(1..=9)` from the `LEVELS` table (plan time; `react`: how many frames into an attack it can answer it; how often it approaches, attacks, grabs, defends and dodges; `judgement`: how often it takes the best-scoring option instead of any that works; `edge_guard`, `offstage`; `di`; `recovery_mix`). `EASY` is level 3. Plans that take longer than a level's reaction time (hops, guards, jumps) are finished before it re-plans; it starts new plans only when it can act, so nothing it presses is buffered through lag. Rollouts run on clones of the world and of the CPU (`simulating`, which never rolls out itself), so it still only reads the `World` and returns an `Input`. Its RNG has a fixed seed per port; `with_seed` gives it another (deterministic) one. |

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

DI (directional influence) is Melee's trajectory DI. A hit that launches (anything but
a grounded slide under `GROUNDED_KB_THRESHOLD`) leaves its launch in
`Fighter::di_pending` as a `Trajectory` (world angle, 0 = right and 90 = up, plus speed).
On the fighter's first frame of hitstun (the frame after hitlag ends; throws have no
hitlag, so the frame after the throw), the stick held that frame turns the launch by
`di_angle`: up to `MAX_DI_DEGREES` (18°) toward the stick, scaled by the cross product of
the launch direction and the stick (so a perpendicular stick turns it fully, one along
the launch line not at all, and a stick in the deadzone does nothing). Speed and hitstun
don't change. It's read once and cleared; later stick input does nothing. Humans and
CPUs DI the same way. There is no SDI (nudging your position during hitlag) or DI on
grounded slides.

Smash-attack input: the stick goes from neutral to 0.8 or more within 3 frames of
the attack press, or the press is the `SMASH` button. A tilt is the same direction
without the flick, so the CPU (and tests) use a stick value of 60 for tilts.

Jumping: jump starts `JumpSquat` without turning (back + jump is a backward jump, so
bair still comes out; turning means a ground frame of back first). At liftoff,
`Fighter::liftoff_vx` sets `vx` like Ultimate's jump initial horizontal speed: the
stick's x (outside the deadzone) times the character's `FighterParams::jump_h_speed`,
either way, added to the ground speed left after jumpsquat traction, and clamped to
`air_speed` or to that ground speed if it's faster (so a running jump keeps its
momentum and air drift slows it as before). Full and short hops share it, and so does
jumping out of shield. Double jumps set `vx` to the stick's x times `air_speed` and
never turn; ledge jumps leave inward at `air_speed`.

Feel: movement is moderately floaty, Brawl leaning toward Melee. Gravity, top fall
speed and fast-fall speed are about 20% / 15% / 15% below their first tuning, ground
speeds about 7% and air speeds 5% lower. Jump speeds came down by about 10% with the
gravity (height ≈ v²/2g), so jumps reach the same heights (within ~2%) but hang about
12% longer: the chef's full hop peaks ~27 units up and lands 55 frames later. Floatier
fighters carry further on a vertical hit, so the shared top blast zone went up from 167
to 180 to keep vertical KO percents close. The characters keep their order: the soldier
still falls fastest and the hobo slowest.

## Units

Melee-style: 1 unit ≈ 0.1 m in Godot. Stages are laid out at 5/7 scale
(`STAGE_SCALE`: the Boardwalk's main stage is ≈97 units wide, down from 136) so
characters read 40% larger relative to them; every platform, spawn and respawn
coordinate goes through `stage.rs`'s `s()`. Blast zones don't: they're in fighter
units (how far knockback has to carry someone), so KO percents and recovery depth
don't change with the layout. The top one does depend on gravity, though: lower
gravity carries a launched fighter higher (see Feel, above). Fighters, moves and the CPU's distances are never
scaled. Speeds are in units per
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
recovers with and without a double jump, reverses its up special toward the stage, doesn't self-destruct at any level on any stage,
higher levels attack more, mashes out of grabs, grabs, shields, stays deterministic; two
top CPUs on a side platform keep fighting, it doesn't chase a jumping opponent's jumps,
level 9 edge-guards and level 1 doesn't, smash attacks at kill percent, projectiles at
range, throws toward the near ledge, every character uses a wide part of its moveset;
level 9 shields or dodges a telegraphed smash, punishes a whiffed one, DIs to survive a
hit that KOs without DI, air-dodges through an edge-guard, air-dodges in from farther
out, mixes up its recovery and chases a launched opponent, and level 1 rarely does any
of it) live in `tests/cpu.rs`. `tests/gameplay.rs` also pins the stage's solid sides (a recovery
drifting in below the top grabs the ledge instead of falling through the stage) and DI
(the 18° turn and its scaling, read on the first hitstun frame only, survival DI living
to a higher percent).
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

## Balance testing

The sim is fast and deterministic, so balance is measured by letting CPUs fight:
`cargo run --release -p fight_balance -- --games 200` plays every matchup on every
stage and prints a win-rate matrix with error bars; `--tune N` adds a buff/nerf loop
that proposes changes to `damage_scale` and `weight` as a diff. The harness lives in
its own crate, [`balance/`](../balance/README.md), and only uses the sim's public API.
Its results measure each character as the CPU plays it (it reacts to what it sees but
never guesses, and has no hand-made combo routes), so read its AI flags, Defense and
move-use tables and caveats before acting.
