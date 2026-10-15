use crate::fighter::{Fighter, FighterParams, State, hitlag_frames, knockback};
use crate::fixed::Fx;
use crate::input::Input;
use crate::moves::Hitbox;
use crate::stage::Stage;

pub const MAX_FIGHTERS: usize = 4;

/// Things that happened during the last [`World::step`], for effects and sound.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Event {
    Hit { attacker: usize, defender: usize, x: Fx, y: Fx, damage: i32, knockback: Fx },
    Ko { fighter: usize },
}

/// A hitbox in world space, for debug drawing.
#[derive(Clone, Copy, Debug)]
pub struct ActiveHitbox {
    pub owner: usize,
    pub x: Fx,
    pub y: Fx,
    pub radius: Fx,
}

/// The whole game state. Cloning it is a complete snapshot (for rollback).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct World {
    pub frame: u32,
    pub stage: Stage,
    pub fighters: Vec<Fighter>,
    pub events: Vec<Event>,
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
        World { frame: 0, stage, fighters, events: Vec::new() }
    }

    /// Advances one frame (1/60 s). `inputs[i]` drives fighter `i`.
    pub fn step(&mut self, inputs: &[Input]) {
        self.frame += 1;
        self.events.clear();
        for (i, fighter) in self.fighters.iter_mut().enumerate() {
            fighter.step(inputs.get(i).copied().unwrap_or_default(), &self.stage);
        }
        self.resolve_hits();
        self.check_blast_zones();
    }

    pub fn active_hitboxes(&self) -> Vec<ActiveHitbox> {
        let mut out = Vec::new();
        for (owner, f) in self.fighters.iter().enumerate() {
            for (hb, x, y) in active_hitboxes(f) {
                out.push(ActiveHitbox { owner, x, y, radius: hb.radius });
            }
        }
        out
    }

    /// Detects every hit first and applies them afterwards, so two attacks
    /// that connect on the same frame trade instead of depending on player order.
    fn resolve_hits(&mut self) {
        let mut hits: Vec<(usize, usize, &'static Hitbox, Fx, Fx)> = Vec::new();
        for (ai, attacker) in self.fighters.iter().enumerate() {
            let State::Attack { hit_mask, .. } = attacker.state else { continue };
            for (hb, x, y) in active_hitboxes(attacker) {
                for (di, defender) in self.fighters.iter().enumerate() {
                    let already_hit = hit_mask & (1 << di) != 0 || hits.iter().any(|h| h.0 == ai && h.1 == di);
                    if di != ai && !already_hit && defender.hittable() && defender.hurtbox_overlaps(x, y, hb.radius) {
                        hits.push((ai, di, hb, x, y));
                    }
                }
            }
        }

        for (ai, di, hb, x, y) in hits {
            let direction = self.fighters[ai].facing;
            let lag = hitlag_frames(hb.damage);
            let attacker = &mut self.fighters[ai];
            if let State::Attack { hit_mask, .. } = &mut attacker.state {
                *hit_mask |= 1 << di;
            }
            attacker.hitlag = lag;

            let defender = &mut self.fighters[di];
            defender.percent = (defender.percent + hb.damage).min(999);
            let kb = knockback(defender.percent, hb.damage, defender.params.weight, hb.base_kb, hb.kb_growth);
            defender.take_hit(kb, hb.angle, direction);
            defender.hitlag = lag;
            self.events.push(Event::Hit { attacker: ai, defender: di, x, y, damage: hb.damage, knockback: kb });
        }
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
