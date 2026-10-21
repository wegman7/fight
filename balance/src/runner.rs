//! One CPU-vs-CPU match, start to finish, on the headless sim.

use fight_sim::{Character, Cpu, Event, Fx, State, StageId, World};

use crate::tuning::Tuning;

/// Melee's default time limit: 8 minutes at 60 fps.
pub const DEFAULT_FRAME_CAP: u32 = 8 * 60 * 60;

/// A KO this long (frames) after the fighter was last hit or grabbed counts as a
/// self-destruct: nothing the opponent did sent it there.
pub const SELF_DESTRUCT_WINDOW: u32 = 5 * 60;

/// A fighter this close above the bottom blast zone the frame before a KO went out the bottom.
const BOTTOM_MARGIN: Fx = Fx::int(10);

/// What to play: like the game's `MatchSetup`, with both ports CPUs and a seed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MatchConfig {
    /// P1's and P2's characters.
    pub characters: [Character; 2],
    pub stage: StageId,
    /// CPU levels, 1-9.
    pub levels: [u8; 2],
    pub stocks: u8,
    /// Seeds both CPUs (each port gets its own stream).
    pub seed: u64,
    /// The match ends as a timeout after this many frames.
    pub frame_cap: u32,
}

/// How a match went. Arrays are indexed by port.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct MatchResult {
    /// The port that won, or `None` for a draw (a timeout with equal stocks and percent).
    pub winner: Option<usize>,
    /// Hit the frame cap; the winner is then decided on stocks, then percent.
    pub timed_out: bool,
    pub frames: u32,
    pub stocks: [u8; 2],
    pub percent: [i32; 2],
    /// Damage each port dealt (hits, throws, pummels, projectiles), not counting shields.
    pub damage_dealt: [i32; 2],
    /// Stocks each port lost to self-destructs (no hit within [`SELF_DESTRUCT_WINDOW`]).
    pub self_destructs: [u8; 2],
    /// Stocks each port lost off the bottom blast zone: failed recoveries, since the
    /// CPU never spikes or edge-guards.
    pub bottom_kos: [u8; 2],
    /// Moves each port started from a non-attacking state (swings, grabs, specials).
    pub attacks: [u32; 2],
    /// Hits each port landed (shielded ones excluded).
    pub hits: [u32; 2],
}

impl MatchResult {
    /// Stocks each port lost.
    pub fn stocks_lost(&self, stocks: u8) -> [u8; 2] {
        [stocks - self.stocks[0], stocks - self.stocks[1]]
    }
}

/// splitmix64: spreads nearby seeds into unrelated ones.
pub fn mix(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
}

/// Plays `config` with `tuning`'s params, both ports driven by `Cpu::think`, until one
/// side is out of stocks or the frame cap. Deterministic: the same inputs give the
/// same result.
pub fn run_match(config: &MatchConfig, tuning: &Tuning) -> MatchResult {
    let mut world = World::new(config.stage.stage(), &config.characters, config.stocks);
    for f in &mut world.fighters {
        f.params = tuning.params(f.character);
        f.air_jumps_left = f.params.air_jumps;
    }
    let mut cpus: Vec<Cpu> =
        (0..2).map(|i| Cpu::with_level(i, config.levels[i]).with_seed(mix(config.seed ^ i as u64) as u32)).collect();

    let mut result = MatchResult::default();
    let mut last_hit: [Option<u32>; 2] = [None, None];
    while world.frame < config.frame_cap {
        let was_attacking: Vec<bool> = world.fighters.iter().map(|f| matches!(f.state, State::Attack { .. })).collect();
        let was_low: Vec<bool> = world.fighters.iter().map(|f| f.y < world.stage.blast_bottom + BOTTOM_MARGIN).collect();
        let inputs = [cpus[0].think(&world), cpus[1].think(&world)];
        world.step(&inputs);

        for (i, f) in world.fighters.iter().enumerate() {
            if !was_attacking[i] && matches!(f.state, State::Attack { .. }) {
                result.attacks[i] += 1;
            }
            if matches!(f.state, State::Held { .. }) {
                last_hit[i] = Some(world.frame);
            }
        }
        for e in &world.events {
            match *e {
                Event::Hit { attacker, defender, damage, .. } => {
                    result.hits[attacker] += 1;
                    result.damage_dealt[attacker] += damage;
                    last_hit[defender] = Some(world.frame);
                }
                Event::Ko { fighter } => {
                    if last_hit[fighter].is_none_or(|t| world.frame - t > SELF_DESTRUCT_WINDOW) {
                        result.self_destructs[fighter] += 1;
                    }
                    if was_low[fighter] {
                        result.bottom_kos[fighter] += 1;
                    }
                    last_hit[fighter] = None;
                }
                _ => {}
            }
        }
        if world.fighters.iter().any(|f| f.state == State::Eliminated) {
            break;
        }
    }

    let f = &world.fighters;
    result.frames = world.frame;
    result.stocks = [f[0].stocks, f[1].stocks];
    result.percent = [f[0].percent, f[1].percent];
    result.timed_out = f.iter().all(|f| f.state != State::Eliminated);
    result.winner = match (f[0].stocks.cmp(&f[1].stocks), f[0].percent.cmp(&f[1].percent)) {
        (std::cmp::Ordering::Greater, _) => Some(0),
        (std::cmp::Ordering::Less, _) => Some(1),
        (_, std::cmp::Ordering::Less) => Some(0),
        (_, std::cmp::Ordering::Greater) => Some(1),
        _ => None,
    };
    result
}
