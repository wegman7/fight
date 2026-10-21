//! Tuning overrides for the harness. The game reads each fighter's tuning through
//! `Fighter::params` (a `&'static FighterParams`), so an override is a modified copy
//! of the character's source values, leaked once per [`Tuning`] and installed on the
//! fighters after `World::new`. Characters without knobs keep their source params,
//! so an empty `Tuning` plays exactly the shipped game.

use fight_sim::{Character, FighterParams, Fx};

/// Changes to one character's tuning, relative to its values in `sim/src/fighter.rs`.
/// All zero = unchanged.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Knobs {
    /// Added to `damage_scale` (percentage points of the damage its moves deal).
    pub damage: i32,
    /// Added to `knockback_scale` (percentage points of the knockback its hits deal).
    pub knockback: i32,
    /// Added to `weight` (100 = average; heavier takes less knockback).
    pub weight: i32,
    /// Percent change to `walk_speed`, `run_speed`, `air_speed` and `jump_h_speed`.
    pub speed: i32,
}

impl Knobs {
    pub fn is_zero(&self) -> bool {
        *self == Knobs::default()
    }

    /// `base` with these knobs applied.
    pub fn apply(&self, base: &FighterParams) -> FighterParams {
        let speed = |v: Fx| if self.speed == 0 { v } else { v * Fx::ratio(100 + self.speed as i64, 100) };
        FighterParams {
            damage_scale: base.damage_scale + self.damage,
            knockback_scale: base.knockback_scale + self.knockback,
            weight: base.weight + self.weight,
            walk_speed: speed(base.walk_speed),
            run_speed: speed(base.run_speed),
            air_speed: speed(base.air_speed),
            jump_h_speed: speed(base.jump_h_speed),
            ..base.clone()
        }
    }

    /// Parses `damage=+4,weight=-3` (signs optional; also `knockback`, `speed`).
    pub fn parse(spec: &str) -> Result<Knobs, String> {
        let mut knobs = Knobs::default();
        for part in spec.split(',').filter(|p| !p.is_empty()) {
            let (name, value) = part.split_once('=').ok_or_else(|| format!("expected knob=value, got `{part}`"))?;
            let value: i32 = value.trim_start_matches('+').parse().map_err(|_| format!("bad number in `{part}`"))?;
            match name {
                "damage" => knobs.damage = value,
                "knockback" => knobs.knockback = value,
                "weight" => knobs.weight = value,
                "speed" => knobs.speed = value,
                _ => return Err(format!("unknown knob `{name}` (damage, knockback, weight, speed)")),
            }
        }
        Ok(knobs)
    }
}

impl std::fmt::Display for Knobs {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let parts: Vec<String> = [("damage", self.damage), ("knockback", self.knockback), ("weight", self.weight), ("speed", self.speed)]
            .iter()
            .filter(|(_, v)| *v != 0)
            .map(|(n, v)| format!("{n}={v:+}"))
            .collect();
        if parts.is_empty() { write!(f, "unchanged") } else { write!(f, "{}", parts.join(",")) }
    }
}

/// Knobs for any number of characters, with their params built once.
#[derive(Clone, Debug, Default)]
pub struct Tuning {
    entries: Vec<(Character, Knobs, &'static FighterParams)>,
}

impl Tuning {
    pub fn new(knobs: &[(Character, Knobs)]) -> Tuning {
        let mut tuning = Tuning::default();
        for &(c, k) in knobs {
            tuning.set(c, k);
        }
        tuning
    }

    /// Replaces `c`'s knobs. Leaks one `FighterParams` when they aren't all zero:
    /// the game holds params as `&'static`, and the harness makes only a handful.
    pub fn set(&mut self, c: Character, knobs: Knobs) {
        self.entries.retain(|(e, _, _)| *e != c);
        if !knobs.is_zero() {
            let params: &'static FighterParams = Box::leak(Box::new(knobs.apply(c.params())));
            self.entries.push((c, knobs, params));
        }
    }

    pub fn knobs(&self, c: Character) -> Knobs {
        self.entries.iter().find(|(e, _, _)| *e == c).map_or(Knobs::default(), |&(_, k, _)| k)
    }

    /// The params `c` plays with: its source values unless it has knobs.
    pub fn params(&self, c: Character) -> &'static FighterParams {
        self.entries.iter().find(|(e, _, _)| *e == c).map_or(c.params(), |&(_, _, p)| p)
    }

    /// Characters with knobs, in `Character::ALL` order.
    pub fn changed(&self) -> Vec<(Character, Knobs)> {
        Character::ALL.iter().filter_map(|&c| self.entries.iter().find(|(e, _, _)| *e == c).map(|&(_, k, _)| (c, k))).collect()
    }
}
