//! One CPU-vs-CPU match, start to finish, on the headless sim.

use fight_sim::{Character, Cpu, DodgeKind, Event, Fighter, Fx, Moveset, Platform, StageId, State, World};

use crate::tuning::Tuning;

/// Melee's default time limit: 8 minutes at 60 fps.
pub const DEFAULT_FRAME_CAP: u32 = 8 * 60 * 60;

/// A KO this long (frames) after the fighter was last hit or grabbed counts as a
/// self-destruct: nothing the opponent did sent it there.
pub const SELF_DESTRUCT_WINDOW: u32 = 5 * 60;

/// A fighter this close above the bottom blast zone the frame before a KO went out the bottom.
const BOTTOM_MARGIN: Fx = Fx::int(10);

/// Moveset slots ([`Moveset::SLOT_NAMES`]).
pub const SLOTS: usize = Moveset::SLOT_NAMES.len();

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
    /// Stocks each port lost off the bottom blast zone: mostly failed recoveries
    /// (spikes count too).
    pub bottom_kos: [u8; 2],
    /// Stocks each port lost to a hit taken offstage or on the ledge: edge-guards.
    pub offstage_kos: [u8; 2],
    /// Stocks each port lost off the bottom without being hit offstage: failed recoveries.
    pub failed_recoveries: [u8; 2],
    /// Moves each port started, by moveset slot ([`Moveset::SLOT_NAMES`]). Follow-ups
    /// (jab 2, a counter's answer) belong to no slot and aren't counted.
    pub moves: [[u32; SLOTS]; 2],
    /// Moves each port started from a non-attacking state (swings, grabs, specials).
    pub attacks: [u32; 2],
    /// Hits each port landed (shielded ones excluded).
    pub hits: [u32; 2],
    /// How each port defended.
    pub defense: [Defense; 2],
}

/// One port's defensive play in a match: dodges, shielding and DI.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Defense {
    pub spot_dodges: u32,
    pub rolls: u32,
    pub air_dodges: u32,
    /// Times it put its shield up (not counting shield stun turning back into shield).
    pub shields: u32,
    /// Hits it blocked with its shield.
    pub blocked: u32,
    pub shield_breaks: u32,
    /// Actions straight out of shield: grabs, jumps, up specials, up smashes.
    pub out_of_shield: u32,
    /// Launches it could DI (an airborne launch's first hitstun frame) ...
    pub launches: u32,
    /// ... and how many of them it DI'd (stick out of the deadzone on that frame).
    pub di: u32,
}

impl Defense {
    pub fn add(&mut self, o: &Defense) {
        self.spot_dodges += o.spot_dodges;
        self.rolls += o.rolls;
        self.air_dodges += o.air_dodges;
        self.shields += o.shields;
        self.blocked += o.blocked;
        self.shield_breaks += o.shield_breaks;
        self.out_of_shield += o.out_of_shield;
        self.launches += o.launches;
        self.di += o.di;
    }
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
    let mut hit_offstage = [false; 2];
    let main = world.stage.platforms.iter().find(|p| !p.soft).cloned().expect("a stage without a solid platform");
    while world.frame < config.frame_cap {
        let was_attacking: Vec<bool> = world.fighters.iter().map(|f| matches!(f.state, State::Attack { .. })).collect();
        let was_move: Vec<_> = world.fighters.iter().map(|f| if let State::Attack { mv, .. } = f.state { Some(mv) } else { None }).collect();
        let was_low: Vec<bool> = world.fighters.iter().map(|f| f.y < world.stage.blast_bottom + BOTTOM_MARGIN).collect();
        let was_state: Vec<State> = world.fighters.iter().map(|f| f.state).collect();
        // The frame a launch is DI'd: it's pending and hitlag is over.
        let di_frame: Vec<bool> = world.fighters.iter().map(|f| f.di_pending.is_some() && f.hitlag == 0).collect();
        let inputs = [cpus[0].think(&world), cpus[1].think(&world)];
        world.step(&inputs);

        for (i, f) in world.fighters.iter().enumerate() {
            tally_defense(&mut result.defense[i], was_state[i], f.state);
            if di_frame[i] {
                let d = &mut result.defense[i];
                d.launches += 1;
                let (sx, sy) = inputs[i].stick();
                d.di += (Fx::hypot(sx, sy) >= DI_DEADZONE) as u32;
            }
        }
        for (i, f) in world.fighters.iter().enumerate() {
            if !was_attacking[i] && matches!(f.state, State::Attack { .. }) {
                result.attacks[i] += 1;
            }
            if let State::Attack { mv, .. } = f.state
                && was_move[i] != Some(mv)
                && let Some(slot) = f.character.moveset().slot_of(mv)
            {
                result.moves[i][slot] += 1;
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
                    hit_offstage[defender] = offstage(&world.fighters[defender], &main);
                }
                Event::ShieldHit { defender, .. } => result.defense[defender].blocked += 1,
                Event::ShieldBreak { fighter } => result.defense[fighter].shield_breaks += 1,
                Event::Ko { fighter } => {
                    if last_hit[fighter].is_none_or(|t| world.frame - t > SELF_DESTRUCT_WINDOW) {
                        result.self_destructs[fighter] += 1;
                    } else if hit_offstage[fighter] {
                        result.offstage_kos[fighter] += 1;
                    }
                    if was_low[fighter] {
                        result.bottom_kos[fighter] += 1;
                        if !hit_offstage[fighter] {
                            result.failed_recoveries[fighter] += 1;
                        }
                    }
                    last_hit[fighter] = None;
                    hit_offstage[fighter] = false;
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

/// A stick this far from center on the DI frame counts as DI (the sim's deadzone).
const DI_DEADZONE: Fx = Fx::ratio(2, 10);

/// Counts the defensive option a fighter just started, from its state change.
fn tally_defense(d: &mut Defense, was: State, now: State) {
    let shielding = |s: State| matches!(s, State::Shield | State::ShieldStun { .. });
    match now {
        State::Dodge { kind, frame: 1 } => match kind {
            DodgeKind::Spot => d.spot_dodges += 1,
            DodgeKind::RollForward | DodgeKind::RollBack => d.rolls += 1,
            DodgeKind::Air | DodgeKind::AirDirectional => d.air_dodges += 1,
        },
        State::Shield if !shielding(was) => d.shields += 1,
        State::Attack { .. } | State::JumpSquat { .. } if shielding(was) => d.out_of_shield += 1,
        _ => {}
    }
}

/// Offstage or hanging from the ledge (where a hit is an edge-guard).
fn offstage(f: &Fighter, main: &Platform) -> bool {
    f.state == State::LedgeHang || (!f.grounded() && (!main.contains_x(f.x) || f.y < main.y))
}
