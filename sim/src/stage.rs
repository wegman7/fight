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

impl Stage {
    /// A Battlefield-style layout: one main stage and three soft platforms.
    pub fn battlefield() -> Stage {
        let plat = |left, right, y, soft| Platform {
            left: Fx::int(left),
            right: Fx::int(right),
            y: Fx::int(y),
            soft,
        };
        Stage {
            platforms: vec![
                plat(-68, 68, 0, false),
                plat(-57, -20, 27, true),
                plat(20, 57, 27, true),
                plat(-18, 18, 54, true),
            ],
            blast_left: Fx::int(-224),
            blast_right: Fx::int(224),
            blast_top: Fx::int(200),
            blast_bottom: Fx::int(-108),
            spawns: vec![
                (Fx::int(-40), Fx::ZERO),
                (Fx::int(40), Fx::ZERO),
                (Fx::int(-15), Fx::ZERO),
                (Fx::int(15), Fx::ZERO),
            ],
            respawn: (Fx::ZERO, Fx::int(80)),
        }
    }

    pub fn platform_under(&self, x: Fx, y: Fx) -> Option<usize> {
        self.platforms
            .iter()
            .position(|p| p.y == y && p.contains_x(x))
    }
}
