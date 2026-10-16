use crate::fighter::{Fighter, FighterParams, GRAB_HOLD_DISTANCE, State, hitlag_frames, knockback};
use crate::fixed::Fx;
use crate::input::Input;
use crate::moves::{GrabBox, Hitbox, MoveId, ProjectileData};
use crate::stage::Stage;

pub const MAX_FIGHTERS: usize = 4;

/// Things that happened during the last [`World::step`], for effects and sound.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Event {
    Hit { attacker: usize, defender: usize, x: Fx, y: Fx, damage: i32, knockback: Fx },
    /// A hit that landed on a shield.
    ShieldHit { attacker: usize, defender: usize, x: Fx, y: Fx, damage: i32 },
    ShieldBreak { fighter: usize },
    Grab { attacker: usize, defender: usize },
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

/// A projectile in flight. Its numbers come from `mv`'s [`ProjectileData`].
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Projectile {
    pub owner: usize,
    pub mv: MoveId,
    pub x: Fx,
    pub y: Fx,
    pub vx: Fx,
    pub frames_left: u16,
}

impl Projectile {
    pub fn data(&self) -> &'static ProjectileData {
        self.mv.data().projectile.as_ref().expect("projectile move without ProjectileData")
    }
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

impl World {
    pub fn new(stage: Stage, players: usize, stocks: u8) -> World {
        assert!(players <= MAX_FIGHTERS && players <= stage.spawns.len());
        let fighters = (0..players)
            .map(|i| {
                let (x, y) = stage.spawns[i];
                let facing = if x <= Fx::ZERO { 1 } else { -1 };
                Fighter::new(&FighterParams::DEFAULT, x, y, facing, &stage, stocks)
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
        self.move_projectiles();
        self.fire_projectiles();
        self.resolve_hits();
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
                State::Attack { mv, .. } => mv.data().throw.is_some(),
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
            let (Some(throw), Some(v)) = (&mv.data().throw, f.holding) else { continue };
            if !f.frame_advanced || throw.frame != frame {
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
            self.events.push(Event::Hit { attacker: i, defender: v, x, y, damage: throw.damage, knockback: kb });
        }
    }

    fn move_projectiles(&mut self) {
        let s = &self.stage;
        for p in &mut self.projectiles {
            p.x += p.vx;
            p.frames_left = p.frames_left.saturating_sub(1);
        }
        self.projectiles.retain(|p| p.frames_left > 0 && p.x > s.blast_left && p.x < s.blast_right);
    }

    fn fire_projectiles(&mut self) {
        for (owner, f) in self.fighters.iter().enumerate() {
            let State::Attack { mv, frame, .. } = f.state else { continue };
            let Some(data) = &mv.data().projectile else { continue };
            if f.frame_advanced && data.frame == frame {
                self.projectiles.push(Projectile {
                    owner,
                    mv,
                    x: f.x + data.x * f.facing,
                    y: f.y + data.y,
                    vx: data.speed * f.facing,
                    frames_left: data.lifetime,
                });
            }
        }
    }

    /// Detects every hit and grab first and applies them afterwards, so two attacks
    /// that connect on the same frame trade instead of depending on player order.
    fn resolve_hits(&mut self) {
        let mut strikes: Vec<Strike> = Vec::new();
        for (ai, attacker) in self.fighters.iter().enumerate() {
            let State::Attack { hit_mask, .. } = attacker.state else { continue };
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
                            damage: attacker.charged(hb.damage),
                            angle: hb.angle,
                            base_kb: hb.base_kb,
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
                di != p.owner && d.hittable() && d.hurtbox_overlaps(p.x, p.y, data.radius)
            });
            if let Some(di) = target {
                strikes.push(Strike {
                    attacker: p.owner,
                    defender: di,
                    x: p.x,
                    y: p.y,
                    damage: data.damage,
                    angle: data.angle,
                    base_kb: data.base_kb,
                    kb_growth: data.kb_growth,
                    direction: p.vx.signum(),
                    projectile: Some(pi),
                });
            }
        }

        let mut grabs: Vec<(usize, usize)> = Vec::new();
        for (ai, attacker) in self.fighters.iter().enumerate() {
            let Some((gb, x, y)) = active_grabbox(attacker) else { continue };
            let victim = (0..self.fighters.len()).find(|&di| {
                let d = &self.fighters[di];
                di != ai && d.grabbable() && d.hurtbox_overlaps(x, y, gb.radius)
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
        for s in strikes {
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
            if defender.shielding() {
                let broke = defender.block(s.damage, s.direction);
                self.events.push(Event::ShieldHit { attacker: s.attacker, defender: s.defender, x: s.x, y: s.y, damage: s.damage });
                if broke {
                    self.events.push(Event::ShieldBreak { fighter: s.defender });
                }
                continue;
            }
            defender.percent = (defender.percent + s.damage).min(999);
            let kb = knockback(defender.percent, s.damage, defender.params.weight, s.base_kb, s.kb_growth);
            defender.take_hit(kb, s.angle, s.direction);
            self.events.push(Event::Hit { attacker: s.attacker, defender: s.defender, x: s.x, y: s.y, damage: s.damage, knockback: kb });
        }

        for (ai, di) in grabs {
            self.fighters[ai].start_holding(di);
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
