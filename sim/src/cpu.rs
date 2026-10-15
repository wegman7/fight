//! Computer-controlled players. A [`Cpu`] looks at the [`World`] and returns the
//! same [`Input`] a controller would, so it can't bend any rules. It uses only
//! integer math and its own seeded RNG, so a match against it is deterministic
//! and replays/rollback only need to record the inputs it produced.

use crate::fighter::{Fighter, State};
use crate::fixed::Fx;
use crate::input::Input;
use crate::stage::Platform;
use crate::world::World;

/// How a CPU plays. Lower `reaction_frames` and higher chances make it harder.
#[derive(Debug, PartialEq, Eq, Hash)]
pub struct CpuLevel {
    /// The CPU commits to a plan for this many frames before looking again.
    pub reaction_frames: u8,
    /// Percent chance, when out of range, to walk in rather than stand around.
    pub approach_chance: u32,
    /// Percent chance, when in range, to swing rather than wait or back off.
    pub attack_chance: u32,
}

impl CpuLevel {
    /// Slow to react, walks instead of running, swings at a fraction of its
    /// openings and never punishes or edge-guards. Still recovers, so it
    /// doesn't throw stocks away on its own.
    pub const EASY: CpuLevel = CpuLevel { reaction_frames: 24, approach_chance: 70, attack_chance: 35 };
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Plan {
    Wait,
    /// Walk toward `goal` until within `within` of it.
    Approach { goal: Fx, within: Fx },
    Retreat,
    /// Press attack with the stick toward the target (ftilt), up (utilt) or neutral (jab).
    Attack { forward: bool, up: bool },
    HopAttack,
    /// Full hop plus double jump, drifting toward `goal`.
    Jump { goal: Fx },
    DropDown,
}

/// Below the run threshold, so the CPU walks.
const WALK: i8 = 60;
const ATTACK_RANGE: Fx = Fx::int(14);
/// Targets standing higher than this above the CPU are out of utilt range.
const UTILT_REACH: Fx = Fx::int(20);
/// Don't walk closer than this to the main stage's ledges.
const EDGE_MARGIN: Fx = Fx::int(10);
/// Full hop + double jump clears about 50 units; aim a bit lower than that.
const CLIMB_HEIGHT: Fx = Fx::int(45);
/// Close enough horizontally to jump for a platform instead of walking first.
const JUMP_RANGE: Fx = Fx::int(45);
const HOP_ATTACK_FRAME: u8 = 7;
const FULL_HOP_HOLD: u8 = 12;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Cpu {
    pub player: usize,
    level: &'static CpuLevel,
    rng: u32,
    plan: Plan,
    /// Frames since `plan` was chosen.
    plan_age: u8,
    prev: Input,
}

impl Cpu {
    pub fn new(player: usize, level: &'static CpuLevel) -> Cpu {
        let rng = 0x9E37_79B9 ^ (player as u32 + 1).wrapping_mul(0x85EB_CA6B);
        Cpu { player, level, rng: rng.max(1), plan: Plan::Wait, plan_age: 0, prev: Input::default() }
    }

    pub fn easy(player: usize) -> Cpu {
        Cpu::new(player, &CpuLevel::EASY)
    }

    /// The input to feed this CPU's fighter for the next [`World::step`].
    pub fn think(&mut self, world: &World) -> Input {
        let input = self.decide(world);
        self.prev = input;
        input
    }

    fn decide(&mut self, world: &World) -> Input {
        let me = &world.fighters[self.player];
        if !matches!(me.state, State::Ground | State::Air | State::JumpSquat { .. } | State::Landing { .. } | State::Attack { .. }) {
            return Input::default();
        }
        let Some(stage) = world.stage.platforms.iter().find(|p| !p.soft) else { return Input::default() };
        if !me.grounded() && (me.x < stage.left || me.x > stage.right || me.y < stage.y) {
            return self.recover(me, stage);
        }

        let target = world
            .fighters
            .iter()
            .enumerate()
            .filter(|&(i, f)| i != self.player && f.hittable())
            .map(|(_, f)| f)
            .min_by_key(|f| ((f.x - me.x).abs() + (f.y - me.y).abs()).raw());

        self.plan_age = self.plan_age.saturating_add(1);
        let mid_jump = matches!(self.plan, Plan::Jump { .. }) && !me.grounded();
        if self.plan_age >= self.level.reaction_frames && !mid_jump {
            self.plan = self.choose(me, target, world, stage);
            self.plan_age = 0;
        }
        self.execute(me, target, stage)
    }

    fn choose(&mut self, me: &Fighter, target: Option<&Fighter>, world: &World, stage: &Platform) -> Plan {
        let Some(target) = target else { return Plan::Wait };
        if !stage.contains_x(target.x) {
            return Plan::Wait;
        }
        let (dx, dy) = (target.x - me.x, target.y - me.y);
        if dy > UTILT_REACH {
            // Out of reach on a platform above: climb after it, one platform at a time.
            if !me.grounded() || !self.chance(self.level.approach_chance) {
                return Plan::Wait;
            }
            let goal = if dy <= CLIMB_HEIGHT {
                target.x
            } else {
                world
                    .stage
                    .platforms
                    .iter()
                    .filter(|p| p.y > me.y && p.y - me.y <= CLIMB_HEIGHT && p.y < target.y)
                    .map(|p| (p.left + p.right) * Fx::ratio(1, 2))
                    .min_by_key(|&center| (center - me.x).abs().raw())
                    .unwrap_or(target.x)
            };
            return if (goal - me.x).abs() > JUMP_RANGE {
                Plan::Approach { goal, within: JUMP_RANGE }
            } else {
                Plan::Jump { goal }
            };
        }
        let on_soft = me.grounded_on.is_some_and(|i| world.stage.platforms[i].soft);
        if me.grounded() && on_soft && dy < Fx::int(-15) && self.chance(50) {
            return Plan::DropDown;
        }
        if dx.abs() > ATTACK_RANGE {
            let approach = Plan::Approach { goal: target.x, within: ATTACK_RANGE };
            return if self.chance(self.level.approach_chance) { approach } else { Plan::Wait };
        }

        let roll = self.roll(100);
        let attack = self.level.attack_chance;
        if roll < attack {
            if dy > Fx::int(10) {
                Plan::Attack { forward: false, up: true }
            } else if me.facing != dx.signum() || roll < attack / 3 {
                Plan::Attack { forward: true, up: false }
            } else {
                Plan::Attack { forward: false, up: false }
            }
        } else if roll < attack + 10 {
            Plan::HopAttack
        } else if roll < attack + 30 {
            Plan::Retreat
        } else {
            Plan::Wait
        }
    }

    fn execute(&self, me: &Fighter, target: Option<&Fighter>, stage: &Platform) -> Input {
        let toward = target.map_or(0, |t| (t.x - me.x).signum()) as i8;
        let walk = |dir: i8| {
            let near_ledge = (dir > 0 && me.x > stage.right - EDGE_MARGIN) || (dir < 0 && me.x < stage.left + EDGE_MARGIN);
            Input { stick_x: if near_ledge { 0 } else { dir * WALK }, ..Input::default() }
        };
        let age = self.plan_age;
        match self.plan {
            Plan::Wait => Input::default(),
            Plan::Approach { goal, within } if (goal - me.x).abs() > within => walk((goal - me.x).signum() as i8),
            Plan::Approach { .. } => Input::default(),
            Plan::Retreat => walk(-toward),
            Plan::Attack { forward, up } if age == 0 => {
                Input { stick_x: if forward { toward * 100 } else { 0 }, stick_y: if up { 100 } else { 0 }, buttons: Input::ATTACK }
            }
            Plan::HopAttack if age == 0 => Input { buttons: Input::JUMP, ..Input::default() },
            Plan::HopAttack if age == HOP_ATTACK_FRAME => Input { stick_x: toward * 40, stick_y: 0, buttons: Input::ATTACK },
            Plan::HopAttack => Input { stick_x: toward * 40, ..Input::default() },
            Plan::Jump { goal } => {
                let drift = if (goal - me.x).abs() < Fx::int(3) { 0 } else { (goal - me.x).signum() as i8 * 100 };
                let double_jump = me.state == State::Air
                    && me.vy <= Fx::ZERO
                    && me.air_jumps_left > 0
                    && !self.prev.held(Input::JUMP);
                let jump = age < FULL_HOP_HOLD || double_jump;
                Input { stick_x: drift, stick_y: 0, buttons: if jump { Input::JUMP } else { 0 } }
            }
            Plan::DropDown if age == 0 => Input { stick_y: -100, ..Input::default() },
            _ => Input::default(),
        }
    }

    /// Drift back toward the stage and double-jump once falling below it.
    fn recover(&mut self, me: &Fighter, stage: &Platform) -> Input {
        self.plan = Plan::Wait;
        self.plan_age = 0;
        let center = (stage.left + stage.right) * Fx::ratio(1, 2);
        let mut input = Input { stick_x: if me.x < center { 100 } else { -100 }, ..Input::default() };
        let jump_ready = me.state == State::Air && me.air_jumps_left > 0 && !self.prev.held(Input::JUMP);
        if jump_ready && me.vy + me.kb_y <= Fx::ZERO && me.y < stage.y + Fx::int(5) {
            input.buttons |= Input::JUMP;
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
