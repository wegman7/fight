use crate::character::Character;
use crate::fighter::{Fighter, GRAB_HOLD_DISTANCE, MAX_CHARGE, State, hitlag_frames, knockback};
use crate::fixed::Fx;
use crate::input::Input;
use crate::moves::{GrabBox, Hitbox, MoveId, ProjectileData, Shatter};
use crate::stage::Stage;

pub const MAX_FIGHTERS: usize = 4;
/// After countering, the fighter can't be hit for this many frames (covers its answer's startup).
const COUNTER_INTANGIBLE_FRAMES: u16 = 10;

/// Things that happened during the last [`World::step`], for effects and sound.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Event {
    /// `projectile`: the hit came from a projectile, which is used up.
    Hit { attacker: usize, defender: usize, x: Fx, y: Fx, damage: i32, knockback: Fx, projectile: bool },
    /// A hit that landed on a shield.
    ShieldHit { attacker: usize, defender: usize, x: Fx, y: Fx, damage: i32, projectile: bool },
    /// A lobbed projectile (the chef's pie) came down on a platform at x, y and is gone.
    ProjectileLanded { owner: usize, x: Fx, y: Fx },
    ShieldBreak { fighter: usize },
    Grab { attacker: usize, defender: usize },
    /// `fighter` countered a hit from `attacker` (the pug playing dead) at x, y.
    Counter { fighter: usize, attacker: usize, x: Fx, y: Fx },
    /// A shattering projectile (see `moves::Shatter`) burst at x, y as it landed or expired.
    Shatter { owner: usize, x: Fx, y: Fx },
    Ko { fighter: usize },
}

/// A hitbox (or grab box) in world space, for debug drawing.
#[derive(Clone, Copy, Debug)]
pub struct ActiveHitbox {
    pub owner: usize,
    pub x: Fx,
    pub y: Fx,
    pub radius: Fx,
    pub grab: bool,
}

/// A projectile in flight. Its numbers come from `mv`'s [`ProjectileData`], grown by
/// `charge` if the move was charged.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Projectile {
    pub owner: usize,
    pub mv: MoveId,
    pub x: Fx,
    pub y: Fx,
    pub vx: Fx,
    pub vy: Fx,
    pub frames_left: u16,
    /// Frames the move was charged before firing, 0..=MAX_CHARGE.
    pub charge: u8,
}

impl Projectile {
    pub fn data(&self) -> &'static ProjectileData {
        self.mv.data().projectile.as_ref().expect("projectile move without ProjectileData")
    }

    pub fn radius(&self) -> Fx {
        let growth = self.data().growth.as_ref().map_or(Fx::ZERO, |g| g.radius * Fx::int(self.charge as i32) / Fx::int(MAX_CHARGE as i32));
        self.data().radius + growth
    }

    pub fn damage(&self) -> i32 {
        self.data().damage + self.data().growth.as_ref().map_or(0, |g| grown(g.damage, self.charge))
    }

    pub fn base_kb(&self) -> i32 {
        self.data().base_kb + self.data().growth.as_ref().map_or(0, |g| grown(g.base_kb, self.charge))
    }
}

/// `full` scaled by how much of a full charge `charge` is.
fn grown(full: i32, charge: u8) -> i32 {
    full * charge as i32 / MAX_CHARGE as i32
}

/// The whole game state. Cloning it is a complete snapshot (for rollback).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct World {
    pub frame: u32,
    pub stage: Stage,
    pub fighters: Vec<Fighter>,
    pub projectiles: Vec<Projectile>,
    pub events: Vec<Event>,
}

/// A hit found during detection, applied once everything has been collected.
struct Strike {
    attacker: usize,
    defender: usize,
    x: Fx,
    y: Fx,
    damage: i32,
    angle: i32,
    base_kb: i32,
    kb_growth: i32,
    /// Knockback is mirrored toward this side (attacker's facing, or projectile's travel).
    direction: i32,
    projectile: Option<usize>,
}

/// A projectile's shatter burst, collected as it stops and applied with the other hits.
#[derive(Clone, Copy)]
struct Burst {
    owner: usize,
    x: Fx,
    y: Fx,
    shatter: Shatter,
}

impl World {
    /// One fighter per entry of `characters`, at the stage's spawn points in order.
    pub fn new(stage: Stage, characters: &[Character], stocks: u8) -> World {
        assert!(characters.len() <= MAX_FIGHTERS && characters.len() <= stage.spawns.len());
        let fighters = characters
            .iter()
            .enumerate()
            .map(|(i, &character)| {
                let (x, y) = stage.spawns[i];
                let facing = if x <= Fx::ZERO { 1 } else { -1 };
                Fighter::new(character, x, y, facing, &stage, stocks)
            })
            .collect();
        World { frame: 0, stage, fighters, projectiles: Vec::new(), events: Vec::new() }
    }

    /// Advances one frame (1/60 s). `inputs[i]` drives fighter `i`.
    pub fn step(&mut self, inputs: &[Input]) {
        self.frame += 1;
        self.events.clear();
        for (i, fighter) in self.fighters.iter_mut().enumerate() {
            fighter.step(inputs.get(i).copied().unwrap_or_default(), &self.stage);
        }
        self.sync_grabs();
        self.apply_throws();
        let mut bursts: Vec<Burst> = Vec::new();
        self.move_projectiles(&mut bursts);
        self.fire_projectiles();
        self.resolve_hits(&bursts);
        self.check_blast_zones();
    }

    pub fn active_hitboxes(&self) -> Vec<ActiveHitbox> {
        let mut out = Vec::new();
        for (owner, f) in self.fighters.iter().enumerate() {
            for (hb, x, y) in active_hitboxes(f) {
                out.push(ActiveHitbox { owner, x, y, radius: hb.radius, grab: false });
            }
            if let Some((gb, x, y)) = active_grabbox(f) {
                out.push(ActiveHitbox { owner, x, y, radius: gb.radius, grab: true });
            }
        }
        out
    }

    /// Keeps grabber and held fighter consistent: carries the held fighter along,
    /// and lets go when either side was interrupted (hit, KO'd) or the held one broke free.
    fn sync_grabs(&mut self) {
        for i in 0..self.fighters.len() {
            let Some(v) = self.fighters[i].holding else { continue };
            let (holder, victim) = pair_mut(&mut self.fighters, i, v);
            let holder_ok = match holder.state {
                State::Holding { .. } => true,
                State::Attack { mv, .. } => !mv.data().throws.is_empty(),
                _ => false,
            };
            let victim_ok = matches!(victim.state, State::Held { by, .. } if by as usize == i);
            // Breaking free only works between pummels and throws.
            let escaped = matches!((holder.state, victim.state), (State::Holding { .. }, State::Held { frames_left: 0, .. }));
            if holder_ok && victim_ok && !escaped {
                victim.x = holder.x + GRAB_HOLD_DISTANCE * holder.facing;
                victim.y = holder.y;
                victim.facing = -holder.facing;
                victim.grounded_on = holder.grounded_on;
                continue;
            }
            if holder_ok {
                holder.drop_hold();
            } else {
                holder.holding = None;
            }
            if victim_ok {
                victim.escape_hold(holder.facing);
            }
        }
        // Held by someone who no longer holds them (KO'd, say).
        for v in 0..self.fighters.len() {
            if let State::Held { by, .. } = self.fighters[v].state
                && self.fighters[by as usize].holding != Some(v)
            {
                let away = -self.fighters[v].facing;
                self.fighters[v].escape_hold(away);
            }
        }
    }

    /// Pummels and throws act on the held fighter on their `Throw::frame`.
    fn apply_throws(&mut self) {
        for i in 0..self.fighters.len() {
            let f = &self.fighters[i];
            let State::Attack { mv, frame, .. } = f.state else { continue };
            let Some(v) = f.holding else { continue };
            let Some(throw) = mv.data().throws.iter().find(|t| t.frame == frame) else { continue };
            if !f.frame_advanced {
                continue;
            }
            let (holder, victim) = pair_mut(&mut self.fighters, i, v);
            victim.percent = (victim.percent + throw.damage).min(999);
            let mut kb = Fx::ZERO;
            if throw.release {
                holder.holding = None;
                victim.x = holder.x + throw.x * holder.facing;
                victim.y = holder.y;
                victim.grounded_on = None;
                kb = knockback(victim.percent, throw.damage, victim.params.weight, throw.base_kb, throw.kb_growth);
                victim.take_hit(kb, throw.angle, holder.facing);
            }
            let (x, y) = (victim.x, victim.y + victim.params.height / Fx::int(2));
            self.events.push(Event::Hit { attacker: i, defender: v, x, y, damage: throw.damage, knockback: kb, projectile: false });
        }
    }

    fn move_projectiles(&mut self, bursts: &mut Vec<Burst>) {
        let s = &self.stage;
        let events = &mut self.events;
        self.projectiles.retain_mut(|p| {
            let gravity = p.data().gravity;
            let was_y = p.y;
            p.vy -= gravity;
            p.x += p.vx;
            p.y += p.vy;
            p.frames_left = p.frames_left.saturating_sub(1);
            // Coming down through the top of a platform: it lands there.
            let landed = s.platforms.iter().find(|pl| p.vy < Fx::ZERO && was_y >= pl.y && p.y < pl.y && pl.contains_x(p.x));
            if let Some(pl) = landed {
                events.push(Event::ProjectileLanded { owner: p.owner, x: p.x, y: pl.y });
                if let Some(shatter) = p.mv.data().shatter {
                    bursts.push(Burst { owner: p.owner, x: p.x, y: pl.y, shatter });
                }
                return false;
            }
            let alive = p.frames_left > 0 && p.x > s.blast_left && p.x < s.blast_right && p.y > s.blast_bottom;
            if !alive
                && let Some(shatter) = p.mv.data().shatter
            {
                bursts.push(Burst { owner: p.owner, x: p.x, y: p.y, shatter });
            }
            alive
        });
    }

    fn fire_projectiles(&mut self) {
        for (owner, f) in self.fighters.iter_mut().enumerate() {
            let State::Attack { mv, frame, .. } = f.state else { continue };
            let Some(data) = &mv.data().projectile else { continue };
            if f.frame_advanced && data.frame == frame {
                let growth = data.growth.as_ref();
                self.projectiles.push(Projectile {
                    owner,
                    mv,
                    x: f.x + data.x * f.facing,
                    y: f.y + data.y,
                    vx: data.speed * f.facing,
                    vy: data.vy,
                    frames_left: data.lifetime + growth.map_or(0, |g| grown(g.lifetime as i32, f.charge) as u16),
                    charge: f.charge,
                });
                if let Some(g) = growth
                    && f.charge > 0
                {
                    f.recoil(g.recoil * Fx::int(f.charge as i32) / Fx::int(MAX_CHARGE as i32));
                }
            }
        }
    }

    /// Detects every hit and grab first and applies them afterwards, so two attacks
    /// that connect on the same frame trade instead of depending on player order.
    fn resolve_hits(&mut self, bursts: &[Burst]) {
        let mut strikes: Vec<Strike> = Vec::new();
        for (ai, attacker) in self.fighters.iter().enumerate() {
            let State::Attack { mv, hit_mask, .. } = attacker.state else { continue };
            let growth = mv.data().charge_growth.as_ref();
            for (hb, x, y) in active_hitboxes(attacker) {
                for (di, defender) in self.fighters.iter().enumerate() {
                    let already_hit = hit_mask & (1 << di) != 0
                        || strikes.iter().any(|s| s.projectile.is_none() && s.attacker == ai && s.defender == di);
                    if di != ai && !already_hit && defender.hittable() && defender.hurtbox_overlaps(x, y, hb.radius) {
                        strikes.push(Strike {
                            attacker: ai,
                            defender: di,
                            x,
                            y,
                            damage: attacker.charged(hb.damage) + growth.map_or(0, |g| grown(g.damage, attacker.charge)),
                            angle: hb.angle,
                            base_kb: hb.base_kb + growth.map_or(0, |g| grown(g.base_kb, attacker.charge)),
                            kb_growth: hb.kb_growth,
                            direction: attacker.facing,
                            projectile: None,
                        });
                    }
                }
            }
        }
        for (pi, p) in self.projectiles.iter().enumerate() {
            let data = p.data();
            let target = (0..self.fighters.len()).find(|&di| {
                let d = &self.fighters[di];
                di != p.owner && d.hittable() && d.hurtbox_overlaps(p.x, p.y, p.radius())
            });
            if let Some(di) = target {
                strikes.push(Strike {
                    attacker: p.owner,
                    defender: di,
                    x: p.x,
                    y: p.y,
                    damage: p.damage(),
                    angle: data.angle,
                    base_kb: p.base_kb(),
                    kb_growth: data.kb_growth,
                    direction: p.vx.signum(),
                    projectile: Some(pi),
                });
            }
        }

        // Shattering projectiles that stopped this frame burst on everyone nearby.
        for b in bursts {
            let s = b.shatter;
            self.events.push(Event::Shatter { owner: b.owner, x: b.x, y: b.y });
            for (di, d) in self.fighters.iter().enumerate() {
                if di != b.owner && d.hittable() && d.hurtbox_overlaps(b.x, b.y, s.radius) {
                    strikes.push(Strike {
                        attacker: b.owner,
                        defender: di,
                        x: b.x,
                        y: b.y,
                        damage: s.damage,
                        angle: s.angle,
                        base_kb: s.base_kb,
                        kb_growth: s.kb_growth,
                        // Sent away from the burst point.
                        direction: if d.x >= b.x { 1 } else { -1 },
                        projectile: None,
                    });
                }
            }
        }

        let mut grabs: Vec<(usize, usize)> = Vec::new();
        for (ai, attacker) in self.fighters.iter().enumerate() {
            let Some((gb, x, y)) = active_grabbox(attacker) else { continue };
            let victim = (0..self.fighters.len()).find(|&di| {
                let d = &self.fighters[di];
                di != ai && d.grabbable() && !(gb.misses_shields && d.shielding()) && d.hurtbox_overlaps(x, y, gb.radius)
            });
            if let Some(di) = victim {
                grabs.push((ai, di));
            }
        }
        // A strike beats a grab on the same frame, two fighters grabbing each other
        // both miss, and a fighter caught twice goes to the lower-numbered grabber.
        let struck = |i: usize| strikes.iter().any(|s| s.defender == i);
        let all_grabs = grabs.clone();
        grabs.retain(|&(a, d)| !struck(a) && !struck(d) && !all_grabs.contains(&(d, a)));
        let mut caught = 0u8;
        grabs.retain(|&(_, d)| {
            let first = caught & (1 << d) == 0;
            caught |= 1 << d;
            first
        });

        let mut spent_projectiles = Vec::new();
        // Fighters that countered a strike this frame ignore the rest of them.
        let mut countered = 0u8;
        for s in strikes {
            if countered & (1 << s.defender) != 0 {
                continue;
            }
            let lag = hitlag_frames(s.damage);
            match s.projectile {
                Some(pi) => spent_projectiles.push(pi),
                None => {
                    let attacker = &mut self.fighters[s.attacker];
                    if let State::Attack { hit_mask, .. } = &mut attacker.state {
                        *hit_mask |= 1 << s.defender;
                    }
                    attacker.hitlag = lag;
                }
            }

            let defender = &mut self.fighters[s.defender];
            defender.hitlag = lag;
            if let Some(into) = defender.counter_move() {
                // The strike came from the side opposite the way it sends.
                defender.facing = -s.direction;
                defender.start_attack(into);
                defender.intangible = COUNTER_INTANGIBLE_FRAMES;
                countered |= 1 << s.defender;
                self.events.push(Event::Counter { fighter: s.defender, attacker: s.attacker, x: s.x, y: s.y });
                continue;
            }
            if defender.shielding() {
                let broke = defender.block(s.damage, s.direction);
                self.events.push(Event::ShieldHit {
                    attacker: s.attacker,
                    defender: s.defender,
                    x: s.x,
                    y: s.y,
                    damage: s.damage,
                    projectile: s.projectile.is_some(),
                });
                if broke {
                    self.events.push(Event::ShieldBreak { fighter: s.defender });
                }
                continue;
            }
            defender.percent = (defender.percent + s.damage).min(999);
            let kb = knockback(defender.percent, s.damage, defender.params.weight, s.base_kb, s.kb_growth);
            defender.take_hit(kb, s.angle, s.direction);
            self.events.push(Event::Hit {
                attacker: s.attacker,
                defender: s.defender,
                x: s.x,
                y: s.y,
                damage: s.damage,
                knockback: kb,
                projectile: s.projectile.is_some(),
            });
        }

        for (ai, di) in grabs {
            let command = match self.fighters[ai].state {
                State::Attack { mv, .. } => mv.data().on_grab,
                _ => None,
            };
            self.fighters[ai].start_holding(di);
            if let Some(next) = command {
                self.fighters[ai].start_attack(next);
            }
            self.fighters[di].get_held(ai);
            self.events.push(Event::Grab { attacker: ai, defender: di });
        }
        self.sync_grabs();

        let mut index = 0;
        self.projectiles.retain(|_| {
            index += 1;
            !spent_projectiles.contains(&(index - 1))
        });
    }

    fn check_blast_zones(&mut self) {
        let s = &self.stage;
        for (i, f) in self.fighters.iter_mut().enumerate() {
            if matches!(f.state, State::Respawning { .. } | State::Eliminated) {
                continue;
            }
            if f.x < s.blast_left || f.x > s.blast_right || f.y > s.blast_top || f.y < s.blast_bottom {
                f.ko(s);
                self.events.push(Event::Ko { fighter: i });
            }
        }
    }
}

/// Mutable references to two different fighters.
fn pair_mut(fighters: &mut [Fighter], a: usize, b: usize) -> (&mut Fighter, &mut Fighter) {
    assert_ne!(a, b);
    if a < b {
        let (left, right) = fighters.split_at_mut(b);
        (&mut left[a], &mut right[0])
    } else {
        let (left, right) = fighters.split_at_mut(a);
        (&mut right[0], &mut left[b])
    }
}

fn active_hitboxes(f: &Fighter) -> impl Iterator<Item = (&'static Hitbox, Fx, Fx)> + '_ {
    let (hitboxes, frame): (&'static [Hitbox], u16) = match f.state {
        State::Attack { mv, frame, .. } => (mv.data().hitboxes, frame),
        _ => (&[], 0),
    };
    hitboxes
        .iter()
        .filter(move |hb| (hb.first..=hb.last).contains(&frame))
        .map(move |hb| (hb, f.x + hb.x * f.facing, f.y + hb.y))
}

fn active_grabbox(f: &Fighter) -> Option<(&'static GrabBox, Fx, Fx)> {
    let State::Attack { mv, frame, .. } = f.state else { return None };
    let gb = mv.data().grabbox.as_ref()?;
    (gb.first..=gb.last).contains(&frame).then(|| (gb, f.x + gb.x * f.facing, f.y + gb.y))
}
