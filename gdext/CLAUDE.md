# fight_gd notes

- godot-rust **0.5.5**, feature `api-4-7`. Its API differs from older tutorials and
  docs (0.1–0.3). Examples: `get_tree()` returns `Gd<SceneTree>` (not `Option`), and
  engine setters take `&Gd<T>` and `&str` directly. When unsure, build and read the
  compiler error, or grep the generated code in `target/debug/build/godot-core-*/out/`.
- Keep this crate a thin view: read `World`, build `Input`s, draw. No gameplay rules
  and no AI: CPU slots (`FightWorld::cpus`) call `fight_sim::Cpu::think`.
- Menus: logic and layout in `menu.rs` (no Godot nodes; only builtin types like
  `Vector2` / `Rect2`), drawing in `menu_view.rs`. A menu behaviour change needs a test
  in `menu.rs`'s `tests`. Hit tests and drawing must use the same layout functions.
  `MenuView` builds nodes once; `update` must not create nodes every frame.
- All 2D UI (menus, HUD) is placed in fixed 1600x900 coordinates (`menu::SCREEN`).
  `godot/project.godot` sets stretch mode `canvas_items` / aspect `keep`, so Godot scales
  it to the window and letterboxes other aspect ratios. Don't read the window size or
  use anchors to lay out UI. (`render_scale.rs` reads it only to size the 3D render.)
- Everything a match creates goes under `FightWorld::arena` (never `base_mut()`), so
  `clear_arena` can tear it down.
- Background music is `music.rs` (`Music`): one `AudioStreamPlayer` attached to the
  root in `ready`, swapping the looping stream on mode changes (`play_menu` /
  `play_stage`). It's presentation, not gameplay — nothing here feeds the sim.
- Sim stepping happens in `physics_process` (60 Hz, set in `godot/project.godot`).
  Visual updates happen in `process`. Don't step the sim from `process`.
- Never let the fighter `AnimationPlayer` advance on its own. Pose comes from sim
  state via `pose()` (seek to frame), which keeps it deterministic and rollback-safe.
- After changing anything here, run `cargo build`, then the headless smoke test from the
  root `CLAUDE.md`. For visual changes, render frames with `--write-movie` (add `--always-on-top`) and
  look at them. The menus need input to get past the first screen: a throwaway scene
  whose script instances `main.tscn` and sends `InputEventKey`s with
  `Input.parse_input_event` works. Re-send held keys every frame, since focus
  changes release them. Delete the scene afterwards.
