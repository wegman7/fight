//! Balance testing on the headless sim: CPUs fight each other (no Godot), the results
//! become a win-rate matrix, and an optional loop proposes buffs and nerfs.
//!
//! - [`runner`]: one match from a [`MatchConfig`] to a [`MatchResult`].
//! - [`tournament`]: every ordered pair on every stage, N games each, on threads.
//! - [`summary`]: win rates with standard errors, play stats, AI-quality flags.
//! - [`probe`]: direct checks of the CPU's play (how far out it recovers from).
//! - [`tuning`]: knobs that override a character's `FighterParams` for the harness only.
//! - [`tuner`]: the buff/nerf loop.
//! - [`report`]: tables, the suggested source diff, JSON and CSV.
//!
//! This crate is a tool, not gameplay: it may use floats, threads and files. The
//! sim it drives stays deterministic, so a seed always reproduces the same results.

pub mod probe;
pub mod report;
pub mod runner;
pub mod summary;
pub mod tournament;
pub mod tuner;
pub mod tuning;

pub use runner::{MatchConfig, MatchResult, run_match};
pub use summary::{AiFlag, Score, Summary};
pub use tournament::{Game, TournamentConfig, run_tournament};
pub use tuner::{Round, TunerConfig, Verdict, tune};
pub use tuning::{Knobs, Tuning};
