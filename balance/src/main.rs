//! `cargo run --release -p fight_balance -- --help`

use std::process::ExitCode;
use std::time::Instant;

use fight_balance::report::{render, to_csv, to_json};
use fight_balance::{Knobs, TournamentConfig, TunerConfig, Tuning, tune};
use fight_sim::{Character, StageId};

const HELP: &str = "\
CPU-vs-CPU balance testing on the headless sim.

USAGE: cargo run --release -p fight_balance -- [OPTIONS]

  --games N          games per ordered pair per stage (default 20)
  --level L          CPU level for both sides, 1-9 (default 9)
  --stocks S         stocks per match (default 3)
  --stages LIST      comma-separated stage names, or `all` (default all)
  --characters LIST  comma-separated character names, or `all` (default all)
  --seed N           base seed (default 1); same seed, same results
  --frame-cap N      frames before a match times out (default 28800, 8 minutes)
  --threads N        worker threads (default: one per core)
  --set NAME:KNOBS   start from changed tuning, e.g. --set soldier:damage=-4,weight=-4
                     (knobs: damage, knockback, weight, speed; repeatable)
  --tune ROUNDS      buff/nerf loop: adjust out-of-band characters for up to ROUNDS rounds
  --max-changes N    characters the loop changes per round, furthest from 50% first (default 2)
  --band LO,HI       win-rate band left alone, in percent (default 45,55)
  --report FILE      also write the printed report (Markdown) to FILE
  --json FILE        write every round's numbers as JSON
  --csv FILE         write every round's matchup cells as CSV

Nothing here edits the source. Apply a suggestion by hand in sim/src/fighter.rs.";

fn find<T: Copy>(all: &[T], name: impl Fn(T) -> &'static str, list: &str, what: &str) -> Result<Vec<T>, String> {
    if list == "all" {
        return Ok(all.to_vec());
    }
    list.split(',')
        .map(|n| all.iter().copied().find(|&x| name(x).eq_ignore_ascii_case(n.trim())).ok_or_else(|| format!("unknown {what} `{n}`")))
        .collect()
}

fn character(name: &str) -> Result<Character, String> {
    find(&Character::ALL, Character::name, name, "character").map(|v| v[0])
}

struct Args {
    config: TournamentConfig,
    tuner: TunerConfig,
    start: Tuning,
    report: Option<String>,
    json: Option<String>,
    csv: Option<String>,
}

fn parse() -> Result<Option<Args>, String> {
    let mut a = Args { config: TournamentConfig::default(), tuner: TunerConfig { rounds: 0, ..TunerConfig::default() }, start: Tuning::default(), report: None, json: None, csv: None };
    let mut it = std::env::args().skip(1);
    while let Some(flag) = it.next() {
        if flag == "--help" || flag == "-h" {
            return Ok(None);
        }
        let mut value = || it.next().ok_or_else(|| format!("{flag} needs a value"));
        let num = |v: String| v.parse::<u64>().map_err(|_| format!("{flag}: `{v}` isn't a number"));
        match flag.as_str() {
            "--games" => a.config.games = num(value()?)? as u32,
            "--level" => a.config.level = (num(value()?)? as u8).clamp(1, 9),
            "--stocks" => a.config.stocks = (num(value()?)? as u8).max(1),
            "--seed" => a.config.seed = num(value()?)?,
            "--frame-cap" => a.config.frame_cap = num(value()?)? as u32,
            "--threads" => a.config.threads = num(value()?)? as usize,
            "--tune" => a.tuner.rounds = num(value()?)? as u32,
            "--max-changes" => a.tuner.max_changes = (num(value()?)? as usize).max(1),
            "--stages" => a.config.stages = find(&StageId::ALL, StageId::name, &value()?, "stage")?,
            "--characters" => a.config.characters = find(&Character::ALL, Character::name, &value()?, "character")?,
            "--set" => {
                let v = value()?;
                let (name, knobs) = v.split_once(':').ok_or("--set wants NAME:KNOBS")?;
                let c = character(name)?;
                a.start.set(c, Knobs::parse(knobs)?);
            }
            "--band" => {
                let v = value()?;
                let (lo, hi) = v.split_once(',').ok_or("--band wants LO,HI")?;
                let p = |x: &str| x.trim().parse::<f64>().map(|x| x / 100.0).map_err(|_| format!("--band: bad number `{x}`"));
                a.tuner.band = (p(lo)?, p(hi)?);
            }
            "--report" => a.report = Some(value()?),
            "--json" => a.json = Some(value()?),
            "--csv" => a.csv = Some(value()?),
            _ => return Err(format!("unknown option `{flag}` (see --help)")),
        }
    }
    if a.config.characters.len() < 2 {
        return Err("need at least two characters".into());
    }
    Ok(Some(a))
}

fn main() -> ExitCode {
    let args = match parse() {
        Ok(Some(a)) => a,
        Ok(None) => {
            println!("{HELP}");
            return ExitCode::SUCCESS;
        }
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::FAILURE;
        }
    };
    let started = Instant::now();
    let rounds = tune(&args.config, &args.start, &args.tuner, |round| {
        let changed: Vec<String> = round.tuning.changed().iter().map(|(c, k)| format!("{} {k}", c.name())).collect();
        eprintln!(
            "played {} games (seed {}) in {:.1}s{}",
            round.summary.total_games,
            round.summary.seed,
            started.elapsed().as_secs_f64(),
            if changed.is_empty() { String::new() } else { format!("; tuning: {}", changed.join(", ")) }
        );
    });
    let text = render(&rounds);
    print!("{text}");
    let writes = [(&args.report, text), (&args.json, to_json(&rounds)), (&args.csv, to_csv(&rounds))];
    for (path, contents) in writes {
        if let Some(path) = path {
            if let Err(e) = std::fs::write(path, contents) {
                eprintln!("error: writing {path}: {e}");
                return ExitCode::FAILURE;
            }
            eprintln!("wrote {path}");
        }
    }
    ExitCode::SUCCESS
}
