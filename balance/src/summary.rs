//! Turns a tournament's games into win rates (with standard errors) and per-character
//! play statistics, and flags characters whose CPU looks like it's playing badly.

use fight_sim::{Character, StageId};

use crate::probe::{Recovery, recovery};
use crate::runner::SLOTS;
use crate::tournament::{Game, TournamentConfig};
use crate::tuning::Tuning;

/// Wins, draws and games from one side's point of view. A draw counts half a win.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Score {
    pub games: u32,
    pub wins: u32,
    pub draws: u32,
}

impl Score {
    fn add(&mut self, won: Option<bool>) {
        self.games += 1;
        match won {
            Some(true) => self.wins += 1,
            Some(false) => {}
            None => self.draws += 1,
        }
    }

    pub fn losses(&self) -> u32 {
        self.games - self.wins - self.draws
    }

    /// Win rate in 0..=1 (NaN with no games).
    pub fn rate(&self) -> f64 {
        (self.wins as f64 + self.draws as f64 / 2.0) / self.games as f64
    }

    /// Binomial standard error of `rate`: about 68% of reruns land within one of it,
    /// 95% within two. At 0% or 100% it uses a half-game, so it never claims zero noise.
    pub fn stderr(&self) -> f64 {
        let n = self.games as f64;
        let p = self.rate().clamp(0.5 / n, 1.0 - 0.5 / n);
        (p * (1.0 - p) / n).sqrt()
    }
}

/// How one character's CPU played, over all its games (mirrors count both sides).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PlayStats {
    pub games: u32,
    pub frames: u64,
    pub stocks_lost: u32,
    pub self_destructs: u32,
    pub bottom_kos: u32,
    pub offstage_kos: u32,
    pub failed_recoveries: u32,
    pub damage_dealt: i64,
    pub attacks: u64,
    pub hits: u64,
    pub timeouts: u32,
    /// Moves started, by moveset slot (`Moveset::SLOT_NAMES`).
    pub moves: [u64; SLOTS],
}

/// A slot counts as part of a character's game once it's this share of its moves.
pub const MOVE_USE_THRESHOLD: f64 = 0.005;

impl PlayStats {
    /// Share of its stocks lost without being hit in the last few seconds.
    pub fn self_destruct_rate(&self) -> f64 {
        self.self_destructs as f64 / self.stocks_lost.max(1) as f64
    }

    /// Share of its stocks lost off the bottom: failed recoveries.
    pub fn bottom_ko_rate(&self) -> f64 {
        self.bottom_kos as f64 / self.stocks_lost.max(1) as f64
    }

    /// Share of its stocks lost off the bottom without a hit offstage: failed recoveries.
    pub fn failed_recovery_rate(&self) -> f64 {
        self.failed_recoveries as f64 / self.stocks_lost.max(1) as f64
    }

    /// Share of its stocks lost to a hit taken offstage or on the ledge (edge-guards).
    pub fn offstage_ko_rate(&self) -> f64 {
        self.offstage_kos as f64 / self.stocks_lost.max(1) as f64
    }

    /// Share of its moves started from `slot`.
    pub fn move_share(&self, slot: usize) -> f64 {
        self.moves[slot] as f64 / self.moves.iter().sum::<u64>().max(1) as f64
    }

    /// Moveset slots it uses (at least `MOVE_USE_THRESHOLD` of its moves each).
    pub fn moves_used(&self) -> usize {
        (0..SLOTS).filter(|&i| self.move_share(i) >= MOVE_USE_THRESHOLD).count()
    }

    /// Hits landed per move started.
    pub fn accuracy(&self) -> f64 {
        self.hits as f64 / self.attacks.max(1) as f64
    }

    pub fn damage_per_minute(&self) -> f64 {
        self.damage_dealt as f64 * 3600.0 / self.frames.max(1) as f64
    }

    pub fn timeout_rate(&self) -> f64 {
        self.timeouts as f64 / self.games.max(1) as f64
    }
}

/// Signs that a character's results say more about the CPU's play than about the
/// character. Tuning shouldn't chase these: fix the AI (`sim/src/cpu.rs`) first.
#[derive(Clone, Debug, PartialEq)]
pub enum AiFlag {
    /// Loses too many stocks with nobody near it (failed recoveries, walking off).
    SelfDestructs { rate: f64 },
    /// Too many of its games hit the frame cap (stalling, or two CPUs that can't reach each other).
    Timeouts { rate: f64 },
    /// Lands far fewer of its swings than the rest of the cast: the CPU's fixed
    /// spacing doesn't suit this character's reach.
    Whiffs { accuracy: f64, cast_median: f64 },
    /// Fails to recover from some distances closer than ones it makes it back from
    /// (`Recovery::gaps`, as ranges of units past the ledge).
    RecoveryGaps { ranges: String },
    /// Uses few of its moveset's slots: its rate measures part of the character.
    NarrowMoveset { used: usize },
}

impl AiFlag {
    /// Whether the tuner should leave the character alone until the AI is fixed.
    pub fn blocks_tuning(&self) -> bool {
        matches!(self, AiFlag::SelfDestructs { .. } | AiFlag::Timeouts { .. })
    }
}

impl std::fmt::Display for AiFlag {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AiFlag::SelfDestructs { rate } => write!(f, "self-destructs: {:.0}% of its stocks lost were unforced", rate * 100.0),
            AiFlag::Timeouts { rate } => write!(f, "timeouts: {:.0}% of its games hit the frame cap", rate * 100.0),
            AiFlag::Whiffs { accuracy, cast_median } => {
                write!(f, "whiffs: lands {:.0}% of its swings vs a cast median of {:.0}%", accuracy * 100.0, cast_median * 100.0)
            }
            AiFlag::RecoveryGaps { ranges } => write!(f, "recovery gaps: falls from {ranges} units past the ledge, inside its reach"),
            AiFlag::NarrowMoveset { used } => write!(f, "narrow moveset: uses {used} of its {SLOTS} move slots"),
        }
    }
}

/// Thresholds for [`AiFlag`]s.
pub const SELF_DESTRUCT_FLAG: f64 = 0.10;
/// Flag timeouts above this rate *and* above `TIMEOUT_FLAG_VS_CAST` times the cast's
/// median: a stall every character shares is reported once for the whole run
/// ([`Summary::timeout_rate`]) instead of holding everyone's tuning back.
pub const TIMEOUT_FLAG: f64 = 0.05;
pub const TIMEOUT_FLAG_VS_CAST: f64 = 2.0;
/// Flag accuracy below this share of the cast's median.
pub const WHIFF_FLAG: f64 = 0.6;
/// Flag a character that uses fewer of its moveset's slots than this.
pub const NARROW_MOVESET_FLAG: usize = 12;

#[derive(Clone, Debug)]
pub struct Summary {
    pub characters: Vec<Character>,
    pub stages: Vec<StageId>,
    pub level: u8,
    pub stocks: u8,
    pub seed: u64,
    /// Games per ordered pair per stage.
    pub games_per_pair: u32,
    pub total_games: usize,
    /// `matrix[r][c]`: character `r`'s score against `c`, both ports, all stages.
    /// On the diagonal it is P1's score in the mirror (a port-bias check).
    pub matrix: Vec<Vec<Score>>,
    /// Each character's score over all its non-mirror games.
    pub overall: Vec<Score>,
    /// `by_stage[r][s]`: `overall`, per stage.
    pub by_stage: Vec<Vec<Score>>,
    /// P1's score over every mirror match: should sit near 50%.
    pub port_bias: Score,
    pub play: Vec<PlayStats>,
    /// Games that hit the frame cap.
    pub timeouts: u32,
    /// Per character: its CPU's [`Recovery`] on the first stage, with the round's tuning.
    pub recovery: Vec<Recovery>,
}

impl Summary {
    /// Tallies `games` (played from `config` with `tuning`) and probes each
    /// character's recovery.
    pub fn new(config: &TournamentConfig, games: &[Game], tuning: &Tuning) -> Summary {
        let (nc, ns) = (config.characters.len(), config.stages.len());
        let ci = |c: Character| config.characters.iter().position(|&x| x == c).expect("game with a character outside the roster");
        let si = |s: StageId| config.stages.iter().position(|&x| x == s).expect("game on a stage outside the list");
        let mut s = Summary {
            characters: config.characters.clone(),
            stages: config.stages.clone(),
            level: config.level,
            stocks: config.stocks,
            seed: config.seed,
            games_per_pair: config.games,
            total_games: games.len(),
            matrix: vec![vec![Score::default(); nc]; nc],
            overall: vec![Score::default(); nc],
            by_stage: vec![vec![Score::default(); ns]; nc],
            port_bias: Score::default(),
            play: vec![PlayStats::default(); nc],
            timeouts: 0,
            recovery: config.characters.iter().map(|&c| recovery(c, config.stages[0], tuning)).collect(),
        };
        for g in games {
            let r = &g.result;
            let [a, b] = g.config.characters.map(ci);
            let won = |port: usize| r.winner.map(|w| w == port);
            if a == b {
                s.matrix[a][a].add(won(0));
                s.port_bias.add(won(0));
            } else {
                let st = si(g.config.stage);
                for (me, them, port) in [(a, b, 0), (b, a, 1)] {
                    s.matrix[me][them].add(won(port));
                    s.overall[me].add(won(port));
                    s.by_stage[me][st].add(won(port));
                }
            }
            s.timeouts += r.timed_out as u32;
            let lost = r.stocks_lost(g.config.stocks);
            for (port, me) in [(0, a), (1, b)] {
                let p = &mut s.play[me];
                p.games += 1;
                p.frames += r.frames as u64;
                p.stocks_lost += lost[port] as u32;
                p.self_destructs += r.self_destructs[port] as u32;
                p.bottom_kos += r.bottom_kos[port] as u32;
                p.offstage_kos += r.offstage_kos[port] as u32;
                p.failed_recoveries += r.failed_recoveries[port] as u32;
                for (total, &n) in p.moves.iter_mut().zip(&r.moves[port]) {
                    *total += n as u64;
                }
                p.damage_dealt += r.damage_dealt[port] as i64;
                p.attacks += r.attacks[port] as u64;
                p.hits += r.hits[port] as u64;
                p.timeouts += r.timed_out as u32;
            }
        }
        s
    }

    pub fn index(&self, c: Character) -> Option<usize> {
        self.characters.iter().position(|&x| x == c)
    }

    /// The AI-quality flags for character `i`.
    pub fn flags(&self, i: usize) -> Vec<AiFlag> {
        let p = &self.play[i];
        let mut flags = Vec::new();
        if p.self_destruct_rate() > SELF_DESTRUCT_FLAG {
            flags.push(AiFlag::SelfDestructs { rate: p.self_destruct_rate() });
        }
        let timeout_median = median(self.play.iter().map(PlayStats::timeout_rate).collect());
        if p.timeout_rate() > TIMEOUT_FLAG && p.timeout_rate() > timeout_median * TIMEOUT_FLAG_VS_CAST {
            flags.push(AiFlag::Timeouts { rate: p.timeout_rate() });
        }
        let accuracy_median = median(self.play.iter().map(PlayStats::accuracy).collect());
        if p.accuracy() < accuracy_median * WHIFF_FLAG {
            flags.push(AiFlag::Whiffs { accuracy: p.accuracy(), cast_median: accuracy_median });
        }
        if !self.recovery[i].gaps.is_empty() {
            flags.push(AiFlag::RecoveryGaps { ranges: self.recovery[i].gap_ranges() });
        }
        if p.moves.iter().any(|&n| n > 0) && p.moves_used() < NARROW_MOVESET_FLAG {
            flags.push(AiFlag::NarrowMoveset { used: p.moves_used() });
        }
        flags
    }

    /// Share of all games that hit the frame cap.
    pub fn timeout_rate(&self) -> f64 {
        self.timeouts as f64 / self.total_games.max(1) as f64
    }
}

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(f64::total_cmp);
    values.get(values.len() / 2).copied().unwrap_or(f64::NAN)
}
