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

use crate::character::Moveset;
use crate::fighter::{Fighter, FighterParams, GROUNDED_KB_THRESHOLD, HITSTUN_PER_KB, KB_DECAY, LAUNCH_SPEED, State, knockback};
use crate::fixed::{Fx, cos_deg, sin_deg};
use crate::input::Input;
use crate::moves::{Landing, MoveData, MoveId, ProjectileData};
use crate::stage::{Platform, Stage};
use crate::world::World;

/// How a CPU plays. Lower `reaction_frames` and higher chances make it harder.
#[derive(Debug, PartialEq, Eq, Hash)]
pub struct CpuLevel {
    /// The CPU commits to a plan for this many frames before looking again.
    pub reaction_frames: u8,
    /// Percent chance, when out of range, to walk in rather than stand around.
    pub approach_chance: u32,
    /// Percent chance, when a move would connect, to throw it rather than wait or back off.
    pub attack_chance: u32,
    /// Percent of neutral openings it takes with a grab instead of a strike.
    pub grab_chance: u32,
    /// Percent chance to put up shield when an opponent starts an attack nearby.
    pub shield_chance: u32,
    /// Percent chance to pick the best-scoring move (kill power, speed, end lag) rather
    /// than any move that connects; also how often it times aerials to connect instead
    /// of swinging on a fixed frame, picks the best throw, runs, counters and mixes up
    /// its ledge getups.
    pub judgement: u32,
    /// Percent chance, with the opponent offstage or on the ledge, to go and cover the
    /// ledge (ground moves and projectiles at the recovering opponent) rather than wait.
    pub edge_guard: u32,
    /// Percent chance, edge-guarding, to jump off after the opponent with an aerial
    /// (only while it keeps a jump to come back with).
    pub offstage: u32,
}

#[allow(clippy::too_many_arguments)]
const fn level(
    reaction_frames: u8,
    approach_chance: u32,
    attack_chance: u32,
    grab_chance: u32,
    shield_chance: u32,
    judgement: u32,
    edge_guard: u32,
    offstage: u32,
) -> CpuLevel {
    CpuLevel { reaction_frames, approach_chance, attack_chance, grab_chance, shield_chance, judgement, edge_guard, offstage }
}

/// Melee-style levels 1 to 9, from barely fighting back to reacting within a few
/// frames. Levels 1-3 never edge-guard and mostly swing at whatever connects; from
/// level 4 they cover the ledge, and from level 7 they jump off after a recovering
/// opponent. Every level walks or runs rather than dashing, and recovers.
static LEVELS: [CpuLevel; 9] = [
    level(40, 40, 15, 10, 0, 0, 0, 0),
    level(32, 55, 25, 15, 5, 10, 0, 0),
    CpuLevel::EASY,
    level(20, 75, 45, 20, 25, 40, 25, 0),
    level(16, 80, 55, 25, 35, 50, 40, 0),
    level(14, 85, 62, 25, 45, 60, 55, 0),
    level(12, 90, 70, 30, 55, 70, 70, 20),
    level(10, 95, 78, 30, 65, 85, 85, 35),
    level(8, 100, 85, 30, 75, 100, 95, 50),
];

impl CpuLevel {
    /// Level 3. Slow to react, swings at a fraction of its openings, never edge-guards.
    /// Still recovers, so it doesn't throw stocks away on its own.
    pub const EASY: CpuLevel = level(24, 70, 35, 20, 15, 25, 0, 0);
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
    Grab,
}

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
    /// Hold shield for the plan's duration.
    Shield,
    /// A hop (`full` or short) drifting toward `dir`, then the aerial that will connect,
    /// picked frame by frame (or, with `swing_at`, a nair/fair on that frame: lower
    /// levels). `offstage`: jumping off the ledge after a recovering opponent, ended by
    /// `Cpu::offstage_ok`.
    Hop { full: bool, dir: i8, offstage: bool, swing_at: Option<u8> },
    /// Full hop plus double jump, drifting toward `goal` (climbing to a platform).
    Jump { goal: Fx },
    DropDown,
}

/// Below the run threshold, so the CPU walks.
const WALK: i8 = 60;
/// Past the tilt threshold but short of a smash flick, so attacks come out as tilts.
const TILT: i8 = 60;
/// Just past the deadzone: turns a standing fighter without walking it anywhere much.
const TURN: i8 = 30;
const SHIELD_FRAMES: u8 = 20;
/// Being thrown or hit from this close counts as "nearby".
const THREAT_RANGE: Fx = Fx::int(20);
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
/// Shields projectiles that would hit within this many frames.
const INCOMING_FRAMES: u16 = 8;
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
}

impl Cpu {
    pub fn new(player: usize, level: &'static CpuLevel) -> Cpu {
        let rng = 0x9E37_79B9 ^ (player as u32 + 1).wrapping_mul(0x85EB_CA6B);
        Cpu { player, level, rng: rng.max(1), plan: Plan::Wait, plan_age: 0, swung: false, grab_plan: None, last_shot: 0, prev: Input::default() }
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
        let Some(mi) = world.stage.platforms.iter().position(|p| !p.soft) else { return Input::default() };
        let main = &world.stage.platforms[mi];
        let target = self.target(world);
        match me.state {
            // Mash: a fresh press every other frame.
            State::Held { .. } => return if self.prev.buttons == 0 { Input { buttons: Input::ATTACK, ..Input::default() } } else { Input::default() },
            State::Holding { .. } => return self.hold(me, world),
            State::Hitstun { .. } | State::ShieldBreak { .. } | State::Respawning { .. } | State::Eliminated => return Input::default(),
            State::LedgeHang => return self.ledge_getup(me, target, main),
            _ => {}
        }
        if !me.grounded() && (me.x < main.left || me.x > main.right || me.y < main.y) && !self.offstage_ok(me, main) {
            return self.recover(me, main);
        }

        self.plan_age = self.plan_age.saturating_add(1);
        // Plans that take longer than a quick CPU's reaction time get to finish.
        let committed = match self.plan {
            Plan::Jump { .. } => !me.grounded(),
            Plan::Hop { .. } => !me.grounded() || self.plan_age <= me.params.jump_squat + 1,
            Plan::Shield => self.plan_age < SHIELD_FRAMES,
            Plan::Strike { slot, .. } => self.plan_age < 2 || (slot == Slot::Jab && matches!(me.state, State::Attack { .. })),
            _ => false,
        };
        let threat = target.and_then(|t| threat(me, t)).or_else(|| incoming(me, self.player, world));
        if let Some(startup) = threat
            && me.state == State::Ground
            && !matches!(self.plan, Plan::Shield)
        {
            if let Some(plan) = self.defend(me, startup) {
                self.plan = plan;
                self.plan_age = 0;
                self.swung = false;
            }
        } else if self.plan_age >= self.level.reaction_frames && !committed {
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

    /// Shield, or (judgement allowing) a counter whose window covers the attack's
    /// startup, against an attack starting nearby.
    fn defend(&mut self, me: &Fighter, startup: u16) -> Option<Plan> {
        if let Some(counter) = me.character.moveset().down_special.data().counter.as_ref()
            && (counter.first..=counter.last).contains(&startup)
            && self.chance(self.level.judgement / 3)
        {
            return Some(Plan::Strike { slot: Slot::DownSpecial, dir: me.facing as i8 });
        }
        self.chance(self.level.shield_chance).then_some(Plan::Shield)
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
            Plan::Shield if age < SHIELD_FRAMES => Input { buttons: Input::SHIELD, ..Input::default() },
            Plan::Shield => Input::default(),
            Plan::Hop { full, dir, swing_at, .. } => self.hop(me, target, stage, full, dir, swing_at),
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
    fn recover(&mut self, me: &Fighter, stage: &Platform) -> Input {
        self.plan = Plan::Wait;
        self.plan_age = 0;
        let center = (stage.left + stage.right) * Fx::ratio(1, 2);
        let toward: i8 = if me.x < center { 1 } else { -1 };
        let mut input = Input { stick_x: toward * 100, ..Input::default() };
        let falling_low = me.state == State::Air && me.vy + me.kb_y <= Fx::ZERO && me.y < stage.y + Fx::int(5);
        if falling_low && !self.prev.held(Input::JUMP) && !self.prev.held(Input::SPECIAL) {
            if me.air_jumps_left > 0 {
                input.buttons |= Input::JUMP;
            } else {
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

/// Open to a punish: landing, shield broken, in a move's end lag, or already in hitstun.
fn vulnerable(t: &Fighter) -> bool {
    match t.state {
        State::Landing { .. } | State::ShieldBreak { .. } | State::Hitstun { .. } => true,
        State::Attack { mv, frame, .. } => {
            let data = mv.data();
            let last = data.hitboxes.iter().map(|h| h.last).chain(data.grabbox.as_ref().map(|g| g.last)).max().unwrap_or(0);
            frame > last && data.counter.is_none()
        }
        _ => false,
    }
}

/// An attack starting nearby: frames until its first hitbox, if `t` just started one.
fn threat(me: &Fighter, t: &Fighter) -> Option<u16> {
    let State::Attack { mv, frame: 1, .. } = t.state else { return None };
    if (t.x - me.x).abs() >= THREAT_RANGE || (t.y - me.y).abs() >= THREAT_RANGE {
        return None;
    }
    let data = mv.data();
    let first = data.hitboxes.iter().map(|h| h.first).chain(data.grabbox.as_ref().map(|g| g.first)).min().unwrap_or(1);
    Some(first.saturating_sub(1))
}

/// An opponent's projectile about to hit: frames until it does, within `INCOMING_FRAMES`.
fn incoming(me: &Fighter, player: usize, world: &World) -> Option<u16> {
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
                return burst.filter(|&r| overlaps(me, me.x, me.y, x, pl.y, r)).map(|_| k);
            }
            if overlaps(me, me.x, me.y, x, y, radius) {
                return Some(k);
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
