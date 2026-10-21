//! The buff/nerf loop: run a tournament, nudge the characters furthest out of line,
//! run again on fresh seeds, a few rounds. It only ever proposes knobs; nothing here
//! touches the source.
//!
//! Matchups are zero-sum, so changing one character moves everyone else's rates too,
//! and KO thresholds make the response jumpy. The loop therefore changes at most
//! `max_changes` characters a round (the furthest from 50% first), in small steps,
//! and halves a character's step when it overshoots.

use fight_sim::Character;

use crate::summary::{AiFlag, Summary};
use crate::tournament::{TournamentConfig, run_tournament};
use crate::tuning::{Knobs, Tuning};

#[derive(Clone, Debug)]
pub struct TunerConfig {
    /// Overall win rates inside this band (0..1) are left alone.
    pub band: (f64, f64),
    /// Tuning rounds after the baseline.
    pub rounds: u32,
    /// Characters changed per round at most.
    pub max_changes: usize,
    /// Win-rate points (of 100) off 50% per knob point of change.
    pub points_per_step: f64,
    /// Largest change to a knob in one round (percentage / weight points).
    pub max_step: i32,
    /// Largest total change to a knob over all rounds.
    pub max_total: i32,
    /// Only adjust when the rate is this many standard errors from 50%, so noise
    /// alone doesn't move anyone.
    pub sigmas: f64,
}

impl Default for TunerConfig {
    fn default() -> Self {
        TunerConfig { band: (0.45, 0.55), rounds: 3, max_changes: 2, points_per_step: 4.0, max_step: 3, max_total: 9, sigmas: 2.0 }
    }
}

/// Why a character is (or isn't) being changed after a round.
#[derive(Clone, Debug, PartialEq)]
pub enum Verdict {
    InBand,
    /// Outside the band, but within `sigmas` standard errors of 50%: play more games.
    Noisy,
    /// Outside the band, but its CPU looks broken (see [`AiFlag::blocks_tuning`]).
    HeldForAi(Vec<AiFlag>),
    /// Already at `max_total` in that direction.
    AtLimit,
    /// Change its knobs by this much (positive = buff) for the next round.
    Adjust(i32),
    /// Would change by this much, but others are further out this round.
    Later(i32),
}

impl TunerConfig {
    /// What `summary` says about character `i`, now at `knobs`. `last_step` is its
    /// previous change (0 = none): a step against it is an overshoot and is halved.
    pub fn verdict(&self, summary: &Summary, i: usize, knobs: Knobs, last_step: i32) -> Verdict {
        let score = summary.overall[i];
        let rate = score.rate();
        if score.games == 0 || (self.band.0..=self.band.1).contains(&rate) {
            return Verdict::InBand;
        }
        if (rate - 0.5).abs() < self.sigmas * score.stderr() {
            return Verdict::Noisy;
        }
        let blocking: Vec<AiFlag> = summary.flags(i).into_iter().filter(AiFlag::blocks_tuning).collect();
        if !blocking.is_empty() {
            return Verdict::HeldForAi(blocking);
        }
        let direction = if rate < 0.5 { 1 } else { -1 };
        let mut wanted = (((0.5 - rate) * 100.0 / self.points_per_step).round() as i32).clamp(-self.max_step, self.max_step);
        if last_step * direction < 0 {
            wanted /= 2;
        }
        if wanted == 0 {
            wanted = direction;
        }
        let step = (knobs.damage + wanted).clamp(-self.max_total, self.max_total) - knobs.damage;
        if step == 0 { Verdict::AtLimit } else { Verdict::Adjust(step) }
    }

    /// Verdicts for every character, with only the `max_changes` furthest from 50%
    /// left as `Adjust` (the rest become `Later`).
    pub fn verdicts(&self, summary: &Summary, tuning: &Tuning, last_steps: &[i32]) -> Vec<Verdict> {
        let mut verdicts: Vec<Verdict> =
            summary.characters.iter().enumerate().map(|(i, &c)| self.verdict(summary, i, tuning.knobs(c), last_steps[i])).collect();
        let mut adjusting: Vec<usize> = (0..verdicts.len()).filter(|&i| matches!(verdicts[i], Verdict::Adjust(_))).collect();
        // Furthest first; ties by roster order, so the choice is deterministic.
        adjusting.sort_by(|&a, &b| {
            let off = |i: usize| (summary.overall[i].rate() - 0.5).abs();
            off(b).total_cmp(&off(a)).then(a.cmp(&b))
        });
        for &i in adjusting.iter().skip(self.max_changes) {
            if let Verdict::Adjust(step) = verdicts[i] {
                verdicts[i] = Verdict::Later(step);
            }
        }
        verdicts
    }
}

/// A buff or nerf: more (or less) damage dealt and weight together, so the character
/// both wins exchanges and survives a little better (or worse).
pub fn nudge(knobs: Knobs, step: i32) -> Knobs {
    Knobs { damage: knobs.damage + step, weight: knobs.weight + step, ..knobs }
}

/// One tournament in the loop: the tuning it played with and how it went.
#[derive(Clone, Debug)]
pub struct Round {
    pub tuning: Tuning,
    pub summary: Summary,
    /// Per character (in roster order): what this round's results call for.
    pub verdicts: Vec<Verdict>,
}

/// Runs the baseline (`start`'s tuning) and up to `tuner.rounds` adjusted rounds.
/// Each round uses fresh seeds (`seed + round`), so later rounds also check that
/// earlier gains weren't luck. Stops early once nobody needs a change.
/// `progress` is called after each round.
pub fn tune(config: &TournamentConfig, start: &Tuning, tuner: &TunerConfig, mut progress: impl FnMut(&Round)) -> Vec<Round> {
    let mut rounds: Vec<Round> = Vec::new();
    let mut tuning = start.clone();
    let mut last_steps = vec![0; config.characters.len()];
    for r in 0..=tuner.rounds {
        let config = TournamentConfig { seed: config.seed.wrapping_add(r as u64), ..config.clone() };
        let games = run_tournament(&config, &tuning);
        let summary = Summary::new(&config, &games, &tuning);
        let verdicts = tuner.verdicts(&summary, &tuning, &last_steps);
        let round = Round { tuning: tuning.clone(), summary, verdicts };
        progress(&round);
        let adjustments: Vec<(usize, Character, i32)> = round
            .summary
            .characters
            .iter()
            .zip(&round.verdicts)
            .enumerate()
            .filter_map(|(i, (&c, v))| if let Verdict::Adjust(step) = v { Some((i, c, *step)) } else { None })
            .collect();
        rounds.push(round);
        if adjustments.is_empty() || r == tuner.rounds {
            break;
        }
        for (i, c, step) in adjustments {
            tuning.set(c, nudge(tuning.knobs(c), step));
            last_steps[i] = step;
        }
    }
    rounds
}
