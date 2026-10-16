use crate::character::{Character, Moveset};
use crate::fixed::{Fx, cos_deg, sin_deg};
use crate::input::Input;
use crate::moves::{DodgeKind, Landing, MoveData, MoveId};
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
    pub const MANNEQUIN: FighterParams = FighterParams {
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

    /// Light and short, quick on the ground, with lower jumps but two air jumps.
    pub const PUG: FighterParams = FighterParams {
        weight: 82,
        walk_speed: Fx::ratio(12, 10),
        run_speed: Fx::ratio(18, 10),
        ground_accel: Fx::ratio(25, 100),
        traction: Fx::ratio(7, 100),
        air_speed: Fx::ratio(8, 10),
        air_accel: Fx::ratio(5, 100),
        air_friction: Fx::ratio(2, 100),
        gravity: Fx::ratio(1, 10),
        max_fall: Fx::ratio(18, 10),
        fast_fall: Fx::ratio(25, 10),
        jump_squat: 3,
        full_hop: Fx::ratio(21, 10),
        short_hop: Fx::ratio(14, 10),
        double_jump: Fx::ratio(18, 10),
        air_jumps: 2,
        landing_lag: 4,
        height: Fx::int(9),
        radius: Fx::int(4),
    };
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum State {
    /// Standing, walking or running.
    Ground,
    /// Holding down on the ground.
    Crouch,
    JumpSquat { frame: u8 },
    Air,
    /// Helpless after an up/down special: can only drift until landing.
    SpecialFall,
    Landing { frames_left: u8 },
    /// Any move from `moves.rs`. `hit_mask` has bit `i` set once fighter `i` was hit by this swing.
    Attack { mv: MoveId, frame: u16, hit_mask: u8 },
    Dodge { kind: DodgeKind, frame: u16 },
    Shield,
    ShieldStun { frames_left: u8 },
    /// Lowering the shield; no actions until it's down.
    ShieldDrop { frames_left: u8 },
    /// Dizzy after the shield broke.
    ShieldBreak { frames_left: u16 },
    /// Holding a grabbed opponent (`Fighter::holding`). Pummels and throws are `Attack`s.
    Holding { frame: u16 },
    /// Caught by fighter `by`. Breaks free when `frames_left` runs out; mashing speeds it up.
    Held { by: u8, frames_left: u16 },
    Hitstun { frames_left: u16 },
    Respawning { frames_left: u16 },
    Eliminated,
}

const DEADZONE: Fx = Fx::ratio(2, 10);
const RUN_THRESHOLD: Fx = Fx::ratio(8, 10);
const TILT_THRESHOLD: Fx = Fx::ratio(5, 10);
const DOWN_TAP: Fx = Fx::ratio(-65, 100);
/// A stick pushed this far within `SMASH_WINDOW` frames of leaving neutral is a
/// flick: with attack, a smash attack.
const SMASH_THRESHOLD: Fx = Fx::ratio(8, 10);
const SMASH_WINDOW: u8 = 3;
/// Pushing the stick past this while shielding rolls (sideways) or spot dodges (down).
const DODGE_THRESHOLD: Fx = Fx::ratio(7, 10);
/// Presses are remembered this many frames, so an input slightly early
/// (e.g. during landing lag) still comes out on the first actionable frame.
const BUFFER_FRAMES: u8 = 6;
const DROP_THROUGH_FRAMES: u8 = 10;
const RESPAWN_FRAMES: u16 = 60;
const RESPAWN_INTANGIBLE_FRAMES: u16 = 120;
const SPECIAL_FALL_LANDING_LAG: u8 = 20;
const AIR_DODGE_LANDING_LAG: u8 = 10;
/// Smash attacks charge for up to this many frames, for up to 1.4x damage.
pub const MAX_CHARGE: u8 = 60;
const CHARGE_DAMAGE_DIVISOR: i32 = 150;

/// Shield health (Ultimate: 50). Drains while held, refills while not, and
/// breaks at zero.
pub const SHIELD_MAX: Fx = Fx::int(50);
const SHIELD_DECAY: Fx = Fx::ratio(15, 100);
const SHIELD_REGEN: Fx = Fx::ratio(8, 100);
const SHIELD_AFTER_BREAK: Fx = Fx::ratio(50 * 3, 8);
const SHIELD_DROP_FRAMES: u8 = 11;
const SHIELD_BREAK_FRAMES: u16 = 240;
const SHIELD_PUSHBACK_DECAY: Fx = Fx::ratio(1, 10);

/// Held opponents sit this far in front of the grabber.
pub const GRAB_HOLD_DISTANCE: Fx = Fx::int(9);
/// Frames until a held fighter breaks free on its own, plus one per percent.
const GRAB_HOLD_FRAMES: u16 = 90;
/// Each new button press or stick flick while held takes this many frames off.
const MASH_FRAMES: u16 = 5;
const GRAB_RELEASE_HOLDER_LAG: u8 = 15;
const GRAB_RELEASE_VICTIM_LAG: u8 = 10;

/// Knockback units -> launch speed, and per-frame decay of that speed (Melee).
const LAUNCH_SPEED: Fx = Fx::ratio(3, 100);
const KB_DECAY: Fx = Fx::ratio(51, 1000);
const HITSTUN_PER_KB: Fx = Fx::ratio(4, 10);
/// Grounded targets hit with less knockback than this slide instead of lifting off.
const GROUNDED_KB_THRESHOLD: Fx = Fx::int(80);

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Fighter {
    pub character: Character,
    /// `character.params()`, kept at hand.
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
    /// One air dodge and one aerial side special per trip through the air.
    pub air_dodge_used: bool,
    pub side_special_used: bool,
    pub hitlag: u8,
    pub intangible: u16,
    pub percent: i32,
    pub stocks: u8,
    pub shield: Fx,
    /// Frames the current smash attack was charged.
    pub charge: u8,
    /// The fighter this one has grabbed, while holding, pummeling or throwing.
    pub holding: Option<usize>,
    /// Set by `step` when an `Attack` reaches a new frame, so the world fires
    /// projectiles and throws exactly once (not again while frozen in hitlag or charging).
    pub(crate) frame_advanced: bool,
    drop_through: u8,
    jump_buffer: u8,
    attack_buffer: u8,
    /// Whether the buffered attack was a smash input (SMASH button or a flick).
    attack_is_smash: bool,
    special_buffer: u8,
    grab_buffer: u8,
    shield_buffer: u8,
    /// Frames each stick axis has been out of the deadzone.
    stick_x_age: u8,
    stick_y_age: u8,
    prev_input: Input,
}

/// What a frame's stick and buttons mean, worked out once at the top of `step`.
struct Intent {
    sx: Fx,
    sy: Fx,
    down_tap: bool,
    /// The stick just crossed `DODGE_THRESHOLD` sideways / downward.
    dodge_x: bool,
    dodge_down: bool,
    /// Any new press or flick, for mashing out of grabs.
    mashed: bool,
}

impl Intent {
    /// The stick points mostly up or down, past the tilt threshold.
    fn vertical(&self) -> Option<i32> {
        (self.sy.abs() > self.sx.abs() && self.sy.abs() >= TILT_THRESHOLD).then(|| self.sy.signum())
    }
}

impl Fighter {
    pub fn new(character: Character, x: Fx, y: Fx, facing: i32, stage: &Stage, stocks: u8) -> Fighter {
        let grounded_on = stage.platform_under(x, y);
        let params = character.params();
        Fighter {
            character,
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
            air_dodge_used: false,
            side_special_used: false,
            hitlag: 0,
            intangible: 0,
            percent: 0,
            stocks,
            shield: SHIELD_MAX,
            charge: 0,
            holding: None,
            frame_advanced: false,
            drop_through: 0,
            jump_buffer: 0,
            attack_buffer: 0,
            attack_is_smash: false,
            special_buffer: 0,
            grab_buffer: 0,
            shield_buffer: 0,
            stick_x_age: 0,
            stick_y_age: 0,
            prev_input: Input::default(),
        }
    }

    fn moveset(&self) -> &'static Moveset {
        self.character.moveset()
    }

    /// The move a counter switches to, if a hit landing now would be countered.
    pub(crate) fn counter_move(&self) -> Option<MoveId> {
        let State::Attack { mv, frame, .. } = self.state else { return None };
        let counter = mv.data().counter.as_ref()?;
        (counter.first..=counter.last).contains(&frame).then_some(counter.into)
    }

    pub fn grounded(&self) -> bool {
        self.grounded_on.is_some()
    }

    pub fn hittable(&self) -> bool {
        self.intangible == 0 && !self.dodge_invincible() && !matches!(self.state, State::Respawning { .. } | State::Eliminated)
    }

    /// In the invincible part of a dodge or roll.
    pub fn dodge_invincible(&self) -> bool {
        match self.state {
            State::Dodge { kind, frame } => {
                let (first, last) = kind.data().intangible;
                (first..=last).contains(&frame)
            }
            _ => false,
        }
    }

    /// Shield up: hits do shield damage instead of percent.
    pub fn shielding(&self) -> bool {
        matches!(self.state, State::Shield | State::ShieldStun { .. })
    }

    /// Holding a charge (smash attack, sneeze) right now.
    pub fn charging(&self) -> bool {
        matches!(self.state, State::Attack { mv, frame, .. } if self.charge > 0 && mv.data().charge_frame == Some(frame))
    }

    pub(crate) fn grabbable(&self) -> bool {
        self.hittable() && self.holding.is_none() && !matches!(self.state, State::Held { .. })
    }

    /// Damage of a hitbox, scaled up by smash charge.
    pub(crate) fn charged(&self, damage: i32) -> i32 {
        damage * (CHARGE_DAMAGE_DIVISOR + self.charge as i32) / CHARGE_DAMAGE_DIVISOR
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

    /// A short name for the current pose, for the renderer to pick animations: one of
    /// [`STATE_ANIMS`], a move's name (`Character::moves`) or a dodge's
    /// (`DodgeKind::ALL`), or "respawning" / "eliminated", which aren't drawn.
    pub fn anim(&self) -> &'static str {
        match self.state {
            State::Ground if self.vx.abs() > self.params.walk_speed => "run",
            State::Ground if self.vx != Fx::ZERO => "walk",
            State::Ground => "idle",
            State::Crouch => "crouch",
            State::JumpSquat { .. } => "jumpsquat",
            State::Air => "air",
            State::SpecialFall => "specialfall",
            State::Landing { .. } => "land",
            State::Attack { mv, .. } => mv.data().name,
            State::Dodge { kind, .. } => kind.data().name,
            State::Shield | State::ShieldStun { .. } | State::ShieldDrop { .. } => "shield",
            State::ShieldBreak { .. } => "dizzy",
            State::Holding { .. } => "grab_hold",
            State::Held { .. } => "grabbed",
            State::Hitstun { .. } => "hitstun",
            State::Respawning { .. } => "respawning",
            State::Eliminated => "eliminated",
        }
    }

    pub(crate) fn step(&mut self, input: Input, stage: &Stage) {
        let intent = self.read_input(input);
        self.frame_advanced = false;

        // Hitlag freezes everything except input buffering.
        if self.hitlag > 0 {
            self.hitlag -= 1;
            return;
        }
        self.intangible = self.intangible.saturating_sub(1);
        if !matches!(self.state, State::Shield | State::ShieldStun { .. } | State::ShieldBreak { .. }) {
            self.shield = (self.shield + SHIELD_REGEN).min(SHIELD_MAX);
        }

        let p = self.params;
        let (sx, sy) = (intent.sx, intent.sy);
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
            State::Held { by, frames_left } => {
                // The world keeps a held fighter in the grabber's hand.
                let mash = if intent.mashed { MASH_FRAMES } else { 0 };
                self.state = State::Held { by, frames_left: frames_left.saturating_sub(1 + mash) };
                return;
            }
            State::Ground | State::Crouch => {
                if !self.ground_action(input, &intent, stage) {
                    if sy <= -TILT_THRESHOLD {
                        self.state = State::Crouch;
                        self.vx = self.vx.approach(Fx::ZERO, p.traction);
                    } else {
                        self.state = State::Ground;
                        if sx.abs() >= DEADZONE {
                            self.facing = sx.signum();
                            let max = if sx.abs() >= RUN_THRESHOLD { p.run_speed } else { p.walk_speed };
                            self.vx = self.vx.approach(sx * max, p.ground_accel);
                        } else {
                            self.vx = self.vx.approach(Fx::ZERO, p.traction);
                        }
                    }
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
                if self.air_jumps_left > 0 && take(&mut self.jump_buffer) {
                    self.air_jumps_left -= 1;
                    self.vy = p.double_jump;
                    self.vx = sx * p.air_speed;
                    self.fast_falling = false;
                    self.air_control(sx, intent.down_tap);
                } else if !self.air_dodge_used && take(&mut self.shield_buffer) {
                    self.start_air_dodge(sx, sy);
                } else {
                    if take(&mut self.special_buffer) {
                        self.start_special(&intent);
                    } else if take(&mut self.attack_buffer) {
                        self.start_attack(aerial(self.moveset(), &intent, self.facing));
                    }
                    self.air_control(sx, intent.down_tap);
                }
            }
            State::SpecialFall => self.air_control(sx, intent.down_tap),
            State::Landing { frames_left } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                self.state = if frames_left <= 1 { self.idle_state() } else { State::Landing { frames_left: frames_left - 1 } };
            }
            State::Attack { mv, frame, hit_mask } => {
                let data = mv.data();
                if self.grounded() {
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                } else {
                    self.air_control(sx, intent.down_tap);
                }
                let combo = data.combo.filter(|&(_, from)| frame >= from && self.attack_buffer > 0 && !self.attack_is_smash);
                let holding_charge = input.held(data.charge_with);
                if let Some((next, _)) = combo {
                    self.attack_buffer = 0;
                    self.start_attack(next);
                } else if data.charge_frame == Some(frame) && holding_charge && self.charge < MAX_CHARGE {
                    self.charge += 1;
                } else if frame >= data.total_frames {
                    self.state = self.after_move(data);
                } else {
                    self.state = State::Attack { mv, frame: frame + 1, hit_mask };
                    self.frame_advanced = true;
                }
            }
            State::Dodge { kind, frame } => {
                let data = kind.data();
                if self.grounded() {
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                } else if kind == DodgeKind::Air || frame > data.moving.1 {
                    self.air_control(sx, false);
                }
                if frame >= data.total_frames {
                    if kind == DodgeKind::RollForward {
                        self.facing = -self.facing;
                    }
                    self.state = self.idle_state();
                } else {
                    self.state = State::Dodge { kind, frame: frame + 1 };
                }
            }
            State::Shield => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                self.shield -= SHIELD_DECAY;
                if self.shield <= Fx::ZERO {
                    self.break_shield();
                } else {
                    self.shield_action(input, &intent);
                }
            }
            State::ShieldStun { frames_left } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                self.state = match frames_left {
                    0 | 1 if input.held(Input::SHIELD) => State::Shield,
                    0 | 1 => State::ShieldDrop { frames_left: SHIELD_DROP_FRAMES },
                    n => State::ShieldStun { frames_left: n - 1 },
                };
            }
            State::ShieldDrop { frames_left } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                self.state = if frames_left <= 1 { self.idle_state() } else { State::ShieldDrop { frames_left: frames_left - 1 } };
            }
            State::ShieldBreak { frames_left } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                self.state = if frames_left <= 1 { self.idle_state() } else { State::ShieldBreak { frames_left: frames_left - 1 } };
            }
            State::Holding { frame } => {
                self.vx = self.vx.approach(Fx::ZERO, p.traction);
                let moves = self.moveset();
                let throw = match intent.vertical() {
                    Some(1) => Some(moves.uthrow),
                    Some(_) => Some(moves.dthrow),
                    None if sx.abs() >= TILT_THRESHOLD && sx.signum() == self.facing => Some(moves.fthrow),
                    None if sx.abs() >= TILT_THRESHOLD => Some(moves.bthrow),
                    None => None,
                };
                if let Some(throw) = throw {
                    self.attack_buffer = 0;
                    self.start_attack(throw);
                } else if take(&mut self.attack_buffer) {
                    self.start_attack(moves.pummel);
                } else {
                    self.state = State::Holding { frame: frame.saturating_add(1) };
                }
            }
            State::Hitstun { frames_left } => {
                if self.grounded() {
                    self.vx = self.vx.approach(Fx::ZERO, p.traction);
                }
                self.state = if frames_left <= 1 { self.idle_state() } else { State::Hitstun { frames_left: frames_left - 1 } };
            }
        }

        self.scripted_motion();
        self.physics(stage);
    }

    /// Updates buffers and stick history, and returns what this frame's input means.
    fn read_input(&mut self, input: Input) -> Intent {
        let prev = self.prev_input;
        let (sx, sy) = input.stick();
        let (prev_sx, prev_sy) = prev.stick();
        let pressed = |b| input.held(b) && !prev.held(b);
        let age = |age: u8, v: Fx| if v.abs() < DEADZONE { 0 } else { age.saturating_add(1) };
        self.stick_x_age = age(self.stick_x_age, sx);
        self.stick_y_age = age(self.stick_y_age, sy);
        let flick = (sx.abs() >= SMASH_THRESHOLD && self.stick_x_age <= SMASH_WINDOW)
            || (sy.abs() >= SMASH_THRESHOLD && self.stick_y_age <= SMASH_WINDOW);

        let buffer = |buf: &mut u8, now: bool| *buf = if now { BUFFER_FRAMES } else { buf.saturating_sub(1) };
        if pressed(Input::ATTACK) || pressed(Input::SMASH) {
            self.attack_is_smash = pressed(Input::SMASH) || flick;
        }
        buffer(&mut self.attack_buffer, pressed(Input::ATTACK) || pressed(Input::SMASH));
        buffer(&mut self.jump_buffer, pressed(Input::JUMP));
        buffer(&mut self.special_buffer, pressed(Input::SPECIAL));
        buffer(&mut self.grab_buffer, pressed(Input::GRAB));
        buffer(&mut self.shield_buffer, pressed(Input::SHIELD));
        self.prev_input = input;

        Intent {
            sx,
            sy,
            down_tap: sy <= DOWN_TAP && prev_sy > DOWN_TAP,
            dodge_x: sx.abs() >= DODGE_THRESHOLD && prev_sx.abs() < DODGE_THRESHOLD,
            dodge_down: sy <= -DODGE_THRESHOLD && prev_sy > -DODGE_THRESHOLD,
            mashed: input.buttons & !prev.buttons != 0 || self.stick_x_age == 1 || self.stick_y_age == 1,
        }
    }

    /// Actions available standing or crouching. Returns false if none started.
    fn ground_action(&mut self, input: Input, intent: &Intent, stage: &Stage) -> bool {
        let (sx, sy) = (intent.sx, intent.sy);
        let running = self.vx.abs() > self.params.walk_speed && sx.abs() >= RUN_THRESHOLD && sx.signum() == self.vx.signum();
        let shield_held = input.held(Input::SHIELD);
        if take(&mut self.jump_buffer) {
            self.state = State::JumpSquat { frame: 0 };
        } else if take(&mut self.grab_buffer) || (shield_held && take(&mut self.attack_buffer)) {
            let moves = self.moveset();
            self.start_attack(if running { moves.dash_grab } else { moves.grab });
        } else if shield_held {
            // Pressing shield with the stick already pushed dodges straight away.
            let fresh = take(&mut self.shield_buffer);
            if fresh && sx.abs() >= DODGE_THRESHOLD {
                self.start_roll(sx);
            } else if fresh && sy <= -DODGE_THRESHOLD {
                self.start_dodge(DodgeKind::Spot);
            } else {
                self.state = State::Shield;
            }
        } else if take(&mut self.special_buffer) {
            self.start_special(intent);
        } else if take(&mut self.attack_buffer) {
            let mv = self.ground_attack(intent, running);
            self.start_attack(mv);
        } else if intent.down_tap && self.on_soft_platform(stage) {
            self.grounded_on = None;
            self.drop_through = DROP_THROUGH_FRAMES;
            self.state = State::Air;
        } else {
            self.shield_buffer = 0;
            return false;
        }
        if matches!(self.state, State::Attack { .. } | State::Shield | State::Dodge { .. }) {
            self.vx = self.vx.approach(Fx::ZERO, self.params.traction);
        }
        true
    }

    fn ground_attack(&mut self, intent: &Intent, running: bool) -> MoveId {
        let sx = intent.sx;
        let moves = self.moveset();
        match intent.vertical() {
            Some(1) if self.attack_is_smash => moves.usmash,
            Some(_) if self.attack_is_smash => moves.dsmash,
            None if self.attack_is_smash => {
                if sx.abs() >= DEADZONE {
                    self.facing = sx.signum();
                }
                moves.fsmash
            }
            _ if running => moves.dash_attack,
            Some(1) => moves.utilt,
            Some(_) => moves.dtilt,
            None if sx.abs() >= TILT_THRESHOLD => {
                self.facing = sx.signum();
                moves.ftilt
            }
            None => moves.jab,
        }
    }

    fn shield_action(&mut self, input: Input, intent: &Intent) {
        let up = intent.vertical() == Some(1);
        let moves = self.moveset();
        if take(&mut self.jump_buffer) {
            self.state = State::JumpSquat { frame: 0 };
        } else if up && take(&mut self.special_buffer) {
            self.start_attack(moves.up_special);
        } else if take(&mut self.attack_buffer) {
            // Up smash straight out of shield; any other attack button grabs.
            let smash = self.attack_is_smash && up;
            self.start_attack(if smash { moves.usmash } else { moves.grab });
        } else if take(&mut self.grab_buffer) {
            self.start_attack(moves.grab);
        } else if !input.held(Input::SHIELD) {
            self.state = State::ShieldDrop { frames_left: SHIELD_DROP_FRAMES };
        } else if intent.dodge_x {
            self.start_roll(intent.sx);
        } else if intent.dodge_down {
            self.start_dodge(DodgeKind::Spot);
        }
    }

    fn start_special(&mut self, intent: &Intent) {
        let moves = self.moveset();
        let mv = match intent.vertical() {
            Some(1) => moves.up_special,
            Some(_) => moves.down_special,
            None if intent.sx.abs() >= TILT_THRESHOLD => {
                if !self.grounded() {
                    if self.side_special_used {
                        return;
                    }
                    self.side_special_used = true;
                }
                self.facing = intent.sx.signum();
                moves.side_special
            }
            None => moves.neutral_special,
        };
        self.start_attack(mv);
    }

    pub(crate) fn start_attack(&mut self, mv: MoveId) {
        self.state = State::Attack { mv, frame: 1, hit_mask: 0 };
        self.charge = 0;
        self.frame_advanced = true;
    }

    fn start_dodge(&mut self, kind: DodgeKind) {
        self.state = State::Dodge { kind, frame: 1 };
    }

    fn start_roll(&mut self, sx: Fx) {
        self.start_dodge(if sx.signum() == self.facing { DodgeKind::RollForward } else { DodgeKind::RollBack });
    }

    fn start_air_dodge(&mut self, sx: Fx, sy: Fx) {
        self.air_dodge_used = true;
        self.fast_falling = false;
        let length = Fx::hypot(sx, sy);
        if length < DEADZONE {
            self.start_dodge(DodgeKind::Air);
        } else {
            let speed = DodgeKind::AirDirectional.data().speed;
            self.vx = speed * sx / length;
            self.vy = speed * sy / length;
            self.start_dodge(DodgeKind::AirDirectional);
        }
    }

    /// State after a move's last frame.
    fn after_move(&self, data: &MoveData) -> State {
        if self.holding.is_some() {
            State::Holding { frame: 0 }
        } else if !self.grounded() && data.special_fall {
            State::SpecialFall
        } else {
            self.idle_state()
        }
    }

    /// Velocity set by the current move's `Motion` or dodge, overriding control.
    fn scripted_motion(&mut self) {
        match self.state {
            State::Attack { mv, frame, .. } => {
                for m in mv.data().motion.iter().filter(|m| (m.first..=m.last).contains(&frame)) {
                    if let Some(vx) = m.vx {
                        self.vx = vx * self.facing;
                    }
                    if let Some(vy) = m.vy {
                        self.vy = vy;
                        self.fast_falling = false;
                        if vy > Fx::ZERO {
                            self.grounded_on = None;
                        }
                    }
                }
            }
            State::Dodge { kind, frame } => {
                let data = kind.data();
                let (first, last) = data.moving;
                if !(first..=last).contains(&frame) {
                    return;
                }
                if kind == DodgeKind::AirDirectional {
                    // Slow down linearly, reaching zero on the last moving frame.
                    let left = Fx::int((last - frame + 1) as i32);
                    self.vx = self.vx * (left - Fx::ONE) / left;
                    self.vy = self.vy * (left - Fx::ONE) / left;
                } else if self.grounded() {
                    self.vx = data.speed * self.facing;
                }
            }
            _ => {}
        }
    }

    /// Whether something other than gravity sets vertical speed this frame.
    fn vertical_scripted(&self) -> bool {
        match self.state {
            State::Attack { mv, frame, .. } => mv.data().motion.iter().any(|m| m.vy.is_some() && (m.first..=m.last).contains(&frame)),
            State::Dodge { kind: DodgeKind::AirDirectional, frame } => frame <= DodgeKind::AirDirectional.data().moving.1,
            _ => false,
        }
    }

    /// States that stop at a platform's edge instead of sliding off it.
    fn stops_at_ledge(&self) -> bool {
        match self.state {
            State::Crouch
            | State::Dodge { .. }
            | State::Shield
            | State::ShieldStun { .. }
            | State::ShieldDrop { .. }
            | State::ShieldBreak { .. }
            | State::Holding { .. } => true,
            State::Attack { .. } => self.holding.is_some(),
            _ => false,
        }
    }

    fn physics(&mut self, stage: &Stage) {
        let p = self.params;
        if !self.grounded() && !self.vertical_scripted() {
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
                if !plat.contains_x(self.x) && self.stops_at_ledge() {
                    self.x = self.x.clamp(plat.left, plat.right);
                    self.vx = Fx::ZERO;
                    self.kb_x = Fx::ZERO;
                }
                if plat.contains_x(self.x) {
                    self.y = plat.y;
                } else {
                    self.grounded_on = None;
                    if matches!(self.state, State::Ground | State::Crouch | State::Landing { .. }) {
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
        self.air_dodge_used = false;
        self.side_special_used = false;
        match self.state {
            State::Air => self.state = State::Landing { frames_left: self.params.landing_lag },
            State::SpecialFall => self.state = State::Landing { frames_left: SPECIAL_FALL_LANDING_LAG },
            State::Dodge { kind, .. } if kind.aerial() => self.state = State::Landing { frames_left: AIR_DODGE_LANDING_LAG },
            State::Attack { mv, .. } => match mv.data().landing {
                Landing::Continue => {}
                Landing::Lag(frames) => self.state = State::Landing { frames_left: frames },
                Landing::Into(next) => self.start_attack(next),
            },
            // No teching yet: tumbling fighters just keep sliding in hitstun.
            _ => {}
        }
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
        self.air_dodge_used = false;
        self.side_special_used = false;
        self.charge = 0;
        if self.grounded() && (knockback < GROUNDED_KB_THRESHOLD || self.kb_y <= Fx::ZERO) {
            self.kb_y = Fx::ZERO;
        } else {
            self.grounded_on = None;
        }
        let hitstun = (knockback * HITSTUN_PER_KB).floor_to_int().max(1);
        self.state = State::Hitstun { frames_left: hitstun as u16 };
    }

    /// A hit on the shield. Returns true if it broke the shield.
    pub(crate) fn block(&mut self, damage: i32, direction: i32) -> bool {
        self.shield -= Fx::int(damage);
        if self.shield <= Fx::ZERO {
            self.break_shield();
            return true;
        }
        // Ultimate's shieldstun: damage × 0.8 × 0.725, plus 2.
        let stun = (damage * 58 / 100 + 2).clamp(1, u8::MAX as i32);
        self.state = State::ShieldStun { frames_left: stun as u8 };
        self.kb_x = (Fx::ratio(3, 10) + Fx::ratio(6, 100) * damage) * direction;
        self.kb_decay_x = SHIELD_PUSHBACK_DECAY;
        false
    }

    fn break_shield(&mut self) {
        self.shield = SHIELD_AFTER_BREAK;
        self.vx = Fx::ZERO;
        self.state = State::ShieldBreak { frames_left: SHIELD_BREAK_FRAMES };
    }

    /// Pushed backward at `speed` (a big sneeze's recoil), slowing like shield pushback.
    pub(crate) fn recoil(&mut self, speed: Fx) {
        self.kb_x = -speed * self.facing;
        self.kb_decay_x = SHIELD_PUSHBACK_DECAY;
    }

    /// This fighter caught `victim`.
    pub(crate) fn start_holding(&mut self, victim: usize) {
        self.holding = Some(victim);
        self.vx = Fx::ZERO;
        self.state = State::Holding { frame: 0 };
    }

    /// This fighter was caught by fighter `by`.
    pub(crate) fn get_held(&mut self, by: usize) {
        self.vx = Fx::ZERO;
        self.vy = Fx::ZERO;
        self.kb_x = Fx::ZERO;
        self.kb_y = Fx::ZERO;
        self.fast_falling = false;
        self.charge = 0;
        let frames = GRAB_HOLD_FRAMES + self.percent.clamp(0, 999) as u16;
        self.state = State::Held { by: by as u8, frames_left: frames };
    }

    /// The held fighter got away (or was dropped): the grabber is briefly stuck.
    pub(crate) fn drop_hold(&mut self) {
        self.holding = None;
        self.state = State::Landing { frames_left: GRAB_RELEASE_HOLDER_LAG };
    }

    /// Freed from a grab, pushed toward `direction`.
    pub(crate) fn escape_hold(&mut self, direction: i32) {
        self.kb_x = Fx::ONE * direction;
        self.kb_decay_x = SHIELD_PUSHBACK_DECAY;
        self.state = if self.grounded() { State::Landing { frames_left: GRAB_RELEASE_VICTIM_LAG } } else { State::Air };
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
        self.holding = None;
        self.charge = 0;
        self.shield = SHIELD_MAX;
        (self.x, self.y) = stage.respawn;
        self.state = if self.stocks == 0 { State::Eliminated } else { State::Respawning { frames_left: RESPAWN_FRAMES } };
    }

    fn respawn(&mut self, stage: &Stage) {
        (self.x, self.y) = stage.respawn;
        self.vx = Fx::ZERO;
        self.vy = Fx::ZERO;
        self.air_jumps_left = self.params.air_jumps;
        self.air_dodge_used = false;
        self.side_special_used = false;
        self.intangible = RESPAWN_INTANGIBLE_FRAMES;
        self.state = State::Air;
    }

    fn idle_state(&self) -> State {
        if self.grounded() { State::Ground } else { State::Air }
    }

    fn on_soft_platform(&self, stage: &Stage) -> bool {
        self.grounded_on.is_some_and(|i| stage.platforms[i].soft)
    }
}

/// The names `Fighter::anim` gives states other than moves and dodges. Every model
/// needs an animation for each.
pub const STATE_ANIMS: [&str; 13] =
    ["idle", "walk", "run", "crouch", "jumpsquat", "air", "specialfall", "land", "shield", "dizzy", "grab_hold", "grabbed", "hitstun"];

/// Uses up a buffered press, if there is one.
fn take(buffer: &mut u8) -> bool {
    let buffered = *buffer > 0;
    *buffer = 0;
    buffered
}

/// Aerials go by stick direction relative to where the fighter faces.
fn aerial(moves: &Moveset, intent: &Intent, facing: i32) -> MoveId {
    match intent.vertical() {
        Some(1) => moves.uair,
        Some(_) => moves.dair,
        None if intent.sx.abs() < TILT_THRESHOLD => moves.nair,
        None if intent.sx.signum() == facing => moves.fair,
        None => moves.bair,
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
