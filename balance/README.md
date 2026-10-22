# fight_balance

Balance testing on the headless sim. Level-9 CPUs play every matchup on every stage
(no Godot, pure Rust), the results become a win-rate matrix with error bars, and an
optional loop proposes buffs and nerfs. It never edits the source: suggestions come
out as a report and a diff to apply by hand.

It's a separate crate so the sim keeps its rules (no floats, no I/O, no threads): the
harness uses all three for statistics, reports and speed. The sim it drives is
still deterministic, so **the same seed always gives the same numbers**.

## Run

```sh
cargo run --release -p fight_balance -- --games 200                 # baseline: 21,600 games, ~10 s
cargo run --release -p fight_balance -- --games 100 --tune 4        # buff/nerf loop, 4 rounds
cargo run --release -p fight_balance -- --games 200 --seed 100 \
    --set samurai:damage=-6,weight=-6 --set ninja:damage=+6,weight=+6   # try a change on fresh seeds
cargo run --release -p fight_balance -- --characters chef,pug --stages sandbar --games 500
cargo run --release -p fight_balance -- --games 200 --report r.md --json r.json --csv r.csv
cargo run --release -p fight_balance -- --help
```

Always use `--release`: a debug build is roughly 10x slower.

| Option | Default | |
|---|---|---|
| `--games N` | 20 | games per ordered pair per stage (a matchup cell gets 2N per stage: both ports) |
| `--level L` | 9 | CPU level for both sides |
| `--stocks S` | 3 | |
| `--stages`, `--characters` | all | comma-separated names |
| `--seed N` | 1 | base seed. Every game's seed comes from it and the game's (stage, P1, P2, index), so a narrower run replays the same games |
| `--frame-cap N` | 28800 | 8 minutes; then the game is a timeout, decided on stocks, then percent |
| `--threads N` | cores | results don't depend on it |
| `--set NAME:KNOBS` | | start from changed tuning (`damage`, `knockback`, `weight`, `speed`) |
| `--tune ROUNDS` | off | the buff/nerf loop |
| `--max-changes N` | 2 | characters the loop changes per round |
| `--band LO,HI` | 45,55 | win rates left alone |
| `--report`, `--json`, `--csv FILE` | | write the printed report / every round's numbers |

## Reading the report

- **Matrix**: row's win rate against column, both ports and all stages pooled. The
  diagonal is P1's rate in the mirror. The header gives a cell's standard error
  (±1.4 points at `--games 200`). Draws count as half a win.
- **Port bias**: P1's rate over every mirror. It should sit within about two standard
  errors of 50%; if it doesn't, something favours a port (spawns, player order).
- **Overall**: each character's rate over its non-mirror games, ± its standard error,
  per stage, and the loop's verdict: `ok` (inside the band), `noisy` (outside the band
  but within 2 SE of 50%: play more games), `buff`/`nerf` (what the loop would change),
  `later` (out of line, but the loop only changes the `--max-changes` furthest out per
  round), `held: AI issue`, `at tuning limit`.
- **AI check**: `SD/KO%` (stocks lost with no hit in the last 5 s), `bottom%` (stocks lost
  off the bottom: failed recoveries and spikes), `recov%` (of those, the ones with no hit
  taken offstage: failed recoveries), `edge%` (stocks lost to a hit taken offstage or on
  the ledge: edge-guards), `reach` (how far past the ledge, in units, the CPU recovers
  from at stage height), `hit%` (hits per move started), damage per minute, timeouts,
  `moves` (moveset slots used for at least 0.5% of its moves, of 24), and flags.
- **Defense**: how each character's CPU defends. `spot`, `roll`, `airdg` (dodges started),
  `shield` (times it put its shield up) and `blocked` (hits on its shield) are per minute
  of play; `breaks` is shield breaks per game; `OoS%` is the share of its shields it acted
  straight out of (grab, jump, up special, up smash); `DI%` is the share of its airborne
  launches it DI'd (stick out of the deadzone on the first hitstun frame).
- **Move use %**: each character's moves by moveset slot (`Moveset::SLOT_NAMES`), so you
  can see which parts of a kit the numbers measure.
- **Suggestion**: the round that played closest to even (root mean square distance from
  50%), as knobs and as a diff of `sim/src/fighter.rs`.

A rough guide: differences under 2 standard errors are noise. Re-check any suggestion
on a fresh `--seed` before applying it.

## The buff/nerf loop

Each round it plays a full tournament on fresh seeds (`seed + round`), then changes the
`--max-changes` characters furthest outside the band, if they're more than 2 standard
errors from 50% and not held for an AI flag. A change moves `damage_scale` and `weight`
together by about one point per 4 points of win rate off 50%, at most 3 a round and 9
in total; a step against the previous one (an overshoot) is halved. Matchups are
zero-sum, so changing one character moves everyone's rates, and KO thresholds make the
response jumpy: that's why it's slow and bounded.

The knobs (`tuning.rs`) are deltas on a character's `FighterParams`: `damage` and
`knockback` add to `damage_scale` / `knockback_scale`, `weight` adds to `weight`, and
`speed` scales walk, run, air and jump-sideways speed by a percent. The harness installs
the changed params on its fighters after `World::new`. With no knobs it plays the
shipped game exactly.

## The caveat: this measures the CPU, too

CPU-vs-CPU results measure each character **as the CPU plays it**. The CPU
(`sim/src/cpu.rs`) walks or runs in to its own reach, picks moves from the move data (every hitbox, grab box, scripted motion and projectile is played forward against where it predicts the opponent will be, and scored on damage, speed, end lag and whether the knockback formula says the launch KOs or leaves the opponent offstage), anti-airs or waits under an airborne opponent rather than chasing its jumps, edge-guards from level 4 (ground moves and projectiles from the ledge; from level 7 it also jumps off after the recovering opponent, keeping a jump to come back with), picks throws the same way, mixes up ledge getups, and defends: once it sees an attack coming (10 frames in at level 9) or a projectile about to arrive, it plays a copy of the world forward with each answer it has (shield, spot dodge, rolls, air dodges, a counter) and takes one that isn't hit, preferring those that leave it free close enough to punish before the attacker can act; out of shield it grabs, up-smashes or up-specials an attacker in its end lag. It DIs every launch (toward survival near a blast zone, out of combo range otherwise), chases a launched opponent with the hop and aerial that a rollout says connects, and recovers with a style picked by playing it out: plain (drift, double jump, up special), high, low, an air dodge in, an air dodge for distance from farther out, or drifting to the ledge. It is generic: the same scoring runs on every character's move data, with no
per-character script. What it still doesn't do, so read the numbers with it in mind:

- It only reacts: it never guesses an attack before it starts, so moves faster than its
  reaction (10 frames at level 9) always land, and slow-starting kits (the hobo, the
  samurai and soldier's smashes) are answered more reliably than a person would. That
  favours quick kits (the pug, the ninja's jab) a little.
- No charged smash attacks, no dash grabs, only jab combos and rollout-checked
  hop-and-aerial chases (no hand-made combo routes), no teching or SDI. Its up and down
  throws rarely score best.
- Its kill estimates ignore the defender's DI, so it reaches for kill moves a little
  early against a CPU that DIs.
- Rolls and spot dodges are rare (`roll`, `spot` in the Defense table): with a 10-frame
  reaction only smash attacks and slow specials are worth dodging on the ground, and
  shield usually scores better. Most of its defense is air dodges and shields.
- The DI heavily favours heavy characters (they live much longer with survival DI) and
  hurts light, floaty ones that die off the top, where DI barely helps. That is
  character data, not an AI fault: the sim has DI for everyone.
- Flagged characters' rates say more about the AI than the character. Flags:
  `self-destructs` (over 10% of stocks lost unforced) and `timeouts` (well above the
  cast's rate) hold a character out of the loop; `whiffs` (hit rate far below the cast)
  and `recovery gaps` (it falls from distances *closer* than ones it makes it back from:
  a ledge-grab or recovery bug) are warnings. (The gaps the first runs found, 4-6-unit
  bands where a full-drift recovery dropped below the top just outside the corner and
  fell through the stage, were a sim bug: solid platforms now have solid sides.)
  `narrow moveset` (fewer than 12 of its 24 slots used) is a warning too.
- A cast-wide timeout rate is reported once, above the tables, instead of holding
  everyone back.

Fix the AI, or the bug, before tuning around it, and re-run the harness after any CPU
change.

## Code

| File | |
|---|---|
| `src/runner.rs` | `run_match(MatchConfig, Tuning) -> MatchResult`: one CPU-vs-CPU match to elimination or the frame cap, with each port's `Defense` (dodges, shields, DI) |
| `src/tournament.rs` | `TournamentConfig::schedule`, `run_tournament` (threads, results in a fixed order) |
| `src/summary.rs` | `Score` (rate, standard error), `PlayStats`, `Summary` (matrix, overall, by stage, port bias), `AiFlag`s |
| `src/probe.rs` | `recovery`: the CPU's recovery reach and gaps, probed unit by unit |
| `src/tuning.rs` | `Knobs`, `Tuning` (the harness's params overrides) |
| `src/tuner.rs` | `TunerConfig`, `Verdict`, `tune` (the loop) |
| `src/report.rs` | text/Markdown report, source diff, JSON, CSV, `AI_CAVEAT` |
| `src/main.rs` | the `balance` binary's argument parsing |
| `tests/balance.rs` | determinism, termination, mirrors near 50%, knobs, the loop (kept small; real runs use the binary) |
