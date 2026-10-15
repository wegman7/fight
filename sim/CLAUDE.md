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
- New move → add a `MoveId` variant, a `static MoveData` in `moves.rs`, and pick it in
  `Fighter::step`. Hitbox `x` is mirrored by facing automatically.
- Run `cargo test -p fight_sim` after every change. `rollback_resimulation_is_bit_identical`
  guards determinism.
