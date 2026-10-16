//! Frame data. Frames are 1-based like Smash frame data: frame 1 is the first
//! frame of the move, and a hitbox with `first: 3` is the "frame 3 jab".
//! Offsets are from the fighter's feet with `x` pointing forward (mirrored by facing).

use crate::fixed::Fx;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum MoveId {
    Jab,
    Jab2,
    Jab3,
    FTilt,
    UTilt,
    DTilt,
    DashAttack,
    FSmash,
    USmash,
    DSmash,
    Nair,
    Fair,
    Bair,
    Uair,
    Dair,
    NeutralSpecial,
    SideSpecial,
    UpSpecial,
    DownSpecial,
    /// The shockwave when the down special hits the ground.
    DownSpecialLanding,
    Grab,
    DashGrab,
    Pummel,
    FThrow,
    BThrow,
    UThrow,
    DThrow,
}

#[derive(Debug)]
pub struct Hitbox {
    /// Active from `first` through `last`, inclusive.
    pub first: u16,
    pub last: u16,
    pub x: Fx,
    pub y: Fx,
    pub radius: Fx,
    pub damage: i32,
    /// Launch angle in degrees: 0 = forward, 90 = straight up, 180 = backward, 270 = down (a meteor).
    pub angle: i32,
    pub base_kb: i32,
    /// Knockback growth, 100 = neutral scaling.
    pub kb_growth: i32,
}

/// Catches instead of hitting. Grabs go through shields.
#[derive(Debug)]
pub struct GrabBox {
    pub first: u16,
    pub last: u16,
    pub x: Fx,
    pub y: Fx,
    pub radius: Fx,
}

/// Sets the fighter's velocity on frames `first..=last`. `vx` is forward (mirrored
/// by facing). `None` leaves that axis to normal control; a `Some` `vy` also
/// switches gravity off and lifts a grounded fighter off when positive.
#[derive(Debug)]
pub struct Motion {
    pub first: u16,
    pub last: u16,
    pub vx: Option<Fx>,
    pub vy: Option<Fx>,
}

/// Fired on `frame`; flies straight forward until it hits something or `lifetime` runs out.
#[derive(Debug)]
pub struct ProjectileData {
    pub frame: u16,
    pub x: Fx,
    pub y: Fx,
    pub speed: Fx,
    pub lifetime: u16,
    pub radius: Fx,
    pub damage: i32,
    pub angle: i32,
    pub base_kb: i32,
    pub kb_growth: i32,
}

/// Applied to the held opponent on `frame`. A pummel (`release: false`) only deals
/// damage; a throw puts the opponent at `x` and launches them.
#[derive(Debug)]
pub struct Throw {
    pub frame: u16,
    pub release: bool,
    pub x: Fx,
    pub damage: i32,
    pub angle: i32,
    pub base_kb: i32,
    pub kb_growth: i32,
}

/// What happens when the fighter lands partway through the move.
#[derive(Debug)]
pub enum Landing {
    /// Keep going (grounded moves that slid off a ledge).
    Continue,
    /// Stop, with this many frames of landing lag (aerials, specials).
    Lag(u8),
    /// Switch to another move (the down special's shockwave).
    Into(MoveId),
}

#[derive(Debug)]
pub struct MoveData {
    pub name: &'static str,
    pub total_frames: u16,
    /// Earlier entries win when several hitboxes touch the same target.
    pub hitboxes: &'static [Hitbox],
    pub grabbox: Option<GrabBox>,
    pub motion: &'static [Motion],
    pub projectile: Option<ProjectileData>,
    pub throw: Option<Throw>,
    pub landing: Landing,
    /// Smash attacks: holding the button freezes the move on this frame to charge it.
    pub charge_frame: Option<u16>,
    /// Pressing attack from this frame on cancels into the next hit of a combo.
    pub combo: Option<(MoveId, u16)>,
    /// Ends in helpless special fall when it finishes in the air.
    pub special_fall: bool,
}

const BASE: MoveData = MoveData {
    name: "",
    total_frames: 0,
    hitboxes: &[],
    grabbox: None,
    motion: &[],
    projectile: None,
    throw: None,
    landing: Landing::Continue,
    charge_frame: None,
    combo: None,
    special_fall: false,
};

impl MoveId {
    pub fn data(self) -> &'static MoveData {
        match self {
            MoveId::Jab => &JAB,
            MoveId::Jab2 => &JAB2,
            MoveId::Jab3 => &JAB3,
            MoveId::FTilt => &FTILT,
            MoveId::UTilt => &UTILT,
            MoveId::DTilt => &DTILT,
            MoveId::DashAttack => &DASH_ATTACK,
            MoveId::FSmash => &FSMASH,
            MoveId::USmash => &USMASH,
            MoveId::DSmash => &DSMASH,
            MoveId::Nair => &NAIR,
            MoveId::Fair => &FAIR,
            MoveId::Bair => &BAIR,
            MoveId::Uair => &UAIR,
            MoveId::Dair => &DAIR,
            MoveId::NeutralSpecial => &NEUTRAL_SPECIAL,
            MoveId::SideSpecial => &SIDE_SPECIAL,
            MoveId::UpSpecial => &UP_SPECIAL,
            MoveId::DownSpecial => &DOWN_SPECIAL,
            MoveId::DownSpecialLanding => &DOWN_SPECIAL_LANDING,
            MoveId::Grab => &GRAB,
            MoveId::DashGrab => &DASH_GRAB,
            MoveId::Pummel => &PUMMEL,
            MoveId::FThrow => &FTHROW,
            MoveId::BThrow => &BTHROW,
            MoveId::UThrow => &UTHROW,
            MoveId::DThrow => &DTHROW,
        }
    }
}

/// Hitbox shorthand: frames, offset, size, then damage and launch.
#[allow(clippy::too_many_arguments)]
const fn hit(first: u16, last: u16, x: Fx, y: Fx, radius: Fx, damage: i32, angle: i32, base_kb: i32, kb_growth: i32) -> Hitbox {
    Hitbox { first, last, x, y, radius, damage, angle, base_kb, kb_growth }
}

const fn int(n: i32) -> Fx {
    Fx::int(n)
}

const fn half(n: i64) -> Fx {
    Fx::ratio(n, 2)
}

// --- Ground normals ---------------------------------------------------------

static JAB: MoveData = MoveData {
    name: "jab",
    total_frames: 17,
    hitboxes: &[hit(2, 3, int(6), int(6), half(7), 3, 40, 8, 60)],
    combo: Some((MoveId::Jab2, 5)),
    ..BASE
};

static JAB2: MoveData = MoveData {
    name: "jab2",
    total_frames: 18,
    hitboxes: &[hit(3, 4, half(13), int(6), half(7), 2, 40, 8, 50)],
    combo: Some((MoveId::Jab3, 5)),
    ..BASE
};

/// Combo finisher: a kick that sends.
static JAB3: MoveData = MoveData {
    name: "jab3",
    total_frames: 30,
    hitboxes: &[hit(4, 6, int(7), int(5), half(9), 5, 40, 40, 100)],
    ..BASE
};

static FTILT: MoveData = MoveData {
    name: "ftilt",
    total_frames: 26,
    hitboxes: &[hit(5, 7, int(8), int(7), int(4), 9, 35, 20, 100)],
    ..BASE
};

static UTILT: MoveData = MoveData {
    name: "utilt",
    total_frames: 30,
    hitboxes: &[hit(5, 12, int(2), int(14), int(5), 7, 85, 30, 110)],
    ..BASE
};

/// A low sweep from a crouch.
static DTILT: MoveData = MoveData {
    name: "dtilt",
    total_frames: 22,
    hitboxes: &[hit(5, 7, int(8), int(2), int(4), 6, 80, 30, 70)],
    ..BASE
};

/// Shoulder charge out of a run; the fighter keeps sliding on its run momentum.
static DASH_ATTACK: MoveData = MoveData {
    name: "dashattack",
    total_frames: 38,
    hitboxes: &[hit(6, 9, int(6), int(6), int(5), 10, 50, 40, 70), hit(10, 16, int(5), int(6), int(4), 6, 55, 30, 50)],
    ..BASE
};

// --- Smash attacks ----------------------------------------------------------

static FSMASH: MoveData = MoveData {
    name: "fsmash",
    total_frames: 48,
    hitboxes: &[hit(14, 16, int(10), int(7), int(5), 15, 38, 30, 105)],
    charge_frame: Some(10),
    ..BASE
};

static USMASH: MoveData = MoveData {
    name: "usmash",
    total_frames: 46,
    hitboxes: &[hit(11, 12, int(5), int(10), int(6), 14, 88, 32, 100), hit(11, 15, int(1), int(15), int(6), 14, 88, 32, 100)],
    charge_frame: Some(7),
    ..BASE
};

/// Hits both sides, each sending its own way.
static DSMASH: MoveData = MoveData {
    name: "dsmash",
    total_frames: 44,
    hitboxes: &[hit(8, 10, int(8), int(2), int(5), 13, 30, 25, 100), hit(8, 10, int(-8), int(2), int(5), 13, 150, 25, 100)],
    charge_frame: Some(5),
    ..BASE
};

// --- Aerials ----------------------------------------------------------------

/// A classic "sex kick": strong early, weaker lingering hitbox.
static NAIR: MoveData = MoveData {
    name: "nair",
    total_frames: 36,
    hitboxes: &[hit(3, 6, int(3), int(6), int(6), 8, 45, 10, 100), hit(7, 30, int(3), int(6), int(5), 5, 45, 5, 80)],
    landing: Landing::Lag(15),
    ..BASE
};

static FAIR: MoveData = MoveData {
    name: "fair",
    total_frames: 40,
    hitboxes: &[hit(8, 11, int(7), int(6), half(9), 11, 40, 25, 95)],
    landing: Landing::Lag(16),
    ..BASE
};

/// Kicks behind; the angle points backward.
static BAIR: MoveData = MoveData {
    name: "bair",
    total_frames: 34,
    hitboxes: &[hit(6, 9, int(-7), int(6), half(9), 12, 140, 25, 100)],
    landing: Landing::Lag(12),
    ..BASE
};

static UAIR: MoveData = MoveData {
    name: "uair",
    total_frames: 32,
    hitboxes: &[hit(5, 9, int(1), int(15), int(5), 9, 85, 25, 95)],
    landing: Landing::Lag(10),
    ..BASE
};

/// A stomp that meteors (sends straight down).
static DAIR: MoveData = MoveData {
    name: "dair",
    total_frames: 44,
    hitboxes: &[hit(12, 15, int(1), int(-1), half(9), 13, 270, 20, 90)],
    landing: Landing::Lag(20),
    ..BASE
};

// --- Specials ---------------------------------------------------------------

/// Energy shot: a slow projectile.
static NEUTRAL_SPECIAL: MoveData = MoveData {
    name: "special_n",
    total_frames: 36,
    projectile: Some(ProjectileData {
        frame: 12,
        x: int(8),
        y: int(7),
        speed: Fx::ratio(22, 10),
        lifetime: 70,
        radius: int(3),
        damage: 6,
        angle: 40,
        base_kb: 20,
        kb_growth: 50,
    }),
    landing: Landing::Lag(8),
    ..BASE
};

/// Lunge: hangs in place, then dashes forward fist-first. Once per airtime.
static SIDE_SPECIAL: MoveData = MoveData {
    name: "special_s",
    total_frames: 40,
    hitboxes: &[hit(9, 15, int(6), int(7), int(5), 10, 40, 35, 85)],
    motion: &[
        Motion { first: 1, last: 7, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 8, last: 16, vx: Some(Fx::ratio(24, 10)), vy: Some(Fx::ZERO) },
    ],
    landing: Landing::Lag(12),
    ..BASE
};

/// Rising uppercut, the recovery move: about 38 units up, steerable left and right.
static UP_SPECIAL: MoveData = MoveData {
    name: "special_u",
    total_frames: 40,
    hitboxes: &[hit(4, 6, int(4), int(12), int(5), 9, 80, 40, 80), hit(7, 14, int(2), int(14), int(4), 4, 80, 20, 60)],
    motion: &[
        Motion { first: 1, last: 3, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 4, last: 16, vx: None, vy: Some(Fx::ratio(24, 10)) },
        Motion { first: 17, last: 18, vx: None, vy: Some(Fx::ratio(8, 10)) },
    ],
    landing: Landing::Lag(20),
    special_fall: true,
    ..BASE
};

/// Ground pound: hop, stall, then plunge with a meteor hitbox. Hitting the ground
/// makes a shockwave. Used off-stage, it falls all the way down.
static DOWN_SPECIAL: MoveData = MoveData {
    name: "special_d",
    total_frames: 70,
    hitboxes: &[hit(15, 70, int(0), int(2), int(5), 10, 270, 30, 70)],
    motion: &[
        Motion { first: 1, last: 8, vx: Some(Fx::ZERO), vy: Some(Fx::ratio(16, 10)) },
        Motion { first: 9, last: 14, vx: Some(Fx::ZERO), vy: Some(Fx::ratio(2, 10)) },
        Motion { first: 15, last: 70, vx: Some(Fx::ZERO), vy: Some(Fx::ratio(-32, 10)) },
    ],
    landing: Landing::Into(MoveId::DownSpecialLanding),
    special_fall: true,
    ..BASE
};

static DOWN_SPECIAL_LANDING: MoveData = MoveData {
    name: "special_d_land",
    total_frames: 30,
    hitboxes: &[hit(1, 3, int(5), int(3), int(6), 8, 50, 40, 60), hit(1, 3, int(-5), int(3), int(6), 8, 130, 40, 60)],
    ..BASE
};

// --- Grabs and throws -------------------------------------------------------

static GRAB: MoveData = MoveData {
    name: "grab",
    total_frames: 30,
    grabbox: Some(GrabBox { first: 7, last: 8, x: int(7), y: int(6), radius: int(4) }),
    ..BASE
};

/// Longer reach out of a run, more lag on a whiff.
static DASH_GRAB: MoveData = MoveData {
    name: "dashgrab",
    total_frames: 40,
    grabbox: Some(GrabBox { first: 9, last: 10, x: int(9), y: int(6), radius: half(9) }),
    ..BASE
};

static PUMMEL: MoveData = MoveData {
    name: "pummel",
    total_frames: 16,
    throw: Some(Throw { frame: 3, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 }),
    ..BASE
};

static FTHROW: MoveData = MoveData {
    name: "fthrow",
    total_frames: 30,
    throw: Some(Throw { frame: 12, release: true, x: int(9), damage: 8, angle: 45, base_kb: 60, kb_growth: 60 }),
    ..BASE
};

/// The kill throw: swings the opponent around and out behind.
static BTHROW: MoveData = MoveData {
    name: "bthrow",
    total_frames: 36,
    throw: Some(Throw { frame: 15, release: true, x: int(-9), damage: 10, angle: 135, base_kb: 55, kb_growth: 75 }),
    ..BASE
};

static UTHROW: MoveData = MoveData {
    name: "uthrow",
    total_frames: 34,
    throw: Some(Throw { frame: 14, release: true, x: int(2), damage: 7, angle: 90, base_kb: 65, kb_growth: 65 }),
    ..BASE
};

/// Low knockback that pops the opponent up in front: the combo throw.
static DTHROW: MoveData = MoveData {
    name: "dthrow",
    total_frames: 32,
    throw: Some(Throw { frame: 13, release: true, x: int(7), damage: 6, angle: 75, base_kb: 50, kb_growth: 40 }),
    ..BASE
};

// --- Dodges -----------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum DodgeKind {
    Spot,
    /// Rolls past the way the fighter faces and ends turned around.
    RollForward,
    RollBack,
    /// Air dodge with a neutral stick: stays in place (drift allowed).
    Air,
    /// Air dodge with a direction: a burst of speed that slows to a stop, no gravity meanwhile.
    AirDirectional,
}

#[derive(Debug)]
pub struct DodgeData {
    pub name: &'static str,
    pub total_frames: u16,
    /// Invincible on these frames, inclusive.
    pub intangible: (u16, u16),
    /// Frames on which the dodge moves the fighter (rolls: at `speed`, forward;
    /// directional air dodge: decelerating from `speed` to zero).
    pub moving: (u16, u16),
    pub speed: Fx,
}

impl DodgeKind {
    pub fn data(self) -> &'static DodgeData {
        match self {
            DodgeKind::Spot => &SPOT_DODGE,
            DodgeKind::RollForward => &ROLL_FORWARD,
            DodgeKind::RollBack => &ROLL_BACK,
            DodgeKind::Air => &AIR_DODGE,
            DodgeKind::AirDirectional => &AIR_DODGE_DIRECTIONAL,
        }
    }

    pub fn aerial(self) -> bool {
        matches!(self, DodgeKind::Air | DodgeKind::AirDirectional)
    }
}

static SPOT_DODGE: DodgeData = DodgeData { name: "spotdodge", total_frames: 26, intangible: (3, 17), moving: (0, 0), speed: Fx::ZERO };
static ROLL_FORWARD: DodgeData =
    DodgeData { name: "roll_f", total_frames: 32, intangible: (4, 15), moving: (4, 20), speed: Fx::ratio(16, 10) };
static ROLL_BACK: DodgeData = DodgeData { name: "roll_b", total_frames: 32, intangible: (4, 15), moving: (4, 20), speed: Fx::ratio(-16, 10) };
static AIR_DODGE: DodgeData = DodgeData { name: "airdodge", total_frames: 40, intangible: (3, 25), moving: (0, 0), speed: Fx::ZERO };
static AIR_DODGE_DIRECTIONAL: DodgeData =
    DodgeData { name: "airdodge", total_frames: 34, intangible: (3, 18), moving: (1, 20), speed: Fx::int(3) };
