# fight_gd notes

- godot-rust **0.5.5**, feature `api-4-7`. Its API differs from older tutorials and
  docs (0.1–0.3). Examples: `get_tree()` returns `Gd<SceneTree>` (not `Option`), and
  engine setters take `&Gd<T>` and `&str` directly. When unsure, build and read the
  compiler error, or grep the generated code in `target/debug/build/godot-core-*/out/`.
- Keep this crate a thin view: read `World`, build `Input`s, draw. No gameplay rules
  and no AI: CPU slots (`FightWorld::cpus`) call `fight_sim::Cpu::think`.
- Sim stepping happens in `physics_process` (60 Hz, set in `godot/project.godot`).
  Visual updates happen in `process`. Don't step the sim from `process`.
- After changing anything here, run `cargo build`, then the headless smoke test from the
  root `CLAUDE.md`. For visual changes, render frames with `--write-movie` and look at them.
