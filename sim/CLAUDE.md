# fight_sim rules

- **No `f32`/`f64` in simulation logic.** Use `Fx` (Q16.16). Write literals with
  `Fx::int(n)` / `Fx::ratio(num, den)` (both `const`). `Fx::to_f32` is for renderers only.
- Trig only via `sin_deg` / `cos_deg` (integer degrees, table lookup).
- Squared distances can overflow `Fx`. Compute them on `.raw() as i64` like `Fighter::hurtbox_overlaps`.
- Iteration order must be deterministic: `Vec`s and indices, no `HashMap`/`HashSet`.
- Hit detection is two-phase in `World::resolve_hits`: collect everything first, then
  apply, so simultaneous hits trade regardless of player index. Keep it that way.
- New state or mechanic → new variant/fields on `Fighter`/`State`, plus a test in
  `tests/gameplay.rs` asserting it in frame-exact terms.
- New move → add a `MoveId` variant, a `static MoveData` in `moves.rs` (start from
  `..BASE`), and pick it in `Fighter::step` (`ground_attack`, `aerial`, `start_special`,
  the `Holding` branch...). Hitbox/grab box/motion/projectile/throw `x` are forward
  offsets, mirrored by facing automatically. Its `name` needs a matching animation in
  `art/fighter/build_fighter.py`.
- Anything that happens once on a move frame (firing a projectile, applying a throw)
  must check `Fighter::frame_advanced`. The frame number alone repeats during hitlag
  and while a smash attack charges.
- Interactions between two fighters (hits, grabs, throws, keeping a held fighter in
  hand) happen in `World`, never in `Fighter::step`, which only sees itself.
  `sync_grabs` keeps `holding` and `State::Held` consistent. Run it after
  anything that can break a grab.
- Tests that press attack with a direction from neutral get a smash attack. Use stick
  60 (not 100) for tilts.
- CPU players (`cpu.rs`) read `&World` and return an `Input`, nothing else. Their
  randomness comes from the `rng` field (xorshift), never from time or the OS, so CPU
  matches replay identically. Behaviour changes need a test in `tests/cpu.rs`.
- Run `cargo test -p fight_sim` after every change. `rollback_resimulation_is_bit_identical`
  guards determinism.
