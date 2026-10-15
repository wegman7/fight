//! Frame data. Frames are 1-based like Smash frame data: frame 1 is the first
//! frame of the move, and a hitbox with `first: 3` is the "frame 3 jab".

use crate::fixed::Fx;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum MoveId {
    Jab,
    FTilt,
    UTilt,
    Nair,
}

#[derive(Debug)]
pub struct Hitbox {
    /// Active from `first` through `last`, inclusive.
    pub first: u16,
    pub last: u16,
    /// Offset from the fighter's feet; `x` is mirrored by facing.
    pub x: Fx,
    pub y: Fx,
    pub radius: Fx,
    pub damage: i32,
    /// Launch angle in degrees: 0 = forward, 90 = straight up.
    pub angle: i32,
    pub base_kb: i32,
    /// Knockback growth, 100 = neutral scaling.
    pub kb_growth: i32,
}

#[derive(Debug)]
pub struct MoveData {
    pub name: &'static str,
    pub total_frames: u16,
    /// Earlier entries win when several hitboxes touch the same target.
    pub hitboxes: &'static [Hitbox],
    pub aerial: bool,
    pub landing_lag: u8,
}

impl MoveId {
    pub fn data(self) -> &'static MoveData {
        match self {
            MoveId::Jab => &JAB,
            MoveId::FTilt => &FTILT,
            MoveId::UTilt => &UTILT,
            MoveId::Nair => &NAIR,
        }
    }
}

static JAB: MoveData = MoveData {
    name: "jab",
    total_frames: 17,
    hitboxes: &[Hitbox {
        first: 2,
        last: 3,
        x: Fx::int(6),
        y: Fx::int(6),
        radius: Fx::ratio(7, 2),
        damage: 3,
        angle: 40,
        base_kb: 8,
        kb_growth: 60,
    }],
    aerial: false,
    landing_lag: 0,
};

static FTILT: MoveData = MoveData {
    name: "ftilt",
    total_frames: 26,
    hitboxes: &[Hitbox {
        first: 5,
        last: 7,
        x: Fx::int(8),
        y: Fx::int(7),
        radius: Fx::int(4),
        damage: 9,
        angle: 35,
        base_kb: 20,
        kb_growth: 100,
    }],
    aerial: false,
    landing_lag: 0,
};

static UTILT: MoveData = MoveData {
    name: "utilt",
    total_frames: 30,
    hitboxes: &[Hitbox {
        first: 5,
        last: 12,
        x: Fx::int(2),
        y: Fx::int(14),
        radius: Fx::int(5),
        damage: 7,
        angle: 85,
        base_kb: 30,
        kb_growth: 110,
    }],
    aerial: false,
    landing_lag: 0,
};

/// A classic "sex kick": strong early, weaker lingering hitbox.
static NAIR: MoveData = MoveData {
    name: "nair",
    total_frames: 36,
    hitboxes: &[
        Hitbox {
            first: 3,
            last: 6,
            x: Fx::int(3),
            y: Fx::int(6),
            radius: Fx::int(6),
            damage: 8,
            angle: 45,
            base_kb: 10,
            kb_growth: 100,
        },
        Hitbox {
            first: 7,
            last: 30,
            x: Fx::int(3),
            y: Fx::int(6),
            radius: Fx::int(5),
            damage: 5,
            angle: 45,
            base_kb: 5,
            kb_growth: 80,
        },
    ],
    aerial: true,
    landing_lag: 15,
};
