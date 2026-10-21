use crate::fixed::Fx;

/// A walkable surface. Only the top is solid; `soft` platforms can also be
/// dropped through by tapping down.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Platform {
    pub left: Fx,
    pub right: Fx,
    pub y: Fx,
    pub soft: bool,
}

impl Platform {
    pub fn contains_x(&self, x: Fx) -> bool {
        x >= self.left && x <= self.right
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Stage {
    pub platforms: Vec<Platform>,
    pub blast_left: Fx,
    pub blast_right: Fx,
    pub blast_top: Fx,
    pub blast_bottom: Fx,
    /// Starting positions; each must sit on a platform.
    pub spawns: Vec<(Fx, Fx)>,
    pub respawn: (Fx, Fx),
}

/// The stages players pick from, in menu order.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum StageId {
    /// Battlefield-style: a main stage and three soft platforms.
    Boardwalk,
    /// Final Destination-style: one wide main stage, nothing else.
    Sandbar,
    /// Smashville-style: a smaller main stage under one soft platform.
    Driftwood,
}

impl StageId {
    pub const ALL: [StageId; 3] = [StageId::Boardwalk, StageId::Sandbar, StageId::Driftwood];

    pub fn name(self) -> &'static str {
        match self {
            StageId::Boardwalk => "Boardwalk",
            StageId::Sandbar => "Sandbar",
            StageId::Driftwood => "Driftwood",
        }
    }

    pub fn stage(self) -> Stage {
        match self {
            StageId::Boardwalk => Stage::battlefield(),
            StageId::Sandbar => Stage::flat(),
            StageId::Driftwood => Stage::single_platform(),
        }
    }
}

/// Stages are laid out at 5/7 of their original size, so characters read 40% larger
/// relative to them (first 5/6, then a further 6/7). Platforms, spawns and the respawn
/// point go through [`s`], keeping the whole layout proportionally smaller instead of
/// rescaling each fighter's tuning. gdext draws the stage models at this scale too.
pub const STAGE_SCALE: Fx = Fx::ratio(5, 7);

/// `x` in stage units, scaled down by [`STAGE_SCALE`].
fn s(x: i32) -> Fx {
    Fx::int(x) * STAGE_SCALE
}

/// Blast zones are in fighter units, not scaled with the layout: how far a hit has to
/// send someone to KO them (and how far below the stage they can still recover from)
/// is set by the fighters' knockback and movement, which the stage scale leaves alone.
/// Top and bottom lines are shared by every stage.
const BLAST_TOP: Fx = Fx::int(167);
const BLAST_BOTTOM: Fx = Fx::int(-90);

fn plat(left: i32, right: i32, y: i32, soft: bool) -> Platform {
    Platform { left: s(left), right: s(right), y: s(y), soft }
}

/// Spawn points on the floor: the first two at `±outer`, the next two at `±inner`.
fn spawns(outer: i32, inner: i32) -> Vec<(Fx, Fx)> {
    [-outer, outer, -inner, inner].into_iter().map(|x| (s(x), Fx::ZERO)).collect()
}

impl Stage {
    /// A Battlefield-style layout: one main stage and three soft platforms.
    pub fn battlefield() -> Stage {
        Stage {
            platforms: vec![
                plat(-68, 68, 0, false),
                plat(-57, -20, 27, true),
                plat(20, 57, 27, true),
                plat(-18, 18, 54, true),
            ],
            blast_left: Fx::int(-187),
            blast_right: Fx::int(187),
            blast_top: BLAST_TOP,
            blast_bottom: BLAST_BOTTOM,
            spawns: spawns(40, 15),
            respawn: (Fx::ZERO, s(80)),
        }
    }

    /// A Final Destination-style layout: one wide main stage and no platforms.
    pub fn flat() -> Stage {
        Stage {
            platforms: vec![plat(-85, 85, 0, false)],
            blast_left: Fx::int(-200),
            blast_right: Fx::int(200),
            blast_top: BLAST_TOP,
            blast_bottom: BLAST_BOTTOM,
            spawns: spawns(50, 17),
            respawn: (Fx::ZERO, s(80)),
        }
    }

    /// A Smashville-style layout: a smaller main stage under one soft platform.
    pub fn single_platform() -> Stage {
        Stage {
            platforms: vec![plat(-60, 60, 0, false), plat(-24, 24, 32, true)],
            blast_left: Fx::int(-180),
            blast_right: Fx::int(180),
            blast_top: BLAST_TOP,
            blast_bottom: BLAST_BOTTOM,
            spawns: spawns(35, 12),
            respawn: (Fx::ZERO, s(80)),
        }
    }

    pub fn platform_under(&self, x: Fx, y: Fx) -> Option<usize> {
        self.platforms
            .iter()
            .position(|p| p.y == y && p.contains_x(x))
    }
}
