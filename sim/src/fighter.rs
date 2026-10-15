use crate::fixed::{Fx, cos_deg, sin_deg};
use crate::input::Input;
use crate::moves::MoveId;
use crate::stage::Stage;

/// Per-character tuning. Units are Melee-style: stage units per frame.
#[derive(Debug, PartialEq, Eq, Hash)]
pub struct FighterParams {
    /// 100 = average; heavier characters take less knockback.
    pub weight: i32,
    pub walk_speed: Fx,
    pub run_speed: Fx,
    pub ground_accel: Fx,
    pub traction: Fx,
    pub air_speed: Fx,
    pub air_accel: Fx,
    pub air_friction: Fx,
    pub gravity: Fx,
    pub max_fall: Fx,
    pub fast_fall: Fx,
    pub jump_squat: u8,
    pub full_hop: Fx,
    pub short_hop: Fx,
    pub double_jump: Fx,
    pub air_jumps: u8,
    pub landing_lag: u8,
    /// Hurtbox: a vertical capsule standing on the fighter's feet.
    pub height: Fx,
    pub radius: Fx,
}

impl FighterParams {
    pub const DEFAULT: FighterParams = FighterParams {
        weight: 100,
        walk_speed: Fx::ratio(11, 10),
        run_speed: Fx::ratio(15, 10),
        ground_accel: Fx::ratio(2, 10),
        traction: Fx::ratio(8, 100),
        air_speed: Fx::ratio(86, 100),
        air_accel: Fx::ratio(45, 1000),
        air_friction: Fx::ratio(2, 100),
        gravity: Fx::ratio(95, 1000),
        max_fall: Fx::ratio(17, 10),
        fast_fall: Fx::ratio(23, 10),
        jump_squat: 4,
        full_hop: Fx::ratio(23, 10),
        short_hop: Fx::ratio(15, 10),
        double_jump: Fx::ratio(21, 10),
        air_jumps: 1,
        landing_lag: 4,
        height: Fx::int(12),
        radius: Fx::int(4),
    };
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum State {
    /// Standing, walking or running.
    Ground,
    JumpSquat { frame: u8 },
    Air,
    Landing { frames_left: u8 },
    /// `hit_mask` has bit `i` set once fighter `i` was hit by this swing.
    Attack { mv: MoveId, frame: u16, hit_mask: u8 },
    Hitstun { frames_left: u16 },
    Respawning { frames_left: u16 },
    Eliminated,
}

const DEADZONE: Fx = Fx::ratio(2, 10);
const RUN_THRESHOLD: Fx = Fx::ratio(8, 10);
const TILT_THRESHOLD: Fx = Fx::ratio(5, 10);
const DOWN_TAP: Fx = Fx::ratio(-65, 100);
/// Presses are remembered this many frames, so an input slightly early
/// (e.g. during landing lag) still comes out on the first actionable frame.
const BUFFER_FRAMES: u8 = 6;
const DROP_THROUGH_FRAMES: u8 = 10;
const RESPAWN_FRAMES: u16 = 60;
const RESPAWN_INTANGIBLE_FRAMES: u16 = 120;
/// Knockback units -> launch speed, and per-frame decay of that speed (Melee).
const LAUNCH_SPEED: Fx = Fx::ratio(3, 100);
const KB_DECAY: Fx = Fx::ratio(51, 1000);
const HITSTUN_PER_KB: Fx = Fx::ratio(4, 10);
/// Grounded targets hit with less knockback than this slide instead of lifting off.
const GROUNDED_KB_THRESHOLD: Fx = Fx::int(80);

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Fighter {
    pub params: &'static FighterParams,
    pub state: State,
    /// Position of the fighter's feet.
    pub x: Fx,
    pub y: Fx,
    /// Self-propelled velocity (movement, jumps, gravity).
    pub vx: Fx,
    pub vy: Fx,
    /// Knockback velocity, tracked separately and decaying toward zero.
    pub kb_x: Fx,
    pub kb_y: Fx,
    kb_decay_x: Fx,
    kb_decay_y: Fx,
    /// 1 = facing right, -1 = facing left.
    pub facing: i32,
    /// Index of the platform being stood on, if grounded.
    pub grounded_on: Option<usize>,
    pub air_jumps_left: u8,
    pub fast_falling: bool,
    pub hitlag: u8,
    pub intangible: u16,
    pub percent: i32,
    pub stocks: u8,
    drop_through: u8,
    jump_buffer: u8,
    attack_buffer: u8,
    prev_input: Input,
}

impl Fighter {
    pub fn new(params: &'static FighterParams, x: Fx, y: Fx, facing: i32, stage: &Stage, stocks: u8) -> Fighter {
        let grounded_on = stage.platform_under(x, y);
        Fighter {
            params,
            state: if grounded_on.is_some() { State::Ground } else { State::Air },
            x,
            y,
            vx: Fx::ZERO,
            vy: Fx::ZERO,
            kb_x: Fx::ZERO,
            kb_y: Fx::ZERO,
            kb_decay_x: Fx::ZERO,
            kb_decay_y: Fx::ZERO,
            facing,
            grounded_on,
            air_jumps_left: params.air_jumps,
            fast_falling: false,
            hitlag: 0,
            intangible: 0,
            percent: 0,
            stocks,
            drop_through: 0,
            jump_buffer: 0,
            attack_buffer: 0,
            prev_input: Input::default(),
        }
    }

    pub fn grounded(&self) -> bool {
        self.grounded_on.is_some()
    }

    pub fn hittable(&self) -> bool {
        self.intangible == 0 && !matches!(self.state, State::Respawning { .. } | State::Eliminated)
    }

    /// Whether a circle overlaps this fighter's capsule hurtbox.
    pub fn hurtbox_overlaps(&self, cx: Fx, cy: Fx, r: Fx) -> bool {
        let p = self.params;
        let bottom = self.y + p.radius;
        let top = self.y + p.height - p.radius;
        let dx = (cx - self.x).raw() as i64;
        let dy = (cy - cy.clamp(bottom, top)).raw() as i64;
        let reach = (r + p.radius).raw() as i64;
        dx * dx + dy * dy <= reach * reach
    }

    /// A short name for the current pose, for the renderer to pick animations.
    pub fn anim(&self) -> &'static str {
        match self.state {
            State::Ground if self.vx.abs() > self.params.walk_speed => "run",
            State::Ground if self.vx != Fx::ZERO => "walk",
            State::Ground => "idle",
            State::JumpSquat { .. } => "jumpsquat",
            State::Air => "air",
            State::Landing { .. } => "land",
            State::Attack { mv, .. } => mv.data().name,
            State::Hitstun { .. } => "hitstun",
            State::Respawning { .. } => "respawning",
            State::Eliminated => "eliminated",
        }
    }

    pub(crate) fn step(&mut self, input: Input, stage: &Stage) {
        let (sx, sy) = input.stick();
        let (_, prev_sy) = self.prev_input.stick();
        let pressed = |b| input.held(b) && !self.prev_input.held(b);
        self.jump_buffer = if pressed(Input::JUMP) { BUFFER_FRAMES } else { self.jump_buffer.saturating_sub(1) };
        self.attack_buffer = if pressed(Input::ATTACK) { BUFFER_FRAMES } else { self.attack_buffer.saturating_sub(1) };
        let down_tap = sy <= DOWN_TAP && prev_sy > DOWN_TAP;
        self.prev_input = input;

        // Hitlag freezes everything except input buffering.
        if self.hitlag > 0 {
            self.hitlag -= 1;
            return;
        }
        self.intangible = self.intangible.saturating_sub(1);

        let p = self.params;
        match self.state {
            State::Eliminated => return,
            State::Respawning { frames_left } => {
                if frames_left <= 1 {
                    self.respawn(stage);
                } else {
                    self.state = State::Respawning { frames_left: frames_left - 1 };
                }
                return;
            }
            State::Ground => {
                if self.take_jump() {
                    self.state = State::JumpSquat { frame: 0 };
                } else if self.take_attack() {
                    let mv = if sy >= TILT_THRESHOLD && sy.abs() > sx.abs() {
                        MoveId::UTilt
                    } else if sx.abs() >= TILT_THRESHOLD {
                        self.facing = sx.signum();
                        MoveId::FTilt
                    } else {
                        MoveId::Jab
                    };
                    self.start_attack(mv);
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                } else if down_tap && self.on_soft_platform(stage) {
                    self.grounded_on = None;
                    self.drop_through = DROP_THROUGH_FRAMES;
                    self.state = State::Air;
                } else if sx.abs() >= DEADZONE {
                    self.facing = sx.signum();
                    let max = if sx.abs() >= RUN_THRESHOLD { p.run_speed } else { p.walk_speed };
                    self.vx = self.vx.approach(sx * max, p.ground_accel);
                } else {
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                }
            }
            State::JumpSquat { frame } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                if frame + 1 >= p.jump_squat {
                    // Releasing jump before liftoff gives a short hop.
                    self.vy = if input.held(Input::JUMP) { p.full_hop } else { p.short_hop };
                    self.grounded_on = None;
                    self.state = State::Air;
                } else {
                    self.state = State::JumpSquat { frame: frame + 1 };
                }
            }
            State::Air => {
                if self.air_jumps_left > 0 && self.take_jump() {
                    self.air_jumps_left -= 1;
                    self.vy = p.double_jump;
                    self.vx = sx * p.air_speed;
                    self.fast_falling = false;
                } else if self.take_attack() {
                    self.start_attack(MoveId::Nair);
                }
                self.air_control(sx, down_tap);
            }
            State::Landing { frames_left } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                self.state = if frames_left <= 1 { State::Ground } else { State::Landing { frames_left: frames_left - 1 } };
            }
            State::Attack { mv, frame, hit_mask } => {
                if self.grounded() {
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                } else {
                    self.air_control(sx, down_tap);
                }
                self.state = if frame >= mv.data().total_frames {
                    self.idle_state()
                } else {
                    State::Attack { mv, frame: frame + 1, hit_mask }
                };
            }
            State::Hitstun { frames_left } => {
                if self.grounded() {
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                }
                self.state = if frames_left <= 1 { self.idle_state() } else { State::Hitstun { frames_left: frames_left - 1 } };
            }
        }

        self.physics(stage);
    }

    fn physics(&mut self, stage: &Stage) {
        let p = self.params;
        if !self.grounded() {
            self.vy = if self.fast_falling { -p.fast_fall } else { (self.vy - p.gravity).max(-p.max_fall) };
        }
        self.kb_x = self.kb_x.approach(Fx::ZERO, self.kb_decay_x);
        self.kb_y = self.kb_y.approach(Fx::ZERO, self.kb_decay_y);
        self.drop_through = self.drop_through.saturating_sub(1);

        let prev_y = self.y;
        self.x += self.vx + self.kb_x;
        self.y += self.vy + self.kb_y;

        match self.grounded_on {
            Some(i) => {
                let plat = &stage.platforms[i];
                if plat.contains_x(self.x) {
                    self.y = plat.y;
                } else {
                    self.grounded_on = None;
                    if matches!(self.state, State::Ground | State::Landing { .. }) {
                        self.state = State::Air;
                    }
                }
            }
            None if self.vy + self.kb_y <= Fx::ZERO => {
                let landed_on = stage.platforms.iter().position(|plat| {
                    !(plat.soft && self.drop_through > 0) && prev_y >= plat.y && self.y <= plat.y && plat.contains_x(self.x)
                });
                if let Some(i) = landed_on {
                    self.land(i, stage.platforms[i].y);
                }
            }
            None => {}
        }
    }

    fn land(&mut self, platform: usize, y: Fx) {
        self.y = y;
        self.grounded_on = Some(platform);
        self.vy = Fx::ZERO;
        self.kb_y = Fx::ZERO;
        self.fast_falling = false;
        self.air_jumps_left = self.params.air_jumps;
        self.state = match self.state {
            State::Air => State::Landing { frames_left: self.params.landing_lag },
            State::Attack { mv, .. } if mv.data().aerial => State::Landing { frames_left: mv.data().landing_lag },
            // No teching yet: tumbling fighters just keep sliding in hitstun.
            other => other,
        };
    }

    fn air_control(&mut self, sx: Fx, down_tap: bool) {
        let p = self.params;
        self.vx = if sx.abs() >= DEADZONE {
            self.vx.approach(sx * p.air_speed, p.air_accel)
        } else {
            self.vx.approach(Fx::ZERO, p.air_friction)
        };
        if down_tap && self.vy <= Fx::ZERO {
            self.fast_falling = true;
        }
    }

    pub(crate) fn take_hit(&mut self, knockback: Fx, angle: i32, direction: i32) {
        let (cos, sin) = (cos_deg(angle), sin_deg(angle));
        let speed = knockback * LAUNCH_SPEED;
        self.kb_x = speed * cos * direction;
        self.kb_y = speed * sin;
        self.kb_decay_x = (KB_DECAY * cos).abs();
        self.kb_decay_y = (KB_DECAY * sin).abs();
        self.vx = Fx::ZERO;
        self.vy = Fx::ZERO;
        self.fast_falling = false;
        if self.grounded() && (knockback < GROUNDED_KB_THRESHOLD || self.kb_y <= Fx::ZERO) {
            self.kb_y = Fx::ZERO;
        } else {
            self.grounded_on = None;
        }
        let hitstun = (knockback * HITSTUN_PER_KB).floor_to_int().max(1);
        self.state = State::Hitstun { frames_left: hitstun as u16 };
    }

    pub(crate) fn ko(&mut self, stage: &Stage) {
        self.stocks = self.stocks.saturating_sub(1);
        self.percent = 0;
        self.vx = Fx::ZERO;
        self.vy = Fx::ZERO;
        self.kb_x = Fx::ZERO;
        self.kb_y = Fx::ZERO;
        self.grounded_on = None;
        self.fast_falling = false;
        (self.x, self.y) = stage.respawn;
        self.state = if self.stocks == 0 { State::Eliminated } else { State::Respawning { frames_left: RESPAWN_FRAMES } };
    }

    fn respawn(&mut self, stage: &Stage) {
        (self.x, self.y) = stage.respawn;
        self.vx = Fx::ZERO;
        self.vy = Fx::ZERO;
        self.air_jumps_left = self.params.air_jumps;
        self.intangible = RESPAWN_INTANGIBLE_FRAMES;
        self.state = State::Air;
    }

    fn start_attack(&mut self, mv: MoveId) {
        self.state = State::Attack { mv, frame: 1, hit_mask: 0 };
    }

    fn idle_state(&self) -> State {
        if self.grounded() { State::Ground } else { State::Air }
    }

    fn on_soft_platform(&self, stage: &Stage) -> bool {
        self.grounded_on.is_some_and(|i| stage.platforms[i].soft)
    }

    fn take_jump(&mut self) -> bool {
        let buffered = self.jump_buffer > 0;
        self.jump_buffer = 0;
        buffered
    }

    fn take_attack(&mut self) -> bool {
        let buffered = self.attack_buffer > 0;
        self.attack_buffer = 0;
        buffered
    }
}

/// Smash's knockback formula (Melee/Brawl form), in knockback units.
/// `percent` is the target's damage *after* the hit is applied.
pub fn knockback(percent: i32, damage: i32, weight: i32, base_kb: i32, kb_growth: i32) -> Fx {
    let p = Fx::int(percent);
    let d = Fx::int(damage);
    let damage_term = p / Fx::int(10) + p * d / Fx::int(20);
    let weight_term = Fx::ratio(200, (weight + 100) as i64);
    let scaled = damage_term * weight_term * Fx::ratio(14, 10) + Fx::int(18);
    scaled * Fx::ratio(kb_growth as i64, 100) + Fx::int(base_kb)
}

/// Frames both fighters freeze on hit (Melee: floor(damage / 3 + 3)).
pub fn hitlag_frames(damage: i32) -> u8 {
    (damage / 3 + 3).clamp(0, u8::MAX as i32) as u8
}
