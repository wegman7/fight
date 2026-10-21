//! Every ordered pair of characters (both ports, mirrors included) on every chosen
//! stage, `games` times each, spread over threads. Results come back in a fixed
//! order, so a seed always gives the same tournament however the threads interleave.

use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};

use fight_sim::{Character, CpuLevel, StageId};

use crate::runner::{DEFAULT_FRAME_CAP, MatchConfig, MatchResult, mix, run_match};
use crate::tuning::Tuning;

#[derive(Clone, Debug)]
pub struct TournamentConfig {
    pub characters: Vec<Character>,
    pub stages: Vec<StageId>,
    /// Games per ordered pair per stage. A matchup cell (both port orders) gets twice this per stage.
    pub games: u32,
    /// Both CPUs play at this level (1-9).
    pub level: u8,
    pub stocks: u8,
    pub seed: u64,
    pub frame_cap: u32,
    /// Worker threads; 0 = one per core.
    pub threads: usize,
}

impl Default for TournamentConfig {
    fn default() -> Self {
        TournamentConfig {
            characters: Character::ALL.to_vec(),
            stages: StageId::ALL.to_vec(),
            games: 20,
            level: CpuLevel::MAX,
            stocks: 3,
            seed: 1,
            frame_cap: DEFAULT_FRAME_CAP,
            threads: 0,
        }
    }
}

/// One game played and its outcome.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Game {
    pub config: MatchConfig,
    /// Which repetition of its pairing and stage this was.
    pub index: u32,
    pub result: MatchResult,
}

impl TournamentConfig {
    /// Every game to play, in report order: stage, then P1, then P2, then repetition.
    /// Each game's seed depends only on the base seed and its (stage, P1, P2, index),
    /// so narrowing the roster or stages replays the same games for what's left.
    pub fn schedule(&self) -> Vec<(MatchConfig, u32)> {
        let mut out = Vec::new();
        for &stage in &self.stages {
            for &a in &self.characters {
                for &b in &self.characters {
                    for index in 0..self.games {
                        let key = [stage_index(stage), char_index(a), char_index(b), index as u64];
                        let seed = key.iter().fold(mix(self.seed), |h, &k| mix(h ^ k));
                        let config = MatchConfig {
                            characters: [a, b],
                            stage,
                            levels: [self.level; 2],
                            stocks: self.stocks,
                            seed,
                            frame_cap: self.frame_cap,
                        };
                        out.push((config, index));
                    }
                }
            }
        }
        out
    }
}

pub fn char_index(c: Character) -> u64 {
    Character::ALL.iter().position(|&x| x == c).expect("character missing from Character::ALL") as u64
}

fn stage_index(s: StageId) -> u64 {
    StageId::ALL.iter().position(|&x| x == s).expect("stage missing from StageId::ALL") as u64
}

/// Plays the whole schedule with `tuning`'s params.
pub fn run_tournament(config: &TournamentConfig, tuning: &Tuning) -> Vec<Game> {
    let schedule = config.schedule();
    let threads = if config.threads == 0 { std::thread::available_parallelism().map_or(1, |n| n.get()) } else { config.threads };
    let next = AtomicUsize::new(0);
    let results: Mutex<Vec<Option<MatchResult>>> = Mutex::new(vec![None; schedule.len()]);
    std::thread::scope(|scope| {
        for _ in 0..threads.min(schedule.len()).max(1) {
            scope.spawn(|| {
                loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    let Some((match_config, _)) = schedule.get(i) else { break };
                    let result = run_match(match_config, tuning);
                    results.lock().expect("a worker panicked")[i] = Some(result);
                }
            });
        }
    });
    let results = results.into_inner().expect("a worker panicked");
    schedule
        .into_iter()
        .zip(results)
        .map(|((config, index), result)| Game { config, index, result: result.expect("every game is played") })
        .collect()
}
