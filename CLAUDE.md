# Fight — project guide

2.5D platform fighter (Smash-like mechanics, original content). Rust workspace + Godot 4.7.

- `sim/` (`fight_sim`): all gameplay rules, deterministic, engine-free. See `sim/CLAUDE.md`.
- `gdext/` (`fight_gd`): godot-rust extension that feeds input to the sim and renders it. See `gdext/CLAUDE.md`.
- `godot/`: Godot project. `main.tscn` root node is `FightWorld` (defined in Rust).

## Commands

```sh
cargo test                                         # sim tests: run after any sim change
cargo clippy --workspace --all-targets             # keep at zero warnings
cargo build                                        # required before running Godot
godot --headless --path godot --quit-after 600     # smoke test: must print no ERROR lines
FIGHT_DEMO=1 godot --path godot                    # visual check: CPUs fight, hitboxes on
FIGHT_CPU=1 godot --path godot                     # play P1 vs an easy CPU (or press C in game)
godot --path godot --write-movie <dir>/f.png --fixed-fps 60 --quit-after 120   # render frames to PNG for inspection
```

If `cargo` isn't on PATH, prefix with `. "$HOME/.cargo/env";`.

## Architecture rules

- **Gameplay goes in `sim/`, never in `gdext/`.** If it affects who wins (movement,
  hits, damage, timers), it's in the sim and has a test. `gdext` only builds `Input`s
  and draws state.
- **The sim is deterministic.** No floats, no `HashMap` iteration, no time or
  randomness inside `sim/`. `World` must stay `Clone + PartialEq` (rollback snapshots).
- Frame data uses Smash conventions: 1-based frames, angles in degrees (0 = forward,
  90 = up), knockback with Melee/Brawl formula constants.

## Known quirks

- `godot --headless --import` sometimes segfaults on exit inside Godot itself
  (no frames in our library). Rerun it. Game runs aren't affected.
- If Godot says `Cannot get class 'FightWorld'`, the extension isn't registered:
  check `godot/.godot/extension_list.cfg` contains `res://fight.gdextension`
  (re-import to regenerate), and that `cargo build` produced the dylib.
