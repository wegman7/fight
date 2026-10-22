//! Computer-controlled players. A [`Cpu`] looks at the [`World`] and returns the
//! same [`Input`] a controller would, so it can't bend any rules. It uses only
//! integer math and its own seeded RNG, so a match against it is deterministic
//! and replays/rollback only need to record the inputs it produced.
//!
//! It picks moves from the move data rather than a per-character script: for each
//! move its fighter could start, it plays the move's hitboxes, grab box, scripted
//! motion and projectile forward against where it predicts the opponent will be,
//! keeps the ones that connect, and scores them on damage, speed, end lag and whether
//! the launch (simulated from the knockback formula) would KO or send the opponent
//! offstage. So smash attacks come out as kill moves at high percent, projectiles at
//! range, back and down aerials when the opponent is behind or below, and every
//! character spaces by its own reach.
//!
//! Defense works on a copy of the world: once it sees an attack coming (a level's
//! `react` frames after it starts) or a projectile about to arrive, it plays the world
//! forward with each answer it has (shield, spot dodge, rolls, air dodges, a counter)
//! and keeps the ones that don't get hit, preferring those that leave it free to punish
//! before the attacker can act. The same rollouts pick a recovery that makes it back
//! (and mix it up), and check which hop and aerial reach a juggled opponent. Launches
//! are DI'd from the knockback formula: toward survival near a blast zone, out of
//! combo range otherwise.

use crate::character::Moveset;
use crate::fighter::{Fighter, FighterParams, GROUNDED_KB_THRESHOLD, HITSTUN_PER_KB, KB_DECAY, LAUNCH_SPEED, State, Trajectory, di_angle, knockback};
use crate::fixed::{Fx, cos_deg, sin_deg};
use crate::input::Input;
use crate::moves::{Landing, MoveData, MoveId, ProjectileData};
use crate::stage::{Platform, Stage};
use crate::world::{Event, MAX_FIGHTERS, Projectile, World};

/// How a CPU plays. Lower `reaction_frames` and `react` and higher chances make it harder.
#[derive(Debug, PartialEq, Eq, Hash)]
pub struct CpuLevel {
    /// The CPU commits to a plan for this many frames before looking again.
    pub reaction_frames: u8,
    /// How many frames into an opponent's attack it can react to it (shield, dodge,
    /// counter), and how soon it re-plans to punish an opening. An attack that hits
    /// sooner than this lands.
    pub react: u8,
    /// Percent chance, when out of range, to walk in rather than stand around.
    pub approach_chance: u32,
    /// Percent chance, when a move would connect, to throw it rather than wait or back off.
    pub attack_chance: u32,
    /// Percent of neutral openings it takes with a grab instead of a strike.
    pub grab_chance: u32,
    /// Percent chance to defend against a hit it sees coming (rolled once per attack or
    /// projectile): shield, or a dodge or counter when `dodge` allows.
    pub defend: u32,
    /// Percent chance, defending on the ground, to consider spot dodges and rolls as well
    /// as its shield. (In the air the air dodge is its only defense, so `defend` alone
    /// decides it.)
    pub dodge: u32,
    /// Percent chance to pick the best-scoring move (kill power, speed, end lag) rather
    /// than any move that connects; also how often it times aerials to connect instead
    /// of swinging on a fixed frame, picks the best throw, runs, counters, mixes up its
    /// ledge getups, picks the best guard, punishes out of shield, chases a launched
    /// opponent, and switches to a recovery that makes it when its plain one wouldn't.
    pub judgement: u32,
    /// Percent chance, with the opponent offstage or on the ledge, to go and cover the
    /// ledge (ground moves and projectiles at the recovering opponent) rather than wait.
    pub edge_guard: u32,
    /// Percent chance, edge-guarding, to jump off after the opponent with an aerial
    /// (only while it keeps a jump to come back with).
    pub offstage: u32,
    /// Percent chance to DI a launch (toward survival near a blast zone, away from the
    /// attacker otherwise); the rest it holds nothing.
    pub di: u32,
    /// Percent chance to mix up a recovery that would make it anyway: high, low, an air
    /// dodge in, or drifting to the ledge instead of the stage.
    pub recovery_mix: u32,
}

#[allow(clippy::too_many_arguments)]
const fn level(
    reaction_frames: u8,
    react: u8,
    approach_chance: u32,
    attack_chance: u32,
    grab_chance: u32,
    defend: u32,
    dodge: u32,
    judgement: u32,
    edge_guard: u32,
    offstage: u32,
    di: u32,
    recovery_mix: u32,
) -> CpuLevel {
    CpuLevel {
        reaction_frames,
        react,
        approach_chance,
        attack_chance,
        grab_chance,
        defend,
        dodge,
        judgement,
        edge_guard,
        offstage,
        di,
        recovery_mix,
    }
}

/// Melee-style levels 1 to 9, from barely fighting back to reacting within a few
/// frames. Levels 1-3 never edge-guard and mostly swing at whatever connects; from
/// level 4 they cover the ledge, and from level 7 they jump off after a recovering
/// opponent. Level 1 almost never defends or DIs; level 9 sees an attack 10 frames in
/// (a strong human's reaction, not a machine's: slow startups stay worth something),
/// defends most of what it sees and DIs nearly every launch. Every level walks or runs
/// rather than dashing, and recovers.
static LEVELS: [CpuLevel; 9] = [
    //    reac react appr att grab def dodge judg edge off  di mix
    level(40, 32, 40, 15, 10, 2, 10, 0, 0, 0, 0, 0),
    level(32, 28, 55, 25, 15, 8, 15, 10, 0, 0, 10, 0),
    CpuLevel::EASY,
    level(20, 22, 75, 45, 20, 30, 30, 40, 25, 0, 35, 20),
    level(16, 20, 80, 55, 25, 40, 40, 50, 40, 0, 50, 30),
    level(14, 18, 85, 62, 25, 50, 50, 60, 55, 0, 60, 40),
    level(12, 15, 90, 70, 30, 60, 60, 70, 70, 20, 70, 50),
    level(10, 12, 95, 78, 30, 72, 70, 85, 85, 35, 85, 60),
    level(8, 10, 100, 85, 30, 85, 80, 100, 95, 50, 95, 70),
];

impl CpuLevel {
    /// Level 3. Slow to react, swings at a fraction of its openings, never edge-guards.
    /// Still recovers, so it doesn't throw stocks away on its own.
    pub const EASY: CpuLevel = level(24, 25, 70, 35, 20, 18, 20, 25, 0, 0, 20, 10);
    pub const MIN: u8 = 1;
    pub const MAX: u8 = 9;

    /// Level `n`, clamped to `MIN..=MAX`.
    pub fn level(n: u8) -> &'static CpuLevel {
        &LEVELS[usize::from(n.clamp(Self::MIN, Self::MAX) - 1)]
    }
}

/// An input slot: which button and direction start a move, whatever the character.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Slot {
    Jab,
    FTilt,
    UTilt,
    DTilt,
    DashAttack,
    FSmash,
    USmash,
    DSmash,
    Nair,
    Fair,
    Bair,
    Uair,
    Dair,
    NeutralSpecial,
    SideSpecial,
    DownSpecial,
    /// Only out of shield; otherwise it's kept for recovering.
    UpSpecial,
    Grab,
}

/// What it can do straight out of shield (besides jumping).
const OUT_OF_SHIELD_SLOTS: [Slot; 3] = [Slot::Grab, Slot::USmash, Slot::UpSpecial];

/// What the CPU considers from the ground. Up special is kept for recovering.
const GROUND_SLOTS: [Slot; 12] = [
    Slot::Jab,
    Slot::FTilt,
    Slot::UTilt,
    Slot::DTilt,
    Slot::DashAttack,
    Slot::FSmash,
    Slot::USmash,
    Slot::DSmash,
    Slot::NeutralSpecial,
    Slot::SideSpecial,
    Slot::DownSpecial,
    Slot::Grab,
];
const AIR_SLOTS: [Slot; 5] = [Slot::Nair, Slot::Fair, Slot::Bair, Slot::Uair, Slot::Dair];

impl Slot {
    fn move_id(self, m: &Moveset) -> MoveId {
        match self {
            Slot::Jab => m.jab,
            Slot::FTilt => m.ftilt,
            Slot::UTilt => m.utilt,
            Slot::DTilt => m.dtilt,
            Slot::DashAttack => m.dash_attack,
            Slot::FSmash => m.fsmash,
            Slot::USmash => m.usmash,
            Slot::DSmash => m.dsmash,
            Slot::Nair => m.nair,
            Slot::Fair => m.fair,
            Slot::Bair => m.bair,
            Slot::Uair => m.uair,
            Slot::Dair => m.dair,
            Slot::NeutralSpecial => m.neutral_special,
            Slot::SideSpecial => m.side_special,
            Slot::DownSpecial => m.down_special,
            Slot::UpSpecial => m.up_special,
            Slot::Grab => m.grab,
        }
    }

    /// Whether its input turns the fighter toward the stick (so it never needs a turn first).
    fn turns(self) -> bool {
        matches!(self, Slot::FTilt | Slot::FSmash | Slot::SideSpecial | Slot::DashAttack)
    }

    /// The input that starts it, aimed toward `dir` (forward moves) for a fighter facing `facing`.
    fn input(self, dir: i8, facing: i32) -> Input {
        let f = facing as i8;
        let (stick_x, stick_y, buttons) = match self {
            Slot::Jab | Slot::Nair => (0, 0, Input::ATTACK),
            Slot::FTilt => (dir * TILT, 0, Input::ATTACK),
            Slot::UTilt | Slot::Uair => (0, TILT, Input::ATTACK),
            Slot::DTilt | Slot::Dair => (0, -TILT, Input::ATTACK),
            Slot::DashAttack => (dir * 100, 0, Input::ATTACK),
            Slot::FSmash => (dir * TILT, 0, Input::SMASH),
            Slot::USmash => (0, TILT, Input::SMASH),
            Slot::DSmash => (0, -TILT, Input::SMASH),
            Slot::Fair => (f * TILT, 0, Input::ATTACK),
            Slot::Bair => (-f * TILT, 0, Input::ATTACK),
            Slot::NeutralSpecial => (0, 0, Input::SPECIAL),
            Slot::SideSpecial => (dir * TILT, 0, Input::SPECIAL),
            Slot::DownSpecial => (0, -TILT, Input::SPECIAL),
            Slot::UpSpecial => (0, 100, Input::SPECIAL),
            Slot::Grab => (0, 0, Input::GRAB),
        };
        Input { stick_x, stick_y, buttons }
    }
}

/// The four throws, by stick direction relative to the holder's facing.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Throw {
    Forward,
    Back,
    Up,
    Down,
}

impl Throw {
    const ALL: [Throw; 4] = [Throw::Forward, Throw::Back, Throw::Up, Throw::Down];

    fn move_id(self, m: &Moveset) -> MoveId {
        match self {
            Throw::Forward => m.fthrow,
            Throw::Back => m.bthrow,
            Throw::Up => m.uthrow,
            Throw::Down => m.dthrow,
        }
    }

    fn input(self, facing: i32) -> Input {
        let f = facing as i8;
        let (stick_x, stick_y) = match self {
            Throw::Forward => (f * TILT, 0),
            Throw::Back => (-f * TILT, 0),
            Throw::Up => (0, TILT),
            Throw::Down => (0, -TILT),
        };
        Input { stick_x, stick_y, buttons: 0 }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Plan {
    Wait,
    /// Walk (or run, when far) toward `goal` until within `within` of it, braking so it
    /// doesn't slide past or off a ledge.
    Approach { goal: Fx, within: Fx },
    Retreat,
    /// Start `slot`'s move, aimed toward `dir`. A move that doesn't turn by itself gets
    /// a frame of stick toward `dir` first when the fighter faces away. A jab keeps
    /// pressing into its combo while the hits land.
    Strike { slot: Slot, dir: i8 },
    /// Answering a hit it saw coming (see [`Guard`]).
    Guard(Guard),
    /// A hop (`full` or short) drifting toward `dir`, then the aerial that will connect,
    /// picked frame by frame (or, with `swing_at`, a nair/fair on that frame: lower
    /// levels). `offstage`: jumping off the ledge after a recovering opponent, ended by
    /// `Cpu::offstage_ok`.
    Hop { full: bool, dir: i8, offstage: bool, swing_at: Option<u8> },
    /// Full hop plus double jump, drifting toward `goal` (climbing to a platform).
    Jump { goal: Fx },
    DropDown,
}

/// A defensive answer to a hit the CPU sees coming.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Guard {
    /// Hold shield while the attack lasts, then act out of it or let go.
    Shield,
    Spot,
    /// A roll toward this side of the world (-1 left, 1 right).
    Roll(i8),
    /// An air dodge with this stick (0, 0: in place).
    AirDodge(i8, i8),
    /// The down special, if it is a counter.
    Counter,
}

/// How the CPU gets back to the stage: when it double-jumps and up-specials, whether it
/// air-dodges in, and whether it drifts for the ledge or the stage. Picked once per trip
/// offstage (`Cpu::pick_recovery`), checked by playing it out.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
struct Recovery {
    /// Double-jumps once falling below this height above the stage's top (units).
    jump_at: i32,
    /// With the jumps gone, up-specials once falling below this height.
    special_at: i32,
    /// Whether, and when, it spends its air dodge getting back.
    air_dodge: AirDodgeIn,
    /// Drifts for the ledge (stops pushing in just outside it) instead of the stage.
    ledge: bool,
}

/// A recovery's air dodge toward the stage (up and in).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum AirDodgeIn {
    No,
    /// Once within `AIR_DODGE_REACH` of the ledge: a mix-up past an edge-guarder.
    Near,
    /// As soon as it's falling, for distance (no gravity while it travels): before the
    /// double jump and up special, from farther out than they reach alone. Diagonally
    /// up and in, or (`false`) straight in.
    Far(bool),
}

/// Drift in, double jump once falling near the stage's height, then up special.
const PLAIN_RECOVERY: Recovery = Recovery { jump_at: 5, special_at: 5, air_dodge: AirDodgeIn::No, ledge: false };
/// The mix-ups: jump early and come in high, save the jump and come in low, air-dodge
/// in, or hang from the ledge. And one only for distance (`AirDodgeIn::Far`).
const MIXED_RECOVERIES: [Recovery; 4] = [
    Recovery { jump_at: 35, ..PLAIN_RECOVERY },
    Recovery { jump_at: -12, special_at: -10, ..PLAIN_RECOVERY },
    Recovery { air_dodge: AirDodgeIn::Near, ..PLAIN_RECOVERY },
    Recovery { ledge: true, ..PLAIN_RECOVERY },
];
const FAR_RECOVERIES: [Recovery; 2] = [Recovery { air_dodge: AirDodgeIn::Far(true), ..PLAIN_RECOVERY }, Recovery { air_dodge: AirDodgeIn::Far(false), ..PLAIN_RECOVERY }];

/// Below the run threshold, so the CPU walks.
const WALK: i8 = 60;
/// Past the tilt threshold but short of a smash flick, so attacks come out as tilts.
const TILT: i8 = 60;
/// Just past the deadzone: turns a standing fighter without walking it anywhere much.
const TURN: i8 = 30;
/// Holds its shield at least this long once it's up, while the attacker stays close.
const SHIELD_FRAMES: u8 = 6;
/// Never shields into a hit that would leave less than this, and lets go below it.
const SHIELD_LOW: Fx = Fx::int(12);
/// An attack farther than this (feet to feet) is no threat.
const THREAT_RANGE: Fx = Fx::int(50);
/// Plays a guard forward this many frames: long enough to see a roll end, at most
/// `GUARD_FRAMES` (or `RECOVERY_FRAMES` for an air dodge while recovering).
const GUARD_MIN_FRAMES: u16 = 34;
const GUARD_FRAMES: u16 = 44;
/// Score for a guard that leaves it free `n` frames before the attacker (or after):
/// `GUARD_PER_FRAME` per frame, within `±GUARD_ADVANTAGE`.
const GUARD_PER_FRAME: i32 = 3;
const GUARD_ADVANTAGE: i32 = 25;
/// Guards' base scores: a counter, then shield (quick to act out of and doesn't move
/// it), spot dodge, then rolls and air dodges (long end lag, and they move it).
const COUNTER_SCORE: i32 = 50;
const SHIELD_SCORE: i32 = 40;
const SPOT_DODGE_SCORE: i32 = 25;
const ROLL_SCORE: i32 = 15;
const AIR_DODGE_SCORE: i32 = 15;
const COUNTER_HIT_BONUS: i32 = 40;
/// A guard that leaves it free at least `PUNISH_FRAMES` before the attacker, within
/// `PUNISH_RANGE` of it (a grab or a jab away), is a punish: rolling behind a laggy
/// move beats a shield whose pushback leaves it out of reach.
const PUNISH_FRAMES: i32 = 8;
const PUNISH_RANGE: Fx = Fx::int(14);
const PUNISH_BONUS: i32 = 40;
/// Random spread added to guard scores, so close options take turns.
const GUARD_NOISE: u32 = 20;
/// A roll that ends this close to a ledge is a bad idea.
const ROLL_LEDGE_MARGIN: Fx = Fx::int(8);
const LEDGE_ROLL_PENALTY: i32 = 40;
/// Pressured this close to a ledge, a roll that ends `CORNER_ESCAPE` farther from it
/// gets out of the corner.
const CORNER: Fx = Fx::int(20);
const CORNER_ESCAPE: Fx = Fx::int(10);
const CORNER_BONUS: i32 = 25;
/// A recovery is played out at most this many frames, a hop after a launched opponent this many.
const RECOVERY_FRAMES: u16 = 240;
const CHASE_FRAMES: u16 = 40;
/// Air-dodges in toward the ledge from at most this far outside it (and below it).
const AIR_DODGE_REACH: Fx = Fx::int(24);
/// The stick for a directional air dodge up and in: about 45 degrees.
const DIAGONAL: i8 = 70;
/// DI: its scores per unit of room left before a blast zone (up to `DI_ROOM`), per
/// unit offstage where the launch ends, and per unit of distance from the attacker when
/// hitstun ends (up to `DI_ESCAPE`).
const DI_PER_ROOM: i32 = 10;
const DI_ROOM: Fx = Fx::int(50);
const DI_PER_OFFSTAGE: i32 = 3;
const DI_PER_ESCAPE: i32 = 2;
const DI_ESCAPE: Fx = Fx::int(40);
/// A DI that still KOs.
const DI_KO: i32 = -100_000;
/// Targets standing higher than this above the CPU are out of utilt range.
const UTILT_REACH: Fx = Fx::int(20);
/// An airborne opponent this far above the CPU's feet is "above": wait under it,
/// anti-air it or jump after it, never climb after it.
const ABOVE: Fx = Fx::int(12);
/// An opponent this far below a CPU standing on a soft platform is worth dropping to.
const BELOW: Fx = Fx::int(15);
/// Jumps after an airborne opponent above only within this far sideways and up.
const CHASE_X: Fx = Fx::int(24);
const CHASE_Y: Fx = Fx::int(40);
/// Never walk closer than this to the main stage's ledges.
const EDGE_MARGIN: Fx = Fx::int(3);
/// Runs instead of walking when the goal is farther than this (judgement allowing).
const RUN_DISTANCE: Fx = Fx::int(28);
/// Full hop + double jump clears about 50 units; aim a bit lower than that.
const CLIMB_HEIGHT: Fx = Fx::int(45);
/// Close enough horizontally to jump for a platform instead of walking first.
const JUMP_RANGE: Fx = Fx::int(45);
const HOP_ATTACK_FRAME: u8 = 7;
const FULL_HOP_HOLD: u8 = 12;
/// Where it waits to edge-guard: this far in from the ledge, farther while the
/// opponent hangs from it (its getups are invincible and land on the stage).
const LEDGE_GUARD_SPOT: Fx = Fx::int(5);
const LEDGE_HANG_SPOT: Fx = Fx::int(14);
/// Jumps off after a recovering opponent only this far out past the ledge, and from
/// at most this far below the stage to this far above it.
const OFFSTAGE_REACH: Fx = Fx::int(38);
const OFFSTAGE_LOW: Fx = Fx::int(25);
const OFFSTAGE_HIGH: Fx = Fx::int(45);
/// Heads back once it's this far past the ledge, this far below the stage, or this
/// many frames into the chase.
const OFFSTAGE_LIMIT: Fx = Fx::int(42);
const OFFSTAGE_DEPTH: Fx = Fx::int(10);
const OFFSTAGE_FRAMES: u8 = 45;
/// Guards against projectiles that would hit within this many frames.
const INCOMING_FRAMES: u16 = 14;
/// Frames of the opponent's path the CPU predicts, and so how far ahead a move's
/// hitboxes are checked against it.
const HORIZON: usize = 48;
/// Launches are followed this many frames to see whether they KO.
const LAUNCH_FRAMES: u32 = 180;
/// A projectile that only connects after this many frames is a zoning shot: taken a
/// third as often as a strike, so the CPU still walks in.
const ZONING_FRAME: u16 = 24;
/// Frames between its projectiles, so it doesn't stand and camp.
const SHOT_COOLDOWN: u32 = 60;

/// Score weights: per point of damage, per frame until it connects, per frame of end
/// lag after it, and the bonuses for a launch that KOs or leaves the opponent offstage.
const PER_DAMAGE: i32 = 10;
const PER_STARTUP_FRAME: i32 = 4;
const PER_ENDLAG_FRAME: i32 = 2;
/// Moves out within this many frames are quick; each frame slower costs `PER_SLOW_FRAME` more.
const QUICK_FRAMES: i32 = 8;
const PER_SLOW_FRAME: i32 = 8;
/// Per frame a throw leaves the opponent in hitstun after the thrower can act again
/// (up to `MAX_ADVANTAGE`): a throw that sets up a follow-up.
const PER_ADVANTAGE_FRAME: i32 = 4;
const MAX_ADVANTAGE: i32 = 20;
/// ...as long as the launch carries it less than this far.
const FOLLOW_UP_RANGE: Fx = Fx::int(20);
const KO_BONUS: i32 = 400;
const OFFSTAGE_BONUS: i32 = 50;
const COMBO_BONUS: i32 = 40;
/// Grabbing a shielding opponent, and hitting one (only chips the shield).
const GRAB_SHIELD_BONUS: i32 = 120;
const HIT_SHIELD_PENALTY: i32 = 80;

/// Where the opponent's feet will be on each of the next `HORIZON` frames.
type Path = [(Fx, Fx); HORIZON + 1];

#[derive(Clone, Copy, Debug)]
struct Hit {
    /// Frames from now until it connects.
    frame: u16,
    /// Frames from now until the move commits: its hitbox comes out, or its projectile
    /// leaves (what an opponent sees coming).
    start: u16,
    damage: i32,
    angle: i32,
    base_kb: i32,
    kb_growth: i32,
    /// Which way the knockback is mirrored.
    dir: i32,
    /// Where the opponent is when it connects.
    x: Fx,
    y: Fx,
    grab: bool,
    projectile: bool,
}

/// Where a launch leaves the opponent.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Launch {
    Stays,
    /// Offstage once the knockback is spent, this far past the ledge (or below it).
    Offstage(Fx),
    Ko,
}

/// A move worth starting and how good it looks.
#[derive(Clone, Copy, Debug)]
struct Choice {
    slot: Slot,
    dir: i8,
    score: i32,
    hit: Hit,
}

/// What a decision looks at: the CPU's fighter, its target and where it's going.
struct Ctx<'a> {
    me: &'a Fighter,
    t: &'a Fighter,
    stage: &'a Stage,
    main: &'a Platform,
    path: Path,
    /// Projectiles are off cooldown.
    shots: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Cpu {
    pub player: usize,
    level: &'static CpuLevel,
    rng: u32,
    plan: Plan,
    /// Frames since `plan` was chosen.
    plan_age: u8,
    /// The current hop's aerial has been thrown.
    swung: bool,
    /// While holding someone: pummels still to do and the throw after them.
    grab_plan: Option<(u8, Throw)>,
    /// The world frame of its last projectile, for `SHOT_COOLDOWN`.
    last_shot: u32,
    prev: Input,
    /// The threat (an attack or a projectile, see `threat`) it last decided about, and
    /// whether it is still looking for a guard against it, with dodges allowed.
    guard_seen: Option<Threat>,
    /// The target's current attack: its move, the last frame of it seen, and the world
    /// frame it started on (so `react` counts real frames, charging and hitlag included).
    watch: Option<(MoveId, u16, u32)>,
    guard_open: bool,
    guard_dodges: bool,
    /// The stick it holds for the pending launch's DI, once chosen.
    di_input: Option<Input>,
    /// How it's getting back this trip offstage, once picked.
    recovery: Option<Recovery>,
    /// A copy playing a rollout: it never rolls out itself.
    simulating: bool,
}

/// What happened to the CPU's fighter when a copy of the world was played forward.
#[derive(Clone, Copy, Debug, Default)]
struct Outcome {
    /// Frame (1 = the next step) it was hit, grabbed or had its shield broken.
    hit: Option<u16>,
    /// The frame after the last one it couldn't act on (dodging, in shield stun...).
    free: u16,
    /// The same for the opponent.
    opp_free: u16,
    /// How far apart the two were (feet, sideways) on its last frame it couldn't act.
    gap: Fx,
    /// Frame its own hit on the opponent landed.
    landed: Option<u16>,
    /// Frame it was standing on a platform or hanging from a ledge (a recovery made it).
    safe: Option<u16>,
    ko: bool,
    /// Where it was at the end, and its shield.
    x: Fx,
    shield: Fx,
}

/// What the CPU feeds its fighter in a rollout after the first frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Then {
    /// Nothing.
    Idle,
    /// Keeps shield held.
    Shield,
    /// Whatever a copy of the CPU would do (recovering, a hop's aerial).
    Policy,
}

impl Cpu {
    pub fn new(player: usize, level: &'static CpuLevel) -> Cpu {
        let rng = 0x9E37_79B9 ^ (player as u32 + 1).wrapping_mul(0x85EB_CA6B);
        Cpu {
            player,
            level,
            rng: rng.max(1),
            plan: Plan::Wait,
            plan_age: 0,
            swung: false,
            grab_plan: None,
            last_shot: 0,
            prev: Input::default(),
            guard_seen: None,
            watch: None,
            guard_open: false,
            guard_dodges: false,
            di_input: None,
            recovery: None,
            simulating: false,
        }
    }

    /// This CPU with its RNG reseeded from `seed` (mixed with its port), so CPU-vs-CPU
    /// runs such as the balance harness can play many different games. Still
    /// deterministic: the same seed replays the same choices. `new` keeps its fixed
    /// per-port seed.
    pub fn with_seed(mut self, seed: u32) -> Cpu {
        let mixed = (seed ^ 0x9E37_79B9).wrapping_mul(0x85EB_CA6B) ^ (self.player as u32 + 1).wrapping_mul(0xC2B2_AE35);
        self.rng = (mixed ^ (mixed >> 16)).max(1);
        self
    }

    pub fn easy(player: usize) -> Cpu {
        Cpu::new(player, &CpuLevel::EASY)
    }

    /// A CPU at Melee-style level `n` (1 to 9; see [`CpuLevel::level`]).
    pub fn with_level(player: usize, n: u8) -> Cpu {
        Cpu::new(player, CpuLevel::level(n))
    }

    /// The input to feed this CPU's fighter for the next [`World::step`].
    pub fn think(&mut self, world: &World) -> Input {
        let input = self.decide(world);
        self.prev = input;
        input
    }

    fn decide(&mut self, world: &World) -> Input {
        let me = &world.fighters[self.player];
        if me.holding.is_none() {
            self.grab_plan = None;
        }
        if me.di_pending.is_none() {
            self.di_input = None;
        }
        let Some(mi) = world.stage.platforms.iter().position(|p| !p.soft) else { return Input::default() };
        let main = &world.stage.platforms[mi];
        let target = self.target(world);
        self.watch = match target.map(|t| t.state) {
            Some(State::Attack { mv, frame, .. }) => match self.watch {
                Some((m, f, start)) if m == mv && frame >= f => Some((mv, frame, start)),
                _ => Some((mv, frame, world.frame.saturating_sub(u32::from(frame) - 1))),
            },
            _ => None,
        };
        match me.state {
            // Mash: a fresh press every other frame.
            State::Held { .. } => return if self.prev.buttons == 0 { Input { buttons: Input::ATTACK, ..Input::default() } } else { Input::default() },
            State::Holding { .. } => return self.hold(me, world),
            State::Hitstun { .. } => {
                // A new launch: pick its recovery afresh once it can act.
                self.recovery = None;
                return self.di(me, target, world, main);
            }
            State::ShieldBreak { .. } | State::Respawning { .. } | State::Eliminated => return Input::default(),
            State::LedgeHang => {
                self.recovery = None;
                return self.ledge_getup(me, target, main);
            }
            _ => {}
        }
        let recovering = !me.grounded() && (me.x < main.left || me.x > main.right || me.y < main.y) && !self.offstage_ok(me, main);
        self.plan_age = self.plan_age.saturating_add(1);
        if let Some(input) = self.guard(me, target, world, recovering) {
            return input;
        }
        if recovering {
            return self.recover(me, world, main);
        }
        self.recovery = None;

        // Plans that take longer than a quick CPU's reaction time get to finish.
        let committed = match self.plan {
            Plan::Jump { .. } => !me.grounded(),
            Plan::Hop { .. } => !me.grounded() || self.plan_age <= me.params.jump_squat + 1,
            Plan::Strike { slot, .. } => self.plan_age < 2 || (slot == Slot::Jab && matches!(me.state, State::Attack { .. })),
            _ => false,
        };
        // An opening (end lag, a landing, hitstun) is worth looking at sooner.
        let opening = target.is_some_and(vulnerable)
            && matches!(self.plan, Plan::Wait | Plan::Approach { .. } | Plan::Retreat)
            && self.plan_age >= self.level.react.div_ceil(2);
        // New plans only once it can act: a press during lag would be buffered and come
        // out on its first free frame, even if a guard is needed by then.
        if (self.plan_age >= self.level.reaction_frames || opening) && !committed && actionable(me) {
            self.plan = match target {
                Some(t) => {
                    let shots = world.frame >= self.last_shot + SHOT_COOLDOWN || self.last_shot == 0;
                    let ctx = Ctx { me, t, stage: &world.stage, main, path: predict(t, &world.stage), shots };
                    let plan = self.choose(&ctx, world);
                    if let Plan::Strike { slot, .. } = plan
                        && slot.move_id(me.character.moveset()).data().projectile.is_some()
                    {
                        self.last_shot = world.frame;
                    }
                    plan
                }
                None => Plan::Wait,
            };
            self.plan_age = 0;
            self.swung = false;
        }
        self.execute(me, target, &world.stage, main)
    }

    /// The nearest opponent still in the game.
    fn target<'a>(&self, world: &'a World) -> Option<&'a Fighter> {
        let me = &world.fighters[self.player];
        world
            .fighters
            .iter()
            .enumerate()
            .filter(|&(i, f)| i != self.player && !matches!(f.state, State::Respawning { .. } | State::Eliminated))
            .map(|(_, f)| f)
            .min_by_key(|f| ((f.x - me.x).abs() + (f.y - me.y).abs()).raw())
    }

    fn target_index(&self, world: &World) -> Option<usize> {
        let t = self.target(world)?;
        world.fighters.iter().position(|f| std::ptr::eq(f, t))
    }

    /// Keeps a guard going, or answers a hit it sees coming: plays each guard it may use
    /// forward on a copy of the world and takes one that doesn't get hit, the one that
    /// leaves it freest to punish when judgement allows. A hit that would whiff anyway
    /// is left alone (the opening is then punished by `choose`).
    fn guard(&mut self, me: &Fighter, target: Option<&Fighter>, world: &World, recovering: bool) -> Option<Input> {
        if let Plan::Guard(g) = self.plan {
            match g {
                Guard::Shield => {
                    if let Some(input) = self.keep_shield(me, target, world) {
                        return Some(input);
                    }
                }
                // Recovering: `recover` steers the air dodge.
                Guard::AirDodge(..) if recovering => {}
                _ if self.plan_age <= 1 || matches!(me.state, State::Dodge { .. } | State::Attack { .. }) => return Some(Input::default()),
                _ => {}
            }
            // Over: look again straight away (to punish).
            self.plan = Plan::Wait;
            self.plan_age = self.level.reaction_frames;
            if recovering {
                return None;
            }
        }
        if self.simulating {
            return None;
        }
        let watched = self.watch.map_or(0, |(_, _, start)| world.frame + 1 - start);
        let (seen, opp) = threat(self.player, me, target, world, watched >= u32::from(self.level.react))?;
        if !seen.same(self.guard_seen) {
            self.guard_open = self.chance(self.level.defend);
            self.guard_dodges = self.chance(self.level.dodge);
        }
        self.guard_seen = Some(seen);
        if !self.guard_open {
            return None;
        }
        let options = self.guard_options(me, world, !world.fighters[opp].charging());
        if options.iter().all(Option::is_none) {
            return None;
        }
        // While recovering, an air dodge has to get it hit-free all the way back.
        let frames = if recovering { RECOVERY_FRAMES } else { guard_frames(&world.fighters[opp]) };
        let baseline = if me.grounded() {
            self.rollout(world, Some(Input::default()), Then::Idle, frames, opp, None, false)
        } else {
            self.rollout(world, None, Then::Policy, frames, opp, None, recovering)
        };
        if baseline.hit.is_none() {
            // It whiffs: no need.
            self.guard_open = false;
            return None;
        }
        let main = world.stage.platforms.iter().find(|p| !p.soft)?;
        let mut picks: [Option<(i32, Guard)>; 8] = [None; 8];
        for (slot, g) in picks.iter_mut().zip(options.iter()) {
            let Some(g) = *g else { continue };
            let then = match g {
                Guard::Shield => Then::Shield,
                Guard::AirDodge(..) => Then::Policy,
                _ => Then::Idle,
            };
            let out = self.rollout(world, Some(guard_input(g)), then, frames, opp, Some(Plan::Guard(g)), recovering);
            *slot = guard_score(g, &out, main, recovering, me.x).map(|s| (s, g));
        }
        let n = picks.iter().flatten().count();
        if n == 0 {
            // Nothing works yet (a dodge too early, say): look again next frame.
            return None;
        }
        let (_, g) = if self.chance(self.level.judgement) {
            let mut best: Option<(i32, Guard)> = None;
            for &(s, g) in picks.iter().flatten() {
                let s = s + self.roll(GUARD_NOISE) as i32;
                if best.is_none_or(|(b, _)| s > b) {
                    best = Some((s, g));
                }
            }
            best?
        } else {
            *picks.iter().flatten().nth(self.roll(n as u32) as usize)?
        };
        self.guard_open = false;
        self.plan = Plan::Guard(g);
        self.plan_age = 0;
        self.swung = false;
        Some(guard_input(g))
    }

    /// The guards it can use from where it is: shield and dodges on the ground (or in
    /// shield), air dodges in the air, and its counter if it has one. Against a charge
    /// still being held (`timed` false) only the shield: the hit could come any time.
    fn guard_options(&mut self, me: &Fighter, world: &World, timed: bool) -> [Option<Guard>; 8] {
        let mut out = [None; 8];
        let dodges = self.guard_dodges && timed;
        // In the air the air dodge is its shield: `defend` alone decides.
        let air_dodges = timed;
        let counter = timed && me.character.moveset().down_special.data().counter.is_some() && self.chance(self.level.judgement / 3);
        let center = world.stage.platforms.iter().find(|p| !p.soft).map_or(Fx::ZERO, |m| (m.left + m.right) * Fx::ratio(1, 2));
        let inward = dir_of(center - me.x);
        let list: &[Option<Guard>] = match me.state {
            State::Ground | State::Crouch => &[
                Some(Guard::Shield),
                counter.then_some(Guard::Counter),
                dodges.then_some(Guard::Spot),
                dodges.then_some(Guard::Roll(-1)),
                dodges.then_some(Guard::Roll(1)),
            ],
            State::Shield => &[Some(Guard::Shield), dodges.then_some(Guard::Spot), dodges.then_some(Guard::Roll(-1)), dodges.then_some(Guard::Roll(1))],
            State::Air if !me.air_dodge_used => &[
                counter.then_some(Guard::Counter),
                air_dodges.then_some(Guard::AirDodge(0, 0)),
                air_dodges.then_some(Guard::AirDodge(inward * DIAGONAL, DIAGONAL)),
                air_dodges.then_some(Guard::AirDodge(0, 100)),
                air_dodges.then_some(Guard::AirDodge(inward * 100, 0)),
                air_dodges.then_some(Guard::AirDodge(-inward * DIAGONAL, DIAGONAL)),
            ],
            State::Air => &[counter.then_some(Guard::Counter)],
            _ => &[],
        };
        for (o, g) in out.iter_mut().zip(list) {
            *o = *g;
        }
        out
    }

    /// Shielding: hold it while the attack or projectile still threatens (and the shield
    /// holds), then act out of shield on an opponent in its end lag, or let go.
    fn keep_shield(&mut self, me: &Fighter, target: Option<&Fighter>, world: &World) -> Option<Input> {
        let hold = Input { buttons: Input::SHIELD, ..Input::default() };
        match me.state {
            State::ShieldStun { .. } => return Some(hold),
            State::Shield => {}
            // The press frame, before the shield is up.
            State::Ground | State::Crouch if self.plan_age <= 1 => return Some(hold),
            _ => return None,
        }
        let threatened = target.is_some_and(|t| threatening(t, me)) || incoming(me, self.player, world).is_some();
        if threatened {
            if me.shield > SHIELD_LOW {
                return Some(hold);
            }
            // About to break: dodge out instead.
            self.guard_open = true;
            self.guard_dodges = true;
            return None;
        }
        if let Some(t) = target
            && let Some(plan) = self.out_of_shield(me, t, world)
        {
            self.plan = plan;
            self.plan_age = 0;
            self.swung = false;
            let main = world.stage.platforms.iter().find(|p| !p.soft)?;
            return Some(self.execute(me, target, &world.stage, main));
        }
        let near = target.is_some_and(|t| (t.x - me.x).abs() < Fx::int(20) && !vulnerable(t));
        (near && self.plan_age < SHIELD_FRAMES).then_some(hold)
    }

    /// The best grab, up smash or up special straight out of shield that connects with
    /// an opponent in its end lag (judgement allowing).
    fn out_of_shield(&mut self, me: &Fighter, t: &Fighter, world: &World) -> Option<Plan> {
        if !vulnerable(t) || !self.chance(self.level.judgement.max(self.level.attack_chance)) {
            return None;
        }
        let main = world.stage.platforms.iter().find(|p| !p.soft)?;
        let c = Ctx { me, t, stage: &world.stage, main, path: predict(t, &world.stage), shots: false };
        let mut best: Option<(i32, Slot)> = None;
        for slot in OUT_OF_SHIELD_SLOTS {
            let data = slot.move_id(me.character.moveset()).data();
            if data.counter.is_some() {
                continue;
            }
            if let Some(hit) = simulate(&c, data, me.facing, 0) {
                let s = score(&c, data, &hit) + self.roll(NOISE) as i32;
                if best.is_none_or(|(b, _)| s > b) {
                    best = Some((s, slot));
                }
            }
        }
        best.map(|(_, slot)| Plan::Strike { slot, dir: me.facing as i8 })
    }

    /// Hitstun with a launch still to DI: the stick it holds for it (chosen once per
    /// launch: the best by `best_di`, or nothing).
    fn di(&mut self, me: &Fighter, target: Option<&Fighter>, world: &World, main: &Platform) -> Input {
        let Some(launch) = me.di_pending else { return Input::default() };
        if let Some(input) = self.di_input {
            return input;
        }
        let input = if self.chance(self.level.di) { best_di(me, launch, target, &world.stage, main) } else { Input::default() };
        self.di_input = Some(input);
        input
    }

    /// Plays a copy of `world` forward up to `frames` frames, feeding its fighter `first`
    /// (or, with `None`, what a copy of this CPU would do) and then `then`, everyone
    /// else nothing. `plan` starts the copy's plan for `Then::Policy`. With `stop_safe`
    /// it stops once its fighter stands on a platform or hangs from a ledge.
    #[allow(clippy::too_many_arguments)]
    fn rollout(&self, world: &World, first: Option<Input>, then: Then, frames: u16, opp: usize, plan: Option<Plan>, stop_safe: bool) -> Outcome {
        let mut w = world.clone();
        let mut sim = self.clone();
        sim.simulating = true;
        if let Some(p) = plan {
            sim.plan = p;
            sim.plan_age = 0;
        }
        let n = w.fighters.len().min(MAX_FIGHTERS);
        let mut inputs = [Input::default(); MAX_FIGHTERS];
        let mut out = Outcome { free: 1, opp_free: 1, gap: (world.fighters[self.player].x - world.fighters[opp].x).abs(), ..Outcome::default() };
        for k in 1..=frames {
            let mine = match (k, first, then) {
                (1, Some(input), _) => input,
                (_, _, Then::Policy) | (1, None, _) => sim.think(&w),
                (_, _, Then::Shield) => Input { buttons: Input::SHIELD, ..Input::default() },
                (_, _, Then::Idle) => Input::default(),
            };
            sim.prev = mine;
            inputs[self.player] = mine;
            w.step(&inputs[..n]);
            for e in &w.events {
                match *e {
                    Event::Hit { defender, .. } | Event::Grab { defender, .. } if defender == self.player => {
                        out.hit.get_or_insert(k);
                    }
                    Event::ShieldBreak { fighter } if fighter == self.player => {
                        out.hit.get_or_insert(k);
                    }
                    Event::Hit { attacker, defender, .. } if attacker == self.player && defender == opp => {
                        out.landed.get_or_insert(k);
                    }
                    Event::Ko { fighter } if fighter == self.player => out.ko = true,
                    _ => {}
                }
            }
            let f = &w.fighters[self.player];
            if !actionable(f) {
                out.free = k + 1;
                out.gap = (f.x - w.fighters[opp].x).abs();
            }
            if !actionable(&w.fighters[opp]) {
                out.opp_free = k + 1;
            }
            if out.safe.is_none() && (f.state == State::LedgeHang || f.grounded()) {
                out.safe = Some(k);
            }
            if out.ko || (stop_safe && out.safe.is_some()) {
                break;
            }
        }
        let f = &w.fighters[self.player];
        (out.x, out.shield) = (f.x, f.shield);
        out
    }

    fn choose(&mut self, c: &Ctx, world: &World) -> Plan {
        let (me, t, main) = (c.me, c.t, c.main);
        let (dx, dy) = (t.x - me.x, t.y - me.y);
        let toward = dir_of(dx);
        if offstage(t, main) {
            return if self.chance(self.level.edge_guard) { self.edge_guard(c) } else { Plan::Wait };
        }
        if me.state == State::Air {
            return match self.best(c, &AIR_SLOTS) {
                Some(ch) if self.chance(self.level.attack_chance) => Plan::Strike { slot: ch.slot, dir: ch.dir },
                _ => Plan::Wait,
            };
        }
        let standing = matches!(me.state, State::Ground | State::Crouch);
        if standing && let Some(ch) = self.best(c, &GROUND_SLOTS) {
            let eager = if vulnerable(t) { (self.level.attack_chance + 100) / 2 } else { self.level.attack_chance };
            let eager = if ch.hit.projectile && ch.hit.frame > ZONING_FRAME { eager / 3 } else { eager };
            let eager = if ch.slot == Slot::Grab && !t.shielding() { eager * (50 + self.level.grab_chance) / 100 } else { eager };
            if self.chance(eager) {
                return Plan::Strike { slot: ch.slot, dir: ch.dir };
            }
        }

        if standing
            && !t.grounded()
            && matches!(t.state, State::Hitstun { .. })
            && dy > Fx::ZERO
            && self.chance(self.level.judgement)
            && let Some(plan) = self.chase(c, world)
        {
            return plan;
        }
        if !t.grounded() && dy > ABOVE {
            // Airborne above: wait under where it comes down (anti-airs come from the
            // move search above as it falls into range) or jump after it with an
            // aerial. Never climb after it: that's how two CPUs end up mirroring each
            // other's jumps forever.
            if standing && dx.abs() < CHASE_X && dy < CHASE_Y && self.chance(self.level.approach_chance / 3) {
                return Plan::Hop { full: true, dir: toward, offstage: false, swing_at: self.swing_frame() };
            }
            let landing = c.path[HORIZON].0.clamp(main.left + LEDGE_GUARD_SPOT, main.right - LEDGE_GUARD_SPOT);
            return if self.chance(self.level.approach_chance) { Plan::Approach { goal: landing, within: Fx::int(6) } } else { Plan::Wait };
        }
        if dy > UTILT_REACH {
            // Standing on a platform above: climb after it, one platform at a time.
            if !me.grounded() || !self.chance(self.level.approach_chance) {
                return Plan::Wait;
            }
            let goal = if dy <= CLIMB_HEIGHT {
                t.x
            } else {
                world
                    .stage
                    .platforms
                    .iter()
                    .filter(|p| p.y > me.y && p.y - me.y <= CLIMB_HEIGHT && p.y < t.y)
                    .map(|p| (p.left + p.right) * Fx::ratio(1, 2))
                    .min_by_key(|&center| (center - me.x).abs().raw())
                    .unwrap_or(t.x)
            };
            return if (goal - me.x).abs() > JUMP_RANGE { Plan::Approach { goal, within: JUMP_RANGE } } else { Plan::Jump { goal } };
        }
        let on_soft = me.grounded_on.is_some_and(|i| world.stage.platforms[i].soft);
        if me.grounded() && on_soft && dy < -BELOW {
            // Below: drop through to it (an aerial comes from the air search on the
            // way down) rather than wait up here to be juggled.
            return if self.chance(self.level.approach_chance) { Plan::DropDown } else { Plan::Wait };
        }
        let range = reach(me) + t.params.radius;
        if dx.abs() > range {
            let approach = Plan::Approach { goal: t.x, within: range - Fx::int(2) };
            return if self.chance(self.level.approach_chance) { approach } else { Plan::Wait };
        }
        let roll = self.roll(100);
        if roll < 15 {
            Plan::Hop { full: false, dir: toward, offstage: false, swing_at: self.swing_frame() }
        } else if roll < 35 {
            Plan::Retreat
        } else if roll < 35 + self.level.grab_chance / 3 && standing && dy.abs() < Fx::int(5) {
            Plan::Strike { slot: Slot::Grab, dir: toward }
        } else {
            Plan::Wait
        }
    }

    /// The opponent is offstage or on the ledge: hit it from the ledge (ground moves,
    /// projectiles), jump off after it with an aerial, or wait by the ledge.
    fn edge_guard(&mut self, c: &Ctx) -> Plan {
        let (me, t, main) = (c.me, c.t, c.main);
        let center = (main.left + main.right) * Fx::ratio(1, 2);
        let side: i8 = if t.x < center { -1 } else { 1 };
        let edge = if side < 0 { main.left } else { main.right };
        let standing = matches!(me.state, State::Ground | State::Crouch);
        let on_main = me.grounded() && me.y == main.y && main.contains_x(me.x);
        if standing
            && let Some(ch) = self.best(c, &GROUND_SLOTS)
            && self.chance(self.level.attack_chance)
        {
            return Plan::Strike { slot: ch.slot, dir: ch.dir };
        }
        let past = (t.x - edge) * side as i32;
        let chaseable = t.state != State::LedgeHang
            && past > Fx::ZERO
            && past < OFFSTAGE_REACH
            && t.y > main.y - OFFSTAGE_LOW
            && t.y < main.y + OFFSTAGE_HIGH
            && (me.x - edge).abs() < Fx::int(20);
        if on_main && standing && chaseable && me.air_jumps_left > 0 && self.chance(self.level.offstage) {
            return Plan::Hop { full: t.y > main.y, dir: side, offstage: true, swing_at: None };
        }
        let back = if t.state == State::LedgeHang { LEDGE_HANG_SPOT } else { LEDGE_GUARD_SPOT };
        Plan::Approach { goal: edge - back * side as i32, within: Fx::int(2) }
    }

    /// Whether to keep going offstage after a recovering opponent rather than recover.
    fn offstage_ok(&self, me: &Fighter, main: &Platform) -> bool {
        let Plan::Hop { offstage: true, .. } = self.plan else { return false };
        let past = (me.x - main.right).max(main.left - me.x);
        self.plan_age < OFFSTAGE_FRAMES
            && me.air_jumps_left > 0
            && me.y > main.y - OFFSTAGE_DEPTH
            && past < OFFSTAGE_LIMIT
            && !(self.swung && me.state == State::Air)
    }

    /// A launched opponent above, still in hitstun: the hop (full or short, toward it)
    /// whose aerial lands soonest when played out, if any does.
    fn chase(&mut self, c: &Ctx, world: &World) -> Option<Plan> {
        if self.simulating {
            return None;
        }
        let opp = self.target_index(world)?;
        let toward = dir_of(c.t.x - c.me.x);
        let mut best: Option<(u16, Plan)> = None;
        for full in [true, false] {
            let plan = Plan::Hop { full, dir: toward, offstage: false, swing_at: None };
            let out = self.rollout(world, None, Then::Policy, CHASE_FRAMES, opp, Some(plan), false);
            if let Some(k) = out.landed
                && out.hit.is_none()
                && best.is_none_or(|(b, _)| k < b)
            {
                best = Some((k, plan));
            }
        }
        best.map(|(_, plan)| plan)
    }

    /// How to get back this trip offstage. Mostly the plain recovery; with `recovery_mix`
    /// one of the mix-ups instead, and (judgement allowing) one that makes it when the
    /// plain one wouldn't. Every candidate is played out first, so a mix-up never trades
    /// a recovery that works for one that doesn't.
    fn pick_recovery(&mut self, world: &World) -> Recovery {
        if self.simulating {
            return PLAIN_RECOVERY;
        }
        let mix = self.chance(self.level.recovery_mix);
        let smart = self.chance(self.level.judgement);
        if !mix && !smart {
            return PLAIN_RECOVERY;
        }
        let opp = self.target_index(world).unwrap_or(self.player);
        let makes_it = |cpu: &Cpu, r: Recovery| {
            let mut sim = cpu.clone();
            sim.recovery = Some(r);
            sim.plan = Plan::Wait;
            let out = sim.rollout(world, None, Then::Policy, RECOVERY_FRAMES, opp, None, true);
            out.safe.is_some() && out.hit.is_none() && !out.ko
        };
        let plain = makes_it(self, PLAIN_RECOVERY);
        if (plain && !mix) || (!plain && !smart) {
            // It makes it and no mix-up is wanted, or it doesn't and no judgement to fix it.
            return PLAIN_RECOVERY;
        }
        let start = self.roll(MIXED_RECOVERIES.len() as u32) as usize;
        for i in 0..MIXED_RECOVERIES.len() {
            let r = MIXED_RECOVERIES[(start + i) % MIXED_RECOVERIES.len()];
            if makes_it(self, r) {
                return r;
            }
        }
        if !plain && let Some(&r) = FAR_RECOVERIES.iter().find(|&&r| makes_it(self, r)) {
            return r;
        }
        PLAIN_RECOVERY
    }

    /// The best move among `slots` that connects with the target, by score: with
    /// probability `judgement` the top one (plus a little noise), otherwise any that
    /// connects.
    fn best(&mut self, c: &Ctx, slots: &[Slot]) -> Option<Choice> {
        let mut choices: [Option<Choice>; 12] = [None; 12];
        let mut n = 0;
        for &slot in slots {
            if let Some(ch) = evaluate(c, slot) {
                choices[n] = Some(ch);
                n += 1;
            }
        }
        if n == 0 {
            return None;
        }
        if self.chance(self.level.judgement) {
            let mut best: Option<(i32, Choice)> = None;
            for ch in choices[..n].iter().flatten() {
                let s = ch.score + self.roll(NOISE) as i32;
                if best.is_none_or(|(b, _)| s > b) {
                    best = Some((s, *ch));
                }
            }
            best.map(|(_, ch)| ch)
        } else {
            choices[self.roll(n as u32) as usize]
        }
    }

    /// Lower levels throw a hop's aerial on a set frame instead of timing it.
    fn swing_frame(&mut self) -> Option<u8> {
        (!self.chance(self.level.judgement)).then_some(HOP_ATTACK_FRAME)
    }

    fn execute(&mut self, me: &Fighter, target: Option<&Fighter>, stage: &Stage, main: &Platform) -> Input {
        let toward = target.map_or(0, |t| dir_of(t.x - me.x));
        let age = self.plan_age;
        match self.plan {
            Plan::Wait => Input::default(),
            Plan::Approach { goal, within } => self.walk_to(me, main, goal, within),
            Plan::Retreat => {
                let away = me.x - Fx::int(toward as i32 * 30);
                self.walk_to(me, main, away, Fx::int(2))
            }
            Plan::Strike { slot, dir } => {
                let turn = !slot.turns() && me.state != State::Air && me.facing != dir as i32;
                if age == 0 && turn {
                    Input { stick_x: dir * TURN, ..Input::default() }
                } else if age == turn as u8 {
                    slot.input(dir, me.facing)
                } else if slot == Slot::Jab {
                    // Keep the jab chain going while it lands.
                    let chaining = target.is_some_and(|t| matches!(t.state, State::Hitstun { .. }));
                    let can = matches!(me.state, State::Attack { mv, frame, .. } if mv.data().combo.is_some_and(|(_, from)| frame + 1 >= from));
                    let press = chaining && can && !self.prev.held(Input::ATTACK);
                    Input { buttons: if press { Input::ATTACK } else { 0 }, ..Input::default() }
                } else {
                    Input::default()
                }
            }
            Plan::Hop { full, dir, swing_at, .. } => self.hop(me, target, stage, full, dir, swing_at),
            // `guard` drives these; this only starts one.
            Plan::Guard(g) if age == 0 => guard_input(g),
            Plan::Guard(_) => Input::default(),
            Plan::Jump { goal } => {
                let drift = if (goal - me.x).abs() < Fx::int(3) { 0 } else { dir_of(goal - me.x) * 100 };
                let double_jump = me.state == State::Air && me.vy <= Fx::ZERO && me.air_jumps_left > 0 && !self.prev.held(Input::JUMP);
                let jump = age < FULL_HOP_HOLD || double_jump;
                Input { stick_x: drift, stick_y: 0, buttons: if jump { Input::JUMP } else { 0 } }
            }
            Plan::DropDown if age == 0 => Input { stick_y: -100, ..Input::default() },
            Plan::DropDown => Input::default(),
        }
    }

    /// One frame of a hop: jump, then throw the aerial that will connect (or the set
    /// one on `swing_at`), drifting toward the target.
    fn hop(&mut self, me: &Fighter, target: Option<&Fighter>, stage: &Stage, full: bool, dir: i8, swing_at: Option<u8>) -> Input {
        let age = self.plan_age;
        if age == 0 {
            return Input { buttons: Input::JUMP, ..Input::default() };
        }
        if matches!(me.state, State::JumpSquat { .. }) {
            return Input { stick_x: dir * 100, stick_y: 0, buttons: if full { Input::JUMP } else { 0 } };
        }
        let drift = match target {
            Some(t) if (t.x - me.x).abs() > Fx::int(3) => dir_of(t.x - me.x) * 100,
            _ => 0,
        };
        let idle = Input { stick_x: drift, ..Input::default() };
        if me.state != State::Air || self.swung {
            return idle;
        }
        let toward = target.map_or(dir, |t| dir_of(t.x - me.x));
        let swing = match (swing_at, target) {
            (Some(frame), _) if age >= frame => Some(Input { stick_x: toward * 40, stick_y: 0, buttons: Input::ATTACK }),
            (Some(_), _) | (None, None) => None,
            (None, Some(t)) => {
                let Some(main) = stage.platforms.iter().find(|p| !p.soft) else { return idle };
                let c = Ctx { me, t, stage, main, path: predict(t, stage), shots: false };
                self.best(&c, &AIR_SLOTS).map(|ch| ch.slot.input(ch.dir, me.facing))
            }
        };
        match swing {
            Some(input) => {
                self.swung = true;
                input
            }
            None => idle,
        }
    }

    /// Walks toward `goal` until within `within`, running when it's far (judgement
    /// allowing), braking early enough not to overshoot, and never closer than
    /// `EDGE_MARGIN` to a main-stage ledge.
    fn walk_to(&self, me: &Fighter, main: &Platform, goal: Fx, within: Fx) -> Input {
        if !me.grounded() {
            return Input::default();
        }
        let p = me.params;
        let d = goal - me.x;
        let dir = dir_of(d);
        let moving_that_way = me.vx.signum() == dir as i32;
        let stopping = if moving_that_way { me.vx * me.vx / (p.traction * 2) } else { Fx::ZERO };
        if d.abs() <= within || d.abs() <= stopping {
            return Input::default();
        }
        let on_main = me.y == main.y && main.contains_x(me.x);
        let room = if !on_main {
            Fx::int(1000)
        } else if dir > 0 {
            main.right - me.x
        } else {
            me.x - main.left
        };
        if room <= EDGE_MARGIN + stopping {
            return Input::default();
        }
        let run_stop = p.run_speed * p.run_speed / (p.traction * 2);
        let run = self.level.judgement >= 40 && d.abs() > RUN_DISTANCE && room > run_stop + RUN_DISTANCE;
        Input { stick_x: dir * if run { 100 } else { WALK }, ..Input::default() }
    }

    /// Holding someone: pummel (judgement allowing), then the throw whose launch looks
    /// best (a KO, then offstage, then damage).
    fn hold(&mut self, me: &Fighter, world: &World) -> Input {
        let Some(victim) = me.holding.map(|v| &world.fighters[v]) else { return Input::default() };
        if self.grab_plan.is_none() {
            let pummels = if self.chance(self.level.judgement / 2) { 1 } else { 0 };
            let throw = self.pick_throw(me, victim, &world.stage);
            self.grab_plan = Some((pummels, throw));
        }
        let Some((pummels, throw)) = self.grab_plan else { return Input::default() };
        if pummels > 0 {
            if self.prev.held(Input::ATTACK) {
                return Input::default();
            }
            self.grab_plan = Some((pummels - 1, throw));
            return Input { buttons: Input::ATTACK, ..Input::default() };
        }
        throw.input(me.facing)
    }

    fn pick_throw(&mut self, me: &Fighter, victim: &Fighter, stage: &Stage) -> Throw {
        if !self.chance(self.level.judgement) {
            return Throw::ALL[self.roll(4) as usize];
        }
        let main = stage.platforms.iter().find(|p| !p.soft).unwrap_or(&stage.platforms[0]);
        let mut best = (i32::MIN, Throw::Forward);
        for throw in Throw::ALL {
            let s = throw_score(me, victim, stage, main, throw.move_id(me.character.moveset())) + self.roll(NOISE) as i32;
            if s > best.0 {
                best = (s, throw);
            }
        }
        best.1
    }

    /// Hanging from the ledge: climb, or (judgement allowing) mix in rolls, getup
    /// attacks and ledge jumps, more of them with the opponent waiting nearby.
    fn ledge_getup(&mut self, me: &Fighter, target: Option<&Fighter>, main: &Platform) -> Input {
        let climb = Input { stick_y: 100, ..Input::default() };
        if self.prev != Input::default() {
            // Let go of whatever brought it here, so the next press is a fresh one.
            return Input::default();
        }
        if !self.chance(self.level.judgement) {
            return climb;
        }
        let edge = if me.ledge_side > 0 { main.left } else { main.right };
        let near = target.is_some_and(|t| t.grounded() && (t.x - edge).abs() < Fx::int(20));
        let roll = self.roll(100);
        let buttons = match (near, roll) {
            (true, 0..35) => Input::SHIELD,
            (true, 35..65) => Input::ATTACK,
            (true, 65..85) | (false, 0..25) => Input::JUMP,
            _ => return climb,
        };
        Input { buttons, ..Input::default() }
    }

    /// Drift back toward the stage and double-jump once falling below it; with
    /// the double jump gone, up special.
    fn recover(&mut self, me: &Fighter, world: &World, stage: &Platform) -> Input {
        self.plan = Plan::Wait;
        self.plan_age = 0;
        let style = match self.recovery {
            Some(r) => r,
            None => {
                let r = self.pick_recovery(world);
                self.recovery = Some(r);
                r
            }
        };
        let center = (stage.left + stage.right) * Fx::ratio(1, 2);
        let toward: i8 = if me.x < center { 1 } else { -1 };
        let edge = if toward > 0 { stage.left } else { stage.right };
        // How far outside the near edge it is (negative once over the stage).
        let outside = (edge - me.x) * toward as i32;
        let height = me.y - stage.y;
        let drift = if style.ledge && outside > Fx::ZERO && outside < Fx::int(3) { 0 } else { toward * 100 };
        let mut input = Input { stick_x: drift, ..Input::default() };
        let falling = me.state == State::Air && me.vy + me.kb_y <= Fx::ZERO;
        let dodge_in = match style.air_dodge {
            AirDodgeIn::No => false,
            AirDodgeIn::Near => outside > Fx::ZERO && outside < AIR_DODGE_REACH && height < Fx::int(4) && height > -AIR_DODGE_REACH,
            AirDodgeIn::Far(_) => outside > AIR_DODGE_REACH,
        };
        if dodge_in && falling && !me.air_dodge_used && !self.prev.held(Input::SHIELD) {
            let up = !matches!(style.air_dodge, AirDodgeIn::Far(false));
            return if up {
                Input { stick_x: toward * DIAGONAL, stick_y: DIAGONAL, buttons: Input::SHIELD }
            } else {
                Input { stick_x: toward * 100, stick_y: 0, buttons: Input::SHIELD }
            };
        }
        if falling && !self.prev.held(Input::JUMP) && !self.prev.held(Input::SPECIAL) {
            if me.air_jumps_left > 0 && height < Fx::int(style.jump_at) {
                input.buttons |= Input::JUMP;
            } else if me.air_jumps_left == 0 && height < Fx::int(style.special_at) {
                // Mostly up, so it reads as up special rather than side.
                input = Input { stick_x: toward * 40, stick_y: 100, buttons: Input::SPECIAL };
            }
        }
        input
    }

    /// xorshift32: uniform enough for picking plans.
    fn roll(&mut self, n: u32) -> u32 {
        self.rng ^= self.rng << 13;
        self.rng ^= self.rng >> 17;
        self.rng ^= self.rng << 5;
        self.rng % n
    }

    fn chance(&mut self, percent: u32) -> bool {
        self.roll(100) < percent
    }
}

/// Random spread added to scores, so close options take turns.
const NOISE: u32 = 60;

fn dir_of(d: Fx) -> i8 {
    if d < Fx::ZERO { -1 } else { 1 }
}

/// Offstage, or hanging from the ledge: the edge-guarding cases.
fn offstage(f: &Fighter, main: &Platform) -> bool {
    f.state == State::LedgeHang || (!f.grounded() && (!main.contains_x(f.x) || f.y < main.y))
}

/// Open to a punish: landing, shield broken or being let go, helpless, in a move's or a
/// dodge's end lag, or already in hitstun.
fn vulnerable(t: &Fighter) -> bool {
    match t.state {
        State::Landing { .. } | State::ShieldBreak { .. } | State::ShieldDrop { .. } | State::Hitstun { .. } | State::SpecialFall => true,
        State::Dodge { kind, frame } => frame > kind.data().intangible.1,
        State::Attack { mv, frame, .. } => {
            let data = mv.data();
            let last = data.hitboxes.iter().map(|h| h.last).chain(data.grabbox.as_ref().map(|g| g.last)).max().unwrap_or(0);
            frame > last && data.counter.is_none()
        }
        _ => false,
    }
}

/// A hit the CPU can see coming, for `Cpu::guard`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Threat {
    /// The target's attack, seen on this frame of it.
    Attack { mv: MoveId, frame: u16 },
    /// A projectile, by the world frame it expires on (the same every frame of its flight).
    Shot(u32),
}

impl Threat {
    /// Whether `self` is the same attack or projectile as `seen`, one frame or more on.
    fn same(self, seen: Option<Threat>) -> bool {
        match (self, seen) {
            (Threat::Attack { mv, frame }, Some(Threat::Attack { mv: m, frame: f })) => mv == m && frame >= f,
            (Threat::Shot(a), Some(Threat::Shot(b))) => a == b,
            _ => false,
        }
    }
}

/// What the CPU can react to: the target's attack once it has seen it long enough
/// (`seen`: its level's `react` frames; close, with hitboxes, a grab box or a projectile
/// still to come), or a projectile about to arrive. Returns it and who threw it.
fn threat(player: usize, me: &Fighter, target: Option<&Fighter>, world: &World, seen: bool) -> Option<(Threat, usize)> {
    if let Some(t) = target
        && let State::Attack { mv, frame, .. } = t.state
        && seen
        && threatening(t, me)
        && let Some(i) = world.fighters.iter().position(|f| std::ptr::eq(f, t))
    {
        return Some((Threat::Attack { mv, frame }, i));
    }
    let (_, p) = incoming(me, player, world)?;
    Some((Threat::Shot(world.frame + u32::from(p.frames_left)), p.owner))
}

/// Whether `t`'s attack can still hurt `me`: hitboxes, a grab box or a projectile still
/// to come, within `THREAT_RANGE`.
fn threatening(t: &Fighter, me: &Fighter) -> bool {
    let State::Attack { mv, frame, .. } = t.state else { return false };
    if (t.x - me.x).abs() >= THREAT_RANGE || (t.y - me.y).abs() >= THREAT_RANGE {
        return false;
    }
    let d = mv.data();
    let last = d.hitboxes.iter().map(|h| h.last).chain(d.grabbox.as_ref().map(|g| g.last)).chain(d.projectile.as_ref().map(|p| p.frame)).max().unwrap_or(0);
    frame <= last
}

/// Free to act: standing, crouching, airborne or holding shield (out-of-shield options).
fn actionable(f: &Fighter) -> bool {
    matches!(f.state, State::Ground | State::Crouch | State::Air | State::Shield)
}

/// How far to play a guard out: until the attacker's move is over (so a guard's punish
/// window shows), at least long enough to see a roll end, within `GUARD_FRAMES`.
fn guard_frames(opp: &Fighter) -> u16 {
    let left = match opp.state {
        State::Attack { mv, frame, .. } => mv.data().total_frames.saturating_sub(frame),
        _ => 0,
    };
    (left + u16::from(opp.hitlag) + 4).clamp(GUARD_MIN_FRAMES, GUARD_FRAMES)
}

/// The input that starts guard `g`.
fn guard_input(g: Guard) -> Input {
    let (stick_x, stick_y, buttons) = match g {
        Guard::Shield => (0, 0, Input::SHIELD),
        Guard::Spot => (0, -100, Input::SHIELD),
        Guard::Roll(dir) => (dir * 100, 0, Input::SHIELD),
        Guard::AirDodge(x, y) => (x, y, Input::SHIELD),
        Guard::Counter => (0, -TILT, Input::SPECIAL),
    };
    Input { stick_x, stick_y, buttons }
}

/// How good guard `g` played out: `None` if it got hit (or broke its shield, or, while
/// recovering, didn't make it back); otherwise its base score, plus or minus the frames
/// it is free before the attacker is, plus a landed counter.
fn guard_score(g: Guard, out: &Outcome, main: &Platform, recovering: bool, from_x: Fx) -> Option<i32> {
    if out.hit.is_some() || out.ko || (recovering && out.safe.is_none()) {
        return None;
    }
    let mut s = match g {
        Guard::Shield if out.shield < SHIELD_LOW => return None,
        Guard::Shield => SHIELD_SCORE,
        Guard::Counter => COUNTER_SCORE,
        Guard::Spot => SPOT_DODGE_SCORE,
        Guard::Roll(_) => ROLL_SCORE,
        Guard::AirDodge(..) => AIR_DODGE_SCORE,
    };
    let to_ledge = |x: Fx| (x - main.left).min(main.right - x);
    if let Guard::Roll(_) = g {
        if to_ledge(out.x) < ROLL_LEDGE_MARGIN {
            s -= LEDGE_ROLL_PENALTY;
        } else if to_ledge(from_x) < CORNER && to_ledge(out.x) >= to_ledge(from_x) + CORNER_ESCAPE {
            // Out of a corner, toward the middle.
            s += CORNER_BONUS;
        }
    }
    let advantage = (i32::from(out.opp_free) - i32::from(out.free)).clamp(-GUARD_ADVANTAGE, GUARD_ADVANTAGE);
    // Frames to spare are only worth something within reach of the attacker (a shield
    // pushed out of range has nothing to do with them); frames short always count.
    let in_reach = out.gap <= PUNISH_RANGE;
    let usable = if in_reach { advantage } else { advantage.min(0) };
    // Free in time, and close enough, to hit back before the attacker can act.
    let punish = in_reach && advantage >= PUNISH_FRAMES;
    Some(s + usable * GUARD_PER_FRAME + if punish { PUNISH_BONUS } else { 0 } + if out.landed.is_some() { COUNTER_HIT_BONUS } else { 0 })
}

/// The DI stick for `launch` (one of eight directions at full tilt, or none) whose
/// trajectory scores best by `di_score`: survival DI near a blast zone, recoverable
/// launches and escaping the attacker otherwise.
fn best_di(me: &Fighter, launch: Trajectory, attacker: Option<&Fighter>, stage: &Stage, main: &Platform) -> Input {
    let hitstun = match me.state {
        State::Hitstun { frames_left } => frames_left,
        _ => 0,
    };
    let from = attacker.map(|a| (a.x, a.y));
    let mut best = (i32::MIN, Input::default());
    for d in 0..=8 {
        let input = if d == 8 {
            Input::default()
        } else {
            let axis = |v: Fx| (v * Fx::int(100)).floor_to_int().clamp(-100, 100) as i8;
            Input { stick_x: axis(cos_deg(d * 45)), stick_y: axis(sin_deg(d * 45)), buttons: 0 }
        };
        let (sx, sy) = input.stick();
        let angle = di_angle(launch.angle, sx, sy);
        let s = di_score(me, Trajectory { angle, ..launch }, hitstun, from, stage, main);
        if s > best.0 {
            best = (s, input);
        }
    }
    best.1
}

/// Follows `launch` from `me` (knockback decay and gravity, as `Fighter::take_hit` and
/// physics do) and scores it: room left before the nearest blast zone (up to `DI_ROOM`;
/// a KO scores far below anything else), how far offstage it ends, and how far from the
/// attacker (at `from`) it is when hitstun ends.
fn di_score(me: &Fighter, launch: Trajectory, hitstun: u16, from: Option<(Fx, Fx)>, stage: &Stage, main: &Platform) -> i32 {
    let p = me.params;
    let (cos, sin) = (cos_deg(launch.angle), sin_deg(launch.angle));
    let (mut kbx, mut kby) = (launch.speed * cos, launch.speed * sin);
    let (decay_x, decay_y) = ((KB_DECAY * cos).abs(), (KB_DECAY * sin).abs());
    let (mut x, mut y, mut vy) = (me.x, me.y, Fx::ZERO);
    let mut room = DI_ROOM;
    let mut escape = None;
    for f in 1..=LAUNCH_FRAMES {
        vy = (vy - p.gravity).max(-p.max_fall);
        kbx = kbx.approach(Fx::ZERO, decay_x);
        kby = kby.approach(Fx::ZERO, decay_y);
        let prev_y = y;
        x += kbx;
        y += vy + kby;
        room = room.min(x - stage.blast_left).min(stage.blast_right - x).min(stage.blast_top - y).min(y - stage.blast_bottom);
        if room <= Fx::ZERO {
            // A KO: a later one is barely better.
            return DI_KO + f as i32;
        }
        let distance = || from.map_or(Fx::ZERO, |(ax, ay)| Fx::hypot(x - ax, y - ay).min(DI_ESCAPE));
        if f == u32::from(hitstun) {
            escape = Some(distance());
        }
        let landed = vy + kby <= Fx::ZERO && stage.platforms.iter().any(|pl| prev_y >= pl.y && y <= pl.y && pl.contains_x(x));
        if landed || (f >= u32::from(hitstun) && kbx == Fx::ZERO && kby == Fx::ZERO) {
            escape.get_or_insert_with(distance);
            break;
        }
    }
    let off = (main.left - x).max(x - main.right).max(main.y - y).max(Fx::ZERO);
    room.floor_to_int() * DI_PER_ROOM - off.floor_to_int() * DI_PER_OFFSTAGE + escape.unwrap_or(Fx::ZERO).floor_to_int() * DI_PER_ESCAPE
}

/// An opponent's projectile about to hit: frames until it does, within `INCOMING_FRAMES`.
fn incoming<'a>(me: &Fighter, player: usize, world: &'a World) -> Option<(u16, &'a Projectile)> {
    let s = &world.stage;
    world.projectiles.iter().filter(|p| p.owner != player).find_map(|p| {
        let data = p.data();
        let radius = data.explosion.map_or(p.radius(), |e| e.radius.max(p.radius()));
        let (mut x, mut y, mut vy) = (p.x, p.y, p.vy);
        for k in 1..=INCOMING_FRAMES.min(p.frames_left) {
            let was_y = y;
            vy -= data.gravity;
            x += p.vx;
            y += vy;
            let landed = s.platforms.iter().find(|pl| vy < Fx::ZERO && was_y >= pl.y && y < pl.y && pl.contains_x(x));
            if let Some(pl) = landed {
                // Only a blast or shatter hurts once it lands.
                let burst = data.explosion.map(|e| e.radius).or(p.mv.data().shatter.map(|b| b.radius));
                return burst.filter(|&r| overlaps(me, me.x, me.y, x, pl.y, r)).map(|_| (k, p));
            }
            if overlaps(me, me.x, me.y, x, y, radius) {
                return Some((k, p));
            }
        }
        None
    })
}

/// How far in front of its feet this fighter's jab and forward tilt reach: the range it
/// walks in to.
fn reach(me: &Fighter) -> Fx {
    let m = me.character.moveset();
    [m.jab, m.ftilt].iter().flat_map(|mv| mv.data().hitboxes.iter()).map(|h| h.x + h.radius).max().unwrap_or(Fx::int(10))
}

/// Whether a circle overlaps `t`'s capsule hurtbox with its feet at (x, y).
fn overlaps(t: &Fighter, x: Fx, y: Fx, cx: Fx, cy: Fx, r: Fx) -> bool {
    let p = t.params;
    let (bottom, top) = (y + p.radius, y + p.height - p.radius);
    let dx = (cx - x).raw() as i64;
    let dy = (cy - cy.clamp(bottom, top)).raw() as i64;
    let reach = (r + p.radius).raw() as i64;
    dx * dx + dy * dy <= reach * reach
}

/// Where `t`'s feet will be over the next `HORIZON` frames if it does nothing new:
/// momentum, knockback decay, gravity and landing on platforms. Hanging, held and
/// getup states stay put.
fn predict(t: &Fighter, stage: &Stage) -> Path {
    let mut path = [(t.x, t.y); HORIZON + 1];
    if matches!(
        t.state,
        State::LedgeHang | State::LedgeClimb { .. } | State::LedgeRoll { .. } | State::LedgeAttack { .. } | State::Held { .. }
    ) {
        return path;
    }
    let p = t.params;
    let (mut x, mut y, mut vx, mut vy, mut kbx, mut kby) = (t.x, t.y, t.vx, t.vy, t.kb_x, t.kb_y);
    let kb = Fx::hypot(kbx, kby);
    let (decay_x, decay_y) = if kb > Fx::ZERO { (KB_DECAY * kbx.abs() / kb, KB_DECAY * kby.abs() / kb) } else { (Fx::ZERO, Fx::ZERO) };
    let mut grounded = t.grounded_on;
    let mut frozen = t.hitlag;
    for point in path.iter_mut().skip(1) {
        if frozen > 0 {
            frozen -= 1;
            *point = (x, y);
            continue;
        }
        match grounded {
            Some(_) => vx = vx.approach(Fx::ZERO, p.traction),
            None => vy = if t.fast_falling { -p.fast_fall } else { (vy - p.gravity).max(-p.max_fall) },
        }
        kbx = kbx.approach(Fx::ZERO, decay_x);
        kby = kby.approach(Fx::ZERO, decay_y);
        let prev_y = y;
        x += vx + kbx;
        match grounded {
            Some(i) if stage.platforms[i].contains_x(x) => {}
            Some(_) => grounded = None,
            None => {
                y += vy + kby;
                if vy + kby <= Fx::ZERO
                    && let Some(i) = stage.platforms.iter().position(|pl| prev_y >= pl.y && y <= pl.y && pl.contains_x(x))
                {
                    (y, vy, kby, grounded) = (stage.platforms[i].y, Fx::ZERO, Fx::ZERO, Some(i));
                }
            }
        }
        *point = (x, y);
    }
    path
}

/// `slot`'s move from where the CPU stands (or flies), aimed at the target: the best
/// facing that connects, scored, or `None`.
fn evaluate(c: &Ctx, slot: Slot) -> Option<Choice> {
    let me = c.me;
    let moves = me.character.moveset();
    let mv = slot.move_id(moves);
    let data = mv.data();
    if data.counter.is_some() || (slot == Slot::DashAttack && !running(me)) || (data.projectile.is_some() && !c.shots) {
        return None;
    }
    let toward = dir_of(c.t.x - me.x);
    let airborne = !me.grounded();
    // (facing, frames of delay before the move starts)
    let facings: [(i32, u16); 2] = if airborne || slot == Slot::DashAttack {
        [(me.facing, 0), (0, 0)]
    } else if slot.turns() {
        [(toward as i32, 0), (0, 0)]
    } else if me.facing == toward as i32 {
        [(me.facing, 0), (0, 0)]
    } else {
        [(me.facing, 0), (toward as i32, 1)]
    };
    let mut best: Option<Choice> = None;
    for (facing, delay) in facings {
        if facing == 0 {
            continue;
        }
        let Some(hit) = simulate(c, data, facing, delay) else { continue };
        let score = score(c, data, &hit);
        let dir = if slot == Slot::DashAttack { me.vx.signum() as i8 } else { facing as i8 };
        if best.is_none_or(|b| score > b.score) {
            best = Some(Choice { slot, dir, score, hit });
        }
    }
    best
}

fn running(me: &Fighter) -> bool {
    me.state == State::Ground && me.vx.abs() > me.params.walk_speed
}

/// Plays `data` forward from the CPU's position, started after `delay` frames facing
/// `facing`: its scripted motion, traction on the ground, gravity in the air and an
/// aerial's landing, checking its hitboxes, grab box and projectile against the
/// predicted path. The first hit, if the move also leaves the fighter over the main
/// stage (a lunge that carries it off isn't worth it).
fn simulate(c: &Ctx, data: &MoveData, facing: i32, delay: u16) -> Option<Hit> {
    let (me, t) = (c.me, c.t);
    let p = me.params;
    let last_active = data
        .hitboxes
        .iter()
        .map(|h| h.last)
        .chain(data.grabbox.as_ref().map(|g| g.last))
        .chain(data.projectile.as_ref().map(|pr| pr.frame))
        .max()?;
    // A move that never moves the fighter is done once its last hitbox is.
    let end = if data.motion.is_empty() && me.grounded() { last_active } else { data.total_frames };
    // Quick reject: nowhere near.
    if data.projectile.is_none() && data.motion.is_empty() {
        let extent = data.hitboxes.iter().map(|h| h.x.abs() + h.radius).chain(data.grabbox.as_ref().map(|g| g.x.abs() + g.radius)).max()?;
        let slack = extent + t.params.radius + me.vx.abs() * Fx::int(last_active as i32) + Fx::int(2);
        let near = c.path.iter().take(usize::from(last_active + delay) + 1).any(|&(x, _)| (x - me.x).abs() <= slack);
        if !near {
            return None;
        }
    }
    let (mut x, mut y, mut vx, mut vy) = (me.x, me.y, me.vx, me.vy);
    let mut grounded = me.grounded();
    let mut hit = None;
    for f in 1..=end.min(90) {
        if grounded {
            vx = vx.approach(Fx::ZERO, p.traction);
        }
        let mut scripted_y = false;
        for m in data.motion.iter().filter(|m| (m.first..=m.last).contains(&f)) {
            if let Some(v) = m.vx {
                vx = v * facing;
            }
            if let Some(v) = m.vy {
                vy = v;
                scripted_y = true;
                if v > Fx::ZERO {
                    grounded = false;
                }
            }
        }
        if !grounded && !scripted_y {
            vy = (vy - p.gravity).max(-p.max_fall);
        }
        let prev_y = y;
        x += vx;
        let mut landed = false;
        if grounded {
            grounded = c.stage.platforms.iter().any(|pl| pl.y == y && pl.contains_x(x));
        } else {
            y += vy;
            if vy <= Fx::ZERO && let Some(pl) = c.stage.platforms.iter().find(|pl| prev_y >= pl.y && y <= pl.y && pl.contains_x(x)) {
                (y, vy, grounded, landed) = (pl.y, Fx::ZERO, true, true);
            }
        }
        if landed && !matches!(data.landing, Landing::Continue) {
            break;
        }
        if hit.is_none() {
            hit = strike_at(c, data, f, delay, facing, x, y);
            if hit.is_some() && end == last_active {
                return hit;
            }
        }
    }
    // Aerials are thrown wherever they're needed (offstage too: recovering is `recover`'s job).
    let safe = !me.grounded() || (c.main.contains_x(x) && y >= c.main.y);
    if safe { hit } else { None }
}

/// What `data` hits on its frame `f` with the fighter's feet at (x, y).
fn strike_at(c: &Ctx, data: &MoveData, f: u16, delay: u16, facing: i32, x: Fx, y: Fx) -> Option<Hit> {
    let t = c.t;
    let now = f + delay;
    let (tx, ty) = c.path[usize::from(now).min(HORIZON)];
    let open = now > t.intangible;
    let mk = |damage, angle, base_kb, kb_growth, dir, grab, projectile| Hit {
        frame: now,
        start: now,
        damage,
        angle,
        base_kb,
        kb_growth,
        dir,
        x: tx,
        y: ty,
        grab,
        projectile,
    };
    if open && let Some(h) = data.hitboxes.iter().filter(|h| (h.first..=h.last).contains(&f)).find(|h| overlaps(t, tx, ty, x + h.x * facing, y + h.y, h.radius)) {
        return Some(mk(h.damage, h.angle, h.base_kb, h.kb_growth, facing, false, false));
    }
    if open
        && let Some(g) = &data.grabbox
        && (g.first..=g.last).contains(&f)
        && overlaps(t, tx, ty, x + g.x * facing, y + g.y, g.radius)
    {
        return Some(mk(0, 0, 0, 0, facing, true, false));
    }
    match &data.projectile {
        Some(pr) if pr.frame == f => projectile_hit(c, data, pr, x, y, facing, now),
        _ => None,
    }
}

/// Follows a projectile fired at frame `start` from feet at (x, y) and returns its
/// hit on the target: direct, or the blast / shatter where a lobbed one lands.
fn projectile_hit(c: &Ctx, data: &MoveData, pr: &ProjectileData, x: Fx, y: Fx, facing: i32, start: u16) -> Option<Hit> {
    let t = c.t;
    let s = c.stage;
    let (mut px, mut py) = (x + pr.x * facing, y + pr.y);
    let (vx, mut vy) = (pr.speed * facing, pr.vy);
    for k in 0..=pr.lifetime {
        let now = start + k;
        if k > 0 {
            let was_y = py;
            vy -= pr.gravity;
            px += vx;
            py += vy;
            if let Some(pl) = s.platforms.iter().find(|pl| vy < Fx::ZERO && was_y >= pl.y && py < pl.y && pl.contains_x(px)) {
                let (tx, ty) = c.path[usize::from(now).min(HORIZON)];
                let burst = pr
                    .explosion
                    .map(|e| (e.radius, e.damage, e.angle, e.base_kb, e.kb_growth))
                    .or(data.shatter.map(|b| (b.radius, b.damage, b.angle, b.base_kb, b.kb_growth)));
                return burst.filter(|b| now > t.intangible && overlaps(t, tx, ty, px, pl.y, b.0)).map(|(_, damage, angle, base_kb, kb_growth)| Hit {
                    frame: now,
                    start,
                    damage,
                    angle,
                    base_kb,
                    kb_growth,
                    dir: if tx < px { -1 } else { 1 },
                    x: tx,
                    y: ty,
                    grab: false,
                    projectile: true,
                });
            }
            if px < s.blast_left || px > s.blast_right || py < s.blast_bottom {
                return None;
            }
        }
        let (tx, ty) = c.path[usize::from(now).min(HORIZON)];
        if now > t.intangible && overlaps(t, tx, ty, px, py, pr.radius) {
            let (damage, angle, base_kb, kb_growth) = match pr.explosion {
                Some(e) => (e.damage, e.angle, e.base_kb, e.kb_growth),
                None => (pr.damage, pr.angle, pr.base_kb, pr.kb_growth),
            };
            return Some(Hit { frame: now, start, damage, angle, base_kb, kb_growth, dir: facing, x: tx, y: ty, grab: false, projectile: true });
        }
    }
    None
}

/// How good a hit looks: damage, quick to come out, little end lag, and a launch that
/// KOs or leaves the opponent offstage. Grabs are worth their best throw.
fn score(c: &Ctx, data: &MoveData, hit: &Hit) -> i32 {
    let (me, t) = (c.me, c.t);
    let endlag = i32::from(data.total_frames) - i32::from(hit.frame.min(data.total_frames));
    let endlag = if hit.projectile { endlag / 2 } else { endlag };
    // Slow moves are easy to see coming: past a few frames each one costs more.
    let start = i32::from(hit.start);
    let travel = i32::from(hit.frame - hit.start);
    let mut s = -start * PER_STARTUP_FRAME - (start - QUICK_FRAMES).max(0) * PER_SLOW_FRAME - travel - endlag * PER_ENDLAG_FRAME;
    if hit.grab {
        let throws = Throw::ALL.map(|th| throw_score(me, t, c.stage, c.main, th.move_id(me.character.moveset())));
        s += throws.into_iter().max().unwrap_or(0);
        if t.shielding() {
            s += GRAB_SHIELD_BONUS;
        }
        return s;
    }
    let damage = me.params.dealt_damage(hit.damage);
    s += damage * PER_DAMAGE;
    if data.combo.is_some() {
        s += COMBO_BONUS;
    }
    if t.shielding() && !hit.projectile {
        return s / 4 - HIT_SHIELD_PENALTY;
    }
    s + match launch(t, me.params, c.stage, c.main, damage, hit.angle, hit.base_kb, hit.kb_growth, hit.dir, hit.x, hit.y) {
        Launch::Ko => KO_BONUS,
        Launch::Offstage(past) => offstage_bonus(past),
        Launch::Stays => 0,
    }
}

/// Leaving the opponent offstage is worth more the farther out it ends up.
fn offstage_bonus(past: Fx) -> i32 {
    OFFSTAGE_BONUS + past.floor_to_int().min(KO_BONUS / 4)
}

/// A throw's worth from where the holder stands: damage, then a KO or an offstage launch.
fn throw_score(me: &Fighter, victim: &Fighter, stage: &Stage, main: &Platform, mv: MoveId) -> i32 {
    let data = mv.data();
    let mut damage = 0;
    for th in data.throws {
        damage += me.params.dealt_damage(th.damage);
        if th.release {
            let x = me.x + th.x * me.facing;
            let bonus = match launch(victim, me.params, stage, main, damage, th.angle, th.base_kb, th.kb_growth, me.facing, x, me.y) {
                Launch::Ko => KO_BONUS,
                Launch::Offstage(past) => offstage_bonus(past),
                Launch::Stays => {
                    // Still in hitstun, and not far, when the thrower can act: room for
                    // a follow-up.
                    let kb = me.params.dealt_knockback(knockback((victim.percent + damage).min(999), damage, victim.params.weight, th.base_kb, th.kb_growth));
                    let speed = kb * LAUNCH_SPEED;
                    let carry = speed * speed / (KB_DECAY * 2);
                    let hitstun = (kb * HITSTUN_PER_KB).floor_to_int();
                    let advantage = hitstun - i32::from(data.total_frames - th.frame);
                    if carry < FOLLOW_UP_RANGE { advantage.clamp(0, MAX_ADVANTAGE) * PER_ADVANTAGE_FRAME } else { 0 }
                }
            };
            return damage * PER_DAMAGE + bonus;
        }
    }
    damage * PER_DAMAGE
}

/// Follows the launch of a hit on `t` (its knockback from the formula, gravity, and
/// knockback decay) to see whether it carries `t` past a blast zone, or leaves it
/// offstage once the knockback is spent.
#[allow(clippy::too_many_arguments)]
fn launch(t: &Fighter, attacker: &FighterParams, stage: &Stage, main: &Platform, damage: i32, angle: i32, base_kb: i32, kb_growth: i32, dir: i32, x: Fx, y: Fx) -> Launch {
    let p = t.params;
    let kb = attacker.dealt_knockback(knockback((t.percent + damage).min(999), damage, p.weight, base_kb, kb_growth));
    let (cos, sin) = (cos_deg(angle), sin_deg(angle));
    let speed = kb * LAUNCH_SPEED;
    let (mut kbx, mut kby) = (speed * cos * dir, speed * sin);
    let (decay_x, decay_y) = ((KB_DECAY * cos).abs(), (KB_DECAY * sin).abs());
    if t.grounded() && (kb < GROUNDED_KB_THRESHOLD || kby <= Fx::ZERO) {
        kby = Fx::ZERO;
    }
    let (mut x, mut y, mut vy) = (x, y, Fx::ZERO);
    for _ in 0..LAUNCH_FRAMES {
        vy = (vy - p.gravity).max(-p.max_fall);
        kbx = kbx.approach(Fx::ZERO, decay_x);
        kby = kby.approach(Fx::ZERO, decay_y);
        let prev_y = y;
        x += kbx;
        y += vy + kby;
        if x < stage.blast_left || x > stage.blast_right || y > stage.blast_top || y < stage.blast_bottom {
            return Launch::Ko;
        }
        if vy + kby <= Fx::ZERO && main.contains_x(x) && prev_y >= main.y && y <= main.y {
            return Launch::Stays;
        }
        if kbx == Fx::ZERO && kby == Fx::ZERO {
            break;
        }
    }
    if main.contains_x(x) && y >= main.y {
        Launch::Stays
    } else {
        Launch::Offstage((main.left - x).max(x - main.right).max(main.y - y).max(Fx::ZERO))
    }
}
