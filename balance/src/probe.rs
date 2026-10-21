//! Diagnostics that look at the CPU's play directly rather than through match results.

use fight_sim::{Character, Cpu, CpuLevel, Fx, Input, State, StageId, World};

use crate::tuning::Tuning;

/// Farthest distance tried, in units past the ledge (one-unit steps).
const PROBE_MAX: i32 = 150;
/// Frames the CPU gets to make it back.
const PROBE_FRAMES: u32 = 600;

/// Where a top-level CPU makes it back from, starting at stage height past the main
/// stage's right ledge, still in the air with every jump left.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Recovery {
    /// The farthest distance (units past the ledge) it still makes it back from.
    /// Nobody edge-guards in CPU play, so this is most of what decides how long a
    /// character survives: short reach loses stocks off the bottom long before percent
    /// would KO.
    pub reach: i32,
    /// Distances closer than `reach` it does *not* make it back from. Failing closer
    /// in than it succeeds is a bug (the CPU's recovery or the ledge grab), not a
    /// character trait.
    pub gaps: Vec<i32>,
}

impl Recovery {
    /// The gaps as `a-b` ranges, e.g. `34-39, 52`.
    pub fn gap_ranges(&self) -> String {
        let mut ranges: Vec<(i32, i32)> = Vec::new();
        for &g in &self.gaps {
            match ranges.last_mut() {
                Some((_, end)) if *end + 1 == g => *end = g,
                _ => ranges.push((g, g)),
            }
        }
        ranges.iter().map(|&(a, b)| if a == b { a.to_string() } else { format!("{a}-{b}") }).collect::<Vec<_>>().join(", ")
    }
}

/// Probes `c`'s recovery (with `tuning`'s params) at every whole unit out to 150.
pub fn recovery(c: Character, stage: StageId, tuning: &Tuning) -> Recovery {
    let made_it: Vec<bool> = (0..=PROBE_MAX).map(|dx| recovers(c, stage, tuning, Fx::int(dx))).collect();
    let reach = made_it.iter().rposition(|&ok| ok).map_or(-1, |i| i as i32);
    let gaps = (0..reach.max(0)).filter(|&dx| !made_it[dx as usize]).collect();
    Recovery { reach, gaps }
}

fn recovers(c: Character, stage: StageId, tuning: &Tuning, dx: Fx) -> bool {
    let mut w = World::new(stage.stage(), &[Character::Chef, c], 3);
    let right = w.stage.platforms[0].right;
    w.fighters[0].x = w.stage.platforms[0].left + Fx::int(10);
    let f = &mut w.fighters[1];
    f.params = tuning.params(c);
    (f.x, f.y, f.grounded_on, f.state, f.facing) = (right + dx, Fx::ZERO, None, State::Air, -1);
    f.air_jumps_left = f.params.air_jumps;
    let mut cpu = Cpu::with_level(1, CpuLevel::MAX);
    for _ in 0..PROBE_FRAMES {
        let input = cpu.think(&w);
        w.step(&[Input::default(), input]);
        let f = &w.fighters[1];
        if f.stocks < 3 {
            return false;
        }
        if f.grounded() || f.state == State::LedgeHang {
            return true;
        }
    }
    false
}
