# fight_balance rules

- This crate is a tool around `fight_sim`, never gameplay. It may use floats, threads
  and files; the sim may not, so statistics, reporting and I/O stay here.
- It only drives the sim through its public API: `World::new`/`step`, `Cpu::think`
  (seeded with `Cpu::with_seed`), and `Fighter::params` for tuning overrides. Don't add
  harness-only hooks to the sim's step path; a balance knob that needs one belongs in
  `FighterParams` (like `damage_scale` / `knockback_scale`) with a sim test.
- Results must be a pure function of the config and seed: no time, no `HashMap`
  iteration, results collected in schedule order whatever the thread count. Keep
  `tournaments_are_deterministic_whatever_the_thread_count` passing.
- Never write to the repo's source. Suggestions go to stdout or the `--report` /
  `--json` / `--csv` files the user names; applying them is a separate, reviewed commit.
- Don't hardcode current tuning values or win rates in code or tests: other changes
  move them. Tests assert properties (determinism, termination, mirrors near 50%,
  direction of a change) on small runs that finish in about a second in debug.
- New per-match stat → `MatchResult` (runner), tally in `PlayStats` (summary), show it
  in `report.rs` (text and JSON). New AI-quality flag → `AiFlag`, decide whether it
  `blocks_tuning`, and document it in `README.md`'s caveat section.
- After a CPU (`sim/src/cpu.rs`) or tuning change, re-run the harness; the README's
  numbers aren't kept in it on purpose.
- Run `cargo test -p fight_balance` and keep `cargo clippy --workspace --all-targets` clean.
