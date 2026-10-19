//! Frame data. Frames are 1-based like Smash frame data: frame 1 is the first
//! frame of the move, and a hitbox with `first: 3` is the "frame 3 jab".
//! Offsets are from the fighter's feet with `x` pointing forward (mirrored by facing).

use crate::fixed::Fx;
use crate::input::Input;

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
    PieThrow,
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
    // The pug's moves (see `character.rs` for which input starts each).
    PugBite,
    PugBite2,
    PugNibbles,
    PugPawSwipe,
    PugHeadToss,
    PugScoot,
    PugBellySlide,
    PugRam,
    PugHowl,
    PugShake,
    PugTailSpin,
    PugAirHeadbutt,
    PugBuck,
    PugSnap,
    PugPancake,
    PugSneeze,
    PugTackle,
    /// The tackle after it caught someone: rides and bites them.
    PugTackleRide,
    PugEarCopter,
    PugPlayDead,
    /// The play-dead counter's answer: springs up and pounces on the attacker.
    PugPounce,
    PugBiteGrab,
    PugDashBiteGrab,
    PugNom,
    PugToss,
    PugTugSpin,
    PugFlingUp,
    PugSit,
    // The samurai's moves. He also uses the shared `Grab`, `DashGrab` and `Pummel`.
    SamuraiSlash,
    SamuraiSlash2,
    SamuraiThrust,
    SamuraiForwardCut,
    SamuraiRisingCut,
    SamuraiLowCut,
    SamuraiDashCut,
    SamuraiCleave,
    SamuraiSkyCut,
    SamuraiSpinSweep,
    SamuraiAirSpin,
    SamuraiAirCut,
    SamuraiBackCut,
    SamuraiSkyArc,
    SamuraiPlungeStab,
    SamuraiFocusCut,
    SamuraiVault,
    /// The vault's follow-up: a downward strike from the air.
    SamuraiVaultStrike,
    SamuraiCyclone,
    SamuraiParry,
    /// The parry's answer: a quick cut at the attacker.
    SamuraiRiposte,
    SamuraiHipThrow,
    SamuraiShoulderThrow,
    SamuraiTossUp,
    SamuraiPin,
    // The ninja's moves. Unlike the samurai, every slot is his own, including grab,
    // dash grab and pummel.
    NinjaKunai,
    NinjaKunai2,
    NinjaKunai3,
    NinjaPalmThrust,
    NinjaRisingChop,
    NinjaSweep,
    NinjaDashSlice,
    NinjaChop,
    NinjaFlipKick,
    NinjaSpinKick,
    NinjaAirSpin,
    NinjaFlyingKick,
    NinjaBackHook,
    NinjaUpFlip,
    NinjaAxeKick,
    NinjaShuriken,
    NinjaShadowDash,
    NinjaSmokeBomb,
    NinjaSubstitution,
    /// The substitution counter's answer: a strike from behind.
    NinjaSubstitutionStrike,
    NinjaGrab,
    NinjaDashGrab,
    NinjaPummel,
    NinjaThrowForward,
    NinjaThrowBack,
    NinjaThrowUp,
    NinjaThrowDown,
    // The soldier's moves. Every one of the 24 slots is his own, including grab,
    // dash grab, pummel and all four throws (he never uses the chef's shared ones).
    SoldierButtStrike,
    SoldierButtStrike2,
    SoldierBayonet,
    SoldierRifleUp,
    SoldierLegSweep,
    SoldierShoulderCharge,
    SoldierStockSmash,
    SoldierBayonetUpper,
    SoldierStockSweep,
    SoldierAirSpin,
    SoldierAirBayonet,
    SoldierBackElbow,
    SoldierAirUp,
    SoldierAirStomp,
    SoldierRifleShot,
    SoldierGrenade,
    SoldierBlastJump,
    SoldierRiotShield,
    /// The riot shield's answer: blocks the hit and bashes the attacker back.
    SoldierShieldBash,
    SoldierGrab,
    SoldierDashGrab,
    SoldierPummel,
    SoldierThrowForward,
    SoldierThrowBack,
    SoldierThrowUp,
    SoldierThrowDown,
    // The drunk hobo's moves (see `character.rs`). He uses none of the shared moves:
    // even his grab, dash grab and pummel are his own.
    HoboSlap,
    HoboSlap2,
    HoboSlap3,
    HoboPunch,
    HoboUpSwing,
    HoboTrip,
    HoboStumble,
    HoboBottleSwing,
    HoboUpHeave,
    HoboSpinFlail,
    HoboFlail,
    HoboHaymaker,
    HoboBackhand,
    HoboUpFlail,
    HoboStomp,
    HoboBottleThrow,
    HoboCartCharge,
    HoboFizzRocket,
    HoboPassedOut,
    /// The passed-out counter's answer: he jolts awake and swings.
    HoboJolt,
    HoboGrab,
    HoboDashGrab,
    HoboPummel,
    HoboThrowForward,
    HoboThrowBack,
    HoboThrowUp,
    HoboThrowDown,
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

/// Catches instead of hitting. Grabs go through shields, unless `misses_shields`.
#[derive(Debug)]
pub struct GrabBox {
    pub first: u16,
    pub last: u16,
    pub x: Fx,
    pub y: Fx,
    pub radius: Fx,
    /// Shielding fighters aren't caught (the pug's tackle).
    pub misses_shields: bool,
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

/// Fired on `frame`; flies forward at `speed` until it hits something or `lifetime`
/// runs out. With `gravity`, it's lobbed: it starts rising at `vy`, arcs down, and is
/// gone when it lands on a platform.
#[derive(Debug)]
pub struct ProjectileData {
    pub frame: u16,
    pub x: Fx,
    pub y: Fx,
    pub speed: Fx,
    pub vy: Fx,
    pub gravity: Fx,
    pub lifetime: u16,
    pub radius: Fx,
    pub damage: i32,
    pub angle: i32,
    pub base_kb: i32,
    pub kb_growth: i32,
    /// For a move with a `charge_frame`: what the projectile gains when fully charged.
    pub growth: Option<ProjectileGrowth>,
    /// Explodes in a blast instead of a single-target hit (see [`Explosion`]).
    pub explosion: Option<Explosion>,
}

/// Added to a projectile at full charge (`MAX_CHARGE` frames), in proportion to how
/// long the move was charged.
#[derive(Debug)]
pub struct ProjectileGrowth {
    pub radius: Fx,
    pub damage: i32,
    pub base_kb: i32,
    pub lifetime: u16,
    /// Pushes the shooter backward at this speed when it fires.
    pub recoil: Fx,
}

/// An exploding projectile. When it comes down on a platform — or, with
/// `on_contact`, the moment it touches a fighter — it bursts and hits every fighter
/// (except its owner) within `radius` of the blast, instead of just the one it hit.
/// This is a generic mechanic: any character's projectile can carry one.
#[derive(Clone, Copy, Debug)]
pub struct Explosion {
    pub radius: Fx,
    pub damage: i32,
    /// Launch angle in degrees, as on a hitbox (0 = forward, 90 = up).
    pub angle: i32,
    pub base_kb: i32,
    pub kb_growth: i32,
    /// Explode the instant it touches a fighter, not only on landing.
    pub on_contact: bool,
}

/// For a move with a `charge_frame`: what each of its hitboxes gains at full charge
/// (`MAX_CHARGE` frames), in proportion to how long it was charged. On top of the
/// damage every charged move gains.
#[derive(Debug)]
pub struct HitGrowth {
    pub damage: i32,
    pub base_kb: i32,
}

/// A projectile that bursts when it stops: when it comes down on a platform or runs
/// out of lifetime, every fighter within `radius` of where it stopped takes this hit,
/// sent away from the burst point (0 = forward from that point, 90 = up). The
/// projectile's own direct hit is unchanged, and shattering never happens on a direct
/// hit — only when it lands or expires. Declared on the *move* (`MoveData::shatter`),
/// so any character's lobbed projectile can use it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Shatter {
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

/// A counter: hit by an attack (or projectile) on frames `first..=last`, the fighter
/// takes no damage or knockback, turns to face the attacker and switches to `into`,
/// briefly intangible.
#[derive(Debug)]
pub struct Counter {
    pub first: u16,
    pub last: u16,
    pub into: MoveId,
}

/// A move that teleports the fighter on one frame (a smoke-bomb recovery): it moves
/// straight to a new spot instead of travelling there. `dx` is a forward offset
/// (mirrored by facing), `dy` is up.
#[derive(Debug)]
pub struct Teleport {
    pub frame: u16,
    pub dx: Fx,
    pub dy: Fx,
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
    /// When the grab box catches someone, start this move instead of holding (a
    /// command grab). Without it, the grabber holds and picks a pummel or throw.
    pub on_grab: Option<MoveId>,
    pub motion: &'static [Motion],
    pub projectile: Option<ProjectileData>,
    /// A shattering projectile bursts (an area hit) when it lands or expires.
    pub shatter: Option<Shatter>,
    /// Pummels and throws, in frame order. Once one releases, the rest are skipped.
    pub throws: &'static [Throw],
    pub landing: Landing,
    /// Holding `charge_with` freezes the move on this frame to charge it (smash
    /// attacks, the pug's sneeze).
    pub charge_frame: Option<u16>,
    /// The buttons that keep charging: attack or smash for smash attacks.
    pub charge_with: u8,
    pub charge_growth: Option<HitGrowth>,
    /// Pressing attack from this frame on cancels into the next hit of a combo.
    pub combo: Option<(MoveId, u16)>,
    /// Ends in helpless special fall when it finishes in the air.
    pub special_fall: bool,
    pub counter: Option<Counter>,
    /// The fighter turns around on this frame (the samurai's vault, passing over an
    /// opponent). Motion and hitboxes from then on are relative to the new facing.
    pub turn: Option<u16>,
    /// The fighter can't be hit or grabbed on these frames, inclusive (a shadow dash
    /// passing through, a smoke bomb while it vanishes).
    pub intangible: Option<(u16, u16)>,
    /// The fighter teleports on `frame` (a smoke-bomb recovery).
    pub teleport: Option<Teleport>,
}

const BASE: MoveData = MoveData {
    name: "",
    total_frames: 0,
    hitboxes: &[],
    grabbox: None,
    on_grab: None,
    motion: &[],
    projectile: None,
    shatter: None,
    throws: &[],
    landing: Landing::Continue,
    charge_frame: None,
    charge_with: Input::ATTACK | Input::SMASH,
    charge_growth: None,
    combo: None,
    special_fall: false,
    counter: None,
    turn: None,
    intangible: None,
    teleport: None,
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
            MoveId::PieThrow => &PIE_THROW,
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
            MoveId::PugBite => &PUG_BITE,
            MoveId::PugBite2 => &PUG_BITE2,
            MoveId::PugNibbles => &PUG_NIBBLES,
            MoveId::PugPawSwipe => &PUG_PAW_SWIPE,
            MoveId::PugHeadToss => &PUG_HEAD_TOSS,
            MoveId::PugScoot => &PUG_SCOOT,
            MoveId::PugBellySlide => &PUG_BELLY_SLIDE,
            MoveId::PugRam => &PUG_RAM,
            MoveId::PugHowl => &PUG_HOWL,
            MoveId::PugShake => &PUG_SHAKE,
            MoveId::PugTailSpin => &PUG_TAIL_SPIN,
            MoveId::PugAirHeadbutt => &PUG_AIR_HEADBUTT,
            MoveId::PugBuck => &PUG_BUCK,
            MoveId::PugSnap => &PUG_SNAP,
            MoveId::PugPancake => &PUG_PANCAKE,
            MoveId::PugSneeze => &PUG_SNEEZE,
            MoveId::PugTackle => &PUG_TACKLE,
            MoveId::PugTackleRide => &PUG_TACKLE_RIDE,
            MoveId::PugEarCopter => &PUG_EAR_COPTER,
            MoveId::PugPlayDead => &PUG_PLAY_DEAD,
            MoveId::PugPounce => &PUG_POUNCE,
            MoveId::PugBiteGrab => &PUG_BITE_GRAB,
            MoveId::PugDashBiteGrab => &PUG_DASH_BITE_GRAB,
            MoveId::PugNom => &PUG_NOM,
            MoveId::PugToss => &PUG_TOSS,
            MoveId::PugTugSpin => &PUG_TUG_SPIN,
            MoveId::PugFlingUp => &PUG_FLING_UP,
            MoveId::PugSit => &PUG_SIT,
            MoveId::SamuraiSlash => &SAMURAI_SLASH,
            MoveId::SamuraiSlash2 => &SAMURAI_SLASH2,
            MoveId::SamuraiThrust => &SAMURAI_THRUST,
            MoveId::SamuraiForwardCut => &SAMURAI_FORWARD_CUT,
            MoveId::SamuraiRisingCut => &SAMURAI_RISING_CUT,
            MoveId::SamuraiLowCut => &SAMURAI_LOW_CUT,
            MoveId::SamuraiDashCut => &SAMURAI_DASH_CUT,
            MoveId::SamuraiCleave => &SAMURAI_CLEAVE,
            MoveId::SamuraiSkyCut => &SAMURAI_SKY_CUT,
            MoveId::SamuraiSpinSweep => &SAMURAI_SPIN_SWEEP,
            MoveId::SamuraiAirSpin => &SAMURAI_AIR_SPIN,
            MoveId::SamuraiAirCut => &SAMURAI_AIR_CUT,
            MoveId::SamuraiBackCut => &SAMURAI_BACK_CUT,
            MoveId::SamuraiSkyArc => &SAMURAI_SKY_ARC,
            MoveId::SamuraiPlungeStab => &SAMURAI_PLUNGE_STAB,
            MoveId::SamuraiFocusCut => &SAMURAI_FOCUS_CUT,
            MoveId::SamuraiVault => &SAMURAI_VAULT,
            MoveId::SamuraiVaultStrike => &SAMURAI_VAULT_STRIKE,
            MoveId::SamuraiCyclone => &SAMURAI_CYCLONE,
            MoveId::SamuraiParry => &SAMURAI_PARRY,
            MoveId::SamuraiRiposte => &SAMURAI_RIPOSTE,
            MoveId::SamuraiHipThrow => &SAMURAI_HIP_THROW,
            MoveId::SamuraiShoulderThrow => &SAMURAI_SHOULDER_THROW,
            MoveId::SamuraiTossUp => &SAMURAI_TOSS_UP,
            MoveId::SamuraiPin => &SAMURAI_PIN,
            MoveId::NinjaKunai => &NINJA_KUNAI,
            MoveId::NinjaKunai2 => &NINJA_KUNAI2,
            MoveId::NinjaKunai3 => &NINJA_KUNAI3,
            MoveId::NinjaPalmThrust => &NINJA_PALM_THRUST,
            MoveId::NinjaRisingChop => &NINJA_RISING_CHOP,
            MoveId::NinjaSweep => &NINJA_SWEEP,
            MoveId::NinjaDashSlice => &NINJA_DASH_SLICE,
            MoveId::NinjaChop => &NINJA_CHOP,
            MoveId::NinjaFlipKick => &NINJA_FLIP_KICK,
            MoveId::NinjaSpinKick => &NINJA_SPIN_KICK,
            MoveId::NinjaAirSpin => &NINJA_AIR_SPIN,
            MoveId::NinjaFlyingKick => &NINJA_FLYING_KICK,
            MoveId::NinjaBackHook => &NINJA_BACK_HOOK,
            MoveId::NinjaUpFlip => &NINJA_UP_FLIP,
            MoveId::NinjaAxeKick => &NINJA_AXE_KICK,
            MoveId::NinjaShuriken => &NINJA_SHURIKEN,
            MoveId::NinjaShadowDash => &NINJA_SHADOW_DASH,
            MoveId::NinjaSmokeBomb => &NINJA_SMOKE_BOMB,
            MoveId::NinjaSubstitution => &NINJA_SUBSTITUTION,
            MoveId::NinjaSubstitutionStrike => &NINJA_SUBSTITUTION_STRIKE,
            MoveId::NinjaGrab => &NINJA_GRAB,
            MoveId::NinjaDashGrab => &NINJA_DASH_GRAB,
            MoveId::NinjaPummel => &NINJA_PUMMEL,
            MoveId::NinjaThrowForward => &NINJA_THROW_FORWARD,
            MoveId::NinjaThrowBack => &NINJA_THROW_BACK,
            MoveId::NinjaThrowUp => &NINJA_THROW_UP,
            MoveId::NinjaThrowDown => &NINJA_THROW_DOWN,
            MoveId::SoldierButtStrike => &SOLDIER_BUTT_STRIKE,
            MoveId::SoldierButtStrike2 => &SOLDIER_BUTT_STRIKE2,
            MoveId::SoldierBayonet => &SOLDIER_BAYONET,
            MoveId::SoldierRifleUp => &SOLDIER_RIFLE_UP,
            MoveId::SoldierLegSweep => &SOLDIER_LEG_SWEEP,
            MoveId::SoldierShoulderCharge => &SOLDIER_SHOULDER_CHARGE,
            MoveId::SoldierStockSmash => &SOLDIER_STOCK_SMASH,
            MoveId::SoldierBayonetUpper => &SOLDIER_BAYONET_UPPER,
            MoveId::SoldierStockSweep => &SOLDIER_STOCK_SWEEP,
            MoveId::SoldierAirSpin => &SOLDIER_AIR_SPIN,
            MoveId::SoldierAirBayonet => &SOLDIER_AIR_BAYONET,
            MoveId::SoldierBackElbow => &SOLDIER_BACK_ELBOW,
            MoveId::SoldierAirUp => &SOLDIER_AIR_UP,
            MoveId::SoldierAirStomp => &SOLDIER_AIR_STOMP,
            MoveId::SoldierRifleShot => &SOLDIER_RIFLE_SHOT,
            MoveId::SoldierGrenade => &SOLDIER_GRENADE,
            MoveId::SoldierBlastJump => &SOLDIER_BLAST_JUMP,
            MoveId::SoldierRiotShield => &SOLDIER_RIOT_SHIELD,
            MoveId::SoldierShieldBash => &SOLDIER_SHIELD_BASH,
            MoveId::SoldierGrab => &SOLDIER_GRAB,
            MoveId::SoldierDashGrab => &SOLDIER_DASH_GRAB,
            MoveId::SoldierPummel => &SOLDIER_PUMMEL,
            MoveId::SoldierThrowForward => &SOLDIER_THROW_FORWARD,
            MoveId::SoldierThrowBack => &SOLDIER_THROW_BACK,
            MoveId::SoldierThrowUp => &SOLDIER_THROW_UP,
            MoveId::SoldierThrowDown => &SOLDIER_THROW_DOWN,
            MoveId::HoboSlap => &HOBO_SLAP,
            MoveId::HoboSlap2 => &HOBO_SLAP2,
            MoveId::HoboSlap3 => &HOBO_SLAP3,
            MoveId::HoboPunch => &HOBO_PUNCH,
            MoveId::HoboUpSwing => &HOBO_UP_SWING,
            MoveId::HoboTrip => &HOBO_TRIP,
            MoveId::HoboStumble => &HOBO_STUMBLE,
            MoveId::HoboBottleSwing => &HOBO_BOTTLE_SWING,
            MoveId::HoboUpHeave => &HOBO_UP_HEAVE,
            MoveId::HoboSpinFlail => &HOBO_SPIN_FLAIL,
            MoveId::HoboFlail => &HOBO_FLAIL,
            MoveId::HoboHaymaker => &HOBO_HAYMAKER,
            MoveId::HoboBackhand => &HOBO_BACKHAND,
            MoveId::HoboUpFlail => &HOBO_UP_FLAIL,
            MoveId::HoboStomp => &HOBO_STOMP,
            MoveId::HoboBottleThrow => &HOBO_BOTTLE_THROW,
            MoveId::HoboCartCharge => &HOBO_CART_CHARGE,
            MoveId::HoboFizzRocket => &HOBO_FIZZ_ROCKET,
            MoveId::HoboPassedOut => &HOBO_PASSED_OUT,
            MoveId::HoboJolt => &HOBO_JOLT,
            MoveId::HoboGrab => &HOBO_GRAB,
            MoveId::HoboDashGrab => &HOBO_DASH_GRAB,
            MoveId::HoboPummel => &HOBO_PUMMEL,
            MoveId::HoboThrowForward => &HOBO_THROW_FORWARD,
            MoveId::HoboThrowBack => &HOBO_THROW_BACK,
            MoveId::HoboThrowUp => &HOBO_THROW_UP,
            MoveId::HoboThrowDown => &HOBO_THROW_DOWN,
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

/// Pie throw: a cream pie lobbed overhand. It arcs no higher than the pug's head, so
/// it hits short fighters too, and splats on the floor about half a stage away.
static PIE_THROW: MoveData = MoveData {
    name: "pie_throw",
    total_frames: 36,
    projectile: Some(ProjectileData {
        frame: 12,
        x: int(8),
        y: int(7),
        speed: Fx::int(2),
        vy: Fx::ratio(1, 2),
        gravity: Fx::ratio(7, 200),
        lifetime: 90,
        radius: int(3),
        damage: 7,
        angle: 40,
        base_kb: 25,
        kb_growth: 50,
        growth: None,
        explosion: None,
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
    grabbox: Some(GrabBox { first: 7, last: 8, x: int(7), y: int(6), radius: int(4), misses_shields: false }),
    ..BASE
};

/// Longer reach out of a run, more lag on a whiff.
static DASH_GRAB: MoveData = MoveData {
    name: "dashgrab",
    total_frames: 40,
    grabbox: Some(GrabBox { first: 9, last: 10, x: int(9), y: int(6), radius: half(9), misses_shields: false }),
    ..BASE
};

static PUMMEL: MoveData = MoveData {
    name: "pummel",
    total_frames: 16,
    throws: &[Throw { frame: 3, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 }],
    ..BASE
};

static FTHROW: MoveData = MoveData {
    name: "fthrow",
    total_frames: 30,
    throws: &[Throw { frame: 12, release: true, x: int(9), damage: 8, angle: 45, base_kb: 60, kb_growth: 60 }],
    ..BASE
};

/// The kill throw: swings the opponent around and out behind.
static BTHROW: MoveData = MoveData {
    name: "bthrow",
    total_frames: 36,
    throws: &[Throw { frame: 15, release: true, x: int(-9), damage: 10, angle: 135, base_kb: 55, kb_growth: 75 }],
    ..BASE
};

static UTHROW: MoveData = MoveData {
    name: "uthrow",
    total_frames: 34,
    throws: &[Throw { frame: 14, release: true, x: int(2), damage: 7, angle: 90, base_kb: 65, kb_growth: 65 }],
    ..BASE
};

/// Low knockback that pops the opponent up in front: the combo throw.
static DTHROW: MoveData = MoveData {
    name: "dthrow",
    total_frames: 32,
    throws: &[Throw { frame: 13, release: true, x: int(7), damage: 6, angle: 75, base_kb: 50, kb_growth: 40 }],
    ..BASE
};

// --- Pug --------------------------------------------------------------------
// A short fighter (hurtbox 9 tall), so most hitboxes sit lower than the chef's.

/// Snap bite. Press attack again for a second bite, then keep pressing for nibbles.
static PUG_BITE: MoveData = MoveData {
    name: "bite",
    total_frames: 14,
    hitboxes: &[hit(3, 4, int(6), int(6), half(7), 3, 50, 8, 50)],
    combo: Some((MoveId::PugBite2, 5)),
    ..BASE
};

static PUG_BITE2: MoveData = MoveData {
    name: "bite2",
    total_frames: 16,
    hitboxes: &[hit(3, 4, half(13), int(6), half(7), 2, 50, 8, 50)],
    combo: Some((MoveId::PugNibbles, 5)),
    ..BASE
};

/// Rapid nibbles: chains into itself for as long as attack keeps being pressed.
/// Tiny knockback that drifts the target away, so it can't lock forever.
static PUG_NIBBLES: MoveData = MoveData {
    name: "nibbles",
    total_frames: 12,
    hitboxes: &[hit(2, 3, int(6), int(5), int(4), 1, 60, 6, 30)],
    combo: Some((MoveId::PugNibbles, 5)),
    ..BASE
};

/// Quick low paw swipe.
static PUG_PAW_SWIPE: MoveData = MoveData {
    name: "paw_swipe",
    total_frames: 24,
    hitboxes: &[hit(5, 7, int(7), int(4), int(4), 8, 40, 25, 95)],
    ..BASE
};

/// Tosses the head up: a juggle starter.
static PUG_HEAD_TOSS: MoveData = MoveData {
    name: "head_toss",
    total_frames: 26,
    hitboxes: &[hit(6, 10, int(3), int(10), half(9), 7, 88, 35, 100)],
    ..BASE
};

/// Butt scoot: sits and drags itself forward along the floor, popping targets up.
static PUG_SCOOT: MoveData = MoveData {
    name: "scoot",
    total_frames: 30,
    hitboxes: &[hit(4, 16, int(4), half(3), int(4), 5, 75, 30, 50)],
    motion: &[Motion { first: 4, last: 16, vx: Some(Fx::ONE), vy: None }],
    ..BASE
};

/// Belly slide out of a run, strong early and weaker as it slows down.
static PUG_BELLY_SLIDE: MoveData = MoveData {
    name: "belly_slide",
    total_frames: 36,
    hitboxes: &[hit(5, 10, int(5), int(3), half(9), 9, 60, 40, 70), hit(11, 18, int(5), int(3), int(4), 5, 65, 30, 50)],
    motion: &[
        Motion { first: 4, last: 10, vx: Some(Fx::int(2)), vy: None },
        Motion { first: 11, last: 18, vx: Some(Fx::ONE), vy: None },
    ],
    ..BASE
};

/// A charging headbutt that lunges forward as it hits.
static PUG_RAM: MoveData = MoveData {
    name: "ram",
    total_frames: 46,
    hitboxes: &[hit(13, 15, int(8), int(5), int(5), 16, 35, 32, 100)],
    motion: &[Motion { first: 12, last: 15, vx: Some(Fx::ratio(22, 10)), vy: None }],
    charge_frame: Some(9),
    ..BASE
};

/// Rears up and howls: a tall blast of noise straight up.
static PUG_HOWL: MoveData = MoveData {
    name: "howl",
    total_frames: 44,
    hitboxes: &[hit(10, 16, int(2), int(12), int(6), 13, 90, 30, 100)],
    charge_frame: Some(6),
    ..BASE
};

/// Wet-dog shake: flings spray both ways.
static PUG_SHAKE: MoveData = MoveData {
    name: "shake",
    total_frames: 42,
    hitboxes: &[hit(8, 10, int(6), int(3), int(5), 12, 30, 25, 100), hit(8, 10, int(-6), int(3), int(5), 12, 150, 25, 100)],
    charge_frame: Some(4),
    ..BASE
};

/// Chases its own tail in a curled-up spin: strong early, weaker after.
static PUG_TAIL_SPIN: MoveData = MoveData {
    name: "tail_spin",
    total_frames: 32,
    hitboxes: &[hit(4, 8, int(0), int(5), int(6), 9, 45, 15, 100), hit(9, 20, int(0), int(5), half(11), 5, 45, 5, 80)],
    landing: Landing::Lag(8),
    ..BASE
};

static PUG_AIR_HEADBUTT: MoveData = MoveData {
    name: "air_headbutt",
    total_frames: 36,
    hitboxes: &[hit(7, 9, int(6), int(4), half(9), 11, 40, 25, 95)],
    landing: Landing::Lag(12),
    ..BASE
};

/// Double back kick, bucking with both hind legs.
static PUG_BUCK: MoveData = MoveData {
    name: "buck",
    total_frames: 32,
    hitboxes: &[hit(6, 8, int(-6), int(4), half(9), 12, 140, 25, 100)],
    landing: Landing::Lag(10),
    ..BASE
};

/// Snaps at the sky.
static PUG_SNAP: MoveData = MoveData {
    name: "snap",
    total_frames: 30,
    hitboxes: &[hit(5, 8, int(1), int(11), half(9), 9, 85, 25, 95)],
    landing: Landing::Lag(8),
    ..BASE
};

/// Belly flop that meteors, with a lot of landing lag.
static PUG_PANCAKE: MoveData = MoveData {
    name: "pancake",
    total_frames: 40,
    hitboxes: &[hit(10, 14, int(0), int(0), int(6), 13, 270, 20, 90)],
    landing: Landing::Lag(18),
    ..BASE
};

/// Ah... ah... CHOO. Hold special during the "ah" to build it up: a tap is a small,
/// short puff; a full charge is a big cloud that launches hard and knocks the pug back.
static PUG_SNEEZE: MoveData = MoveData {
    name: "sneeze",
    total_frames: 42,
    projectile: Some(ProjectileData {
        frame: 16,
        x: int(6),
        y: int(6),
        speed: Fx::ONE,
        vy: Fx::ZERO,
        gravity: Fx::ZERO,
        lifetime: 28,
        radius: int(3),
        damage: 4,
        angle: 45,
        base_kb: 20,
        kb_growth: 60,
        growth: Some(ProjectileGrowth { radius: int(3), damage: 12, base_kb: 45, lifetime: 22, recoil: Fx::ratio(15, 10) }),
        explosion: None,
    }),
    charge_frame: Some(13),
    charge_with: Input::SPECIAL,
    landing: Landing::Lag(10),
    ..BASE
};

/// Pounce tackle: a leap that latches onto whoever it catches (not through a shield)
/// and rides them (`PUG_TACKLE_RIDE`). Once per airtime, like every side special.
static PUG_TACKLE: MoveData = MoveData {
    name: "tackle",
    total_frames: 40,
    grabbox: Some(GrabBox { first: 8, last: 18, x: int(5), y: int(5), radius: half(9), misses_shields: true }),
    on_grab: Some(MoveId::PugTackleRide),
    motion: &[
        Motion { first: 1, last: 6, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 7, last: 10, vx: Some(Fx::ratio(24, 10)), vy: Some(Fx::ratio(12, 10)) },
        Motion { first: 11, last: 18, vx: Some(Fx::ratio(24, 10)), vy: None },
    ],
    landing: Landing::Lag(14),
    ..BASE
};

/// Clinging on: three bites, then it kicks off and hops back. Both stay put meanwhile,
/// even in the air.
static PUG_TACKLE_RIDE: MoveData = MoveData {
    name: "tackle_ride",
    total_frames: 54,
    throws: &[
        Throw { frame: 10, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 },
        Throw { frame: 20, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 },
        Throw { frame: 30, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 },
        Throw { frame: 40, release: true, x: int(9), damage: 4, angle: 80, base_kb: 45, kb_growth: 50 },
    ],
    motion: &[
        Motion { first: 1, last: 40, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 41, last: 44, vx: Some(Fx::ratio(-16, 10)), vy: Some(Fx::ratio(14, 10)) },
    ],
    landing: Landing::Lag(6),
    ..BASE
};

/// Ear copter, the recovery: flaps its ears for a slow, steerable climb of about
/// 45 units, swatting anyone above. Helpless afterwards.
static PUG_EAR_COPTER: MoveData = MoveData {
    name: "ear_copter",
    total_frames: 56,
    hitboxes: &[hit(8, 50, int(0), int(10), int(5), 3, 85, 45, 20)],
    motion: &[
        Motion { first: 1, last: 5, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 6, last: 50, vx: None, vy: Some(Fx::ONE) },
    ],
    landing: Landing::Lag(20),
    special_fall: true,
    ..BASE
};

/// Play dead: flops over belly-up. Hit on frames 6-26, it shrugs it off and pounces.
static PUG_PLAY_DEAD: MoveData = MoveData {
    name: "play_dead",
    total_frames: 44,
    counter: Some(Counter { first: 6, last: 26, into: MoveId::PugPounce }),
    ..BASE
};

static PUG_POUNCE: MoveData = MoveData {
    name: "pounce",
    total_frames: 30,
    hitboxes: &[hit(4, 8, int(6), int(4), half(11), 12, 40, 45, 95)],
    motion: &[Motion { first: 2, last: 8, vx: Some(Fx::int(2)), vy: None }],
    ..BASE
};

/// Grabs with its mouth: shorter reach than the chef's hands.
static PUG_BITE_GRAB: MoveData = MoveData {
    name: "bite_grab",
    total_frames: 28,
    grabbox: Some(GrabBox { first: 6, last: 7, x: int(6), y: int(5), radius: half(7), misses_shields: false }),
    ..BASE
};

static PUG_DASH_BITE_GRAB: MoveData = MoveData {
    name: "dash_bite_grab",
    total_frames: 38,
    grabbox: Some(GrabBox { first: 8, last: 9, x: int(8), y: int(5), radius: int(4), misses_shields: false }),
    ..BASE
};

static PUG_NOM: MoveData = MoveData {
    name: "nom",
    total_frames: 14,
    throws: &[Throw { frame: 3, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 }],
    ..BASE
};

/// Shakes them like a toy, then lets go forward.
static PUG_TOSS: MoveData = MoveData {
    name: "toss",
    total_frames: 30,
    throws: &[Throw { frame: 14, release: true, x: int(8), damage: 7, angle: 40, base_kb: 65, kb_growth: 55 }],
    ..BASE
};

/// The kill throw: spins around like a tug-of-war and flings them out behind.
static PUG_TUG_SPIN: MoveData = MoveData {
    name: "tug_spin",
    total_frames: 40,
    throws: &[Throw { frame: 20, release: true, x: int(-9), damage: 11, angle: 140, base_kb: 60, kb_growth: 80 }],
    ..BASE
};

static PUG_FLING_UP: MoveData = MoveData {
    name: "fling_up",
    total_frames: 32,
    throws: &[Throw { frame: 12, release: true, x: int(2), damage: 6, angle: 88, base_kb: 70, kb_growth: 60 }],
    ..BASE
};

/// Sits on them, popping them up in front: the combo throw.
static PUG_SIT: MoveData = MoveData {
    name: "sit",
    total_frames: 34,
    throws: &[Throw { frame: 16, release: true, x: int(6), damage: 7, angle: 80, base_kb: 45, kb_growth: 35 }],
    ..BASE
};

// --- Samurai ----------------------------------------------------------------
// The chef's height, with a katana: his hitboxes reach further out than anyone's,
// and the blade's tip (listed first, so it wins) hits harder than the part near the
// hilt. In exchange most cuts start a few frames later.

/// Quick draw cut. Press attack again for a backhand, then a thrust.
static SAMURAI_SLASH: MoveData = MoveData {
    name: "slash",
    total_frames: 20,
    hitboxes: &[hit(4, 5, int(9), int(7), int(4), 4, 50, 10, 50)],
    combo: Some((MoveId::SamuraiSlash2, 7)),
    ..BASE
};

static SAMURAI_SLASH2: MoveData = MoveData {
    name: "slash2",
    total_frames: 20,
    hitboxes: &[hit(4, 5, int(9), int(6), int(4), 3, 50, 10, 50)],
    combo: Some((MoveId::SamuraiThrust, 7)),
    ..BASE
};

/// Combo finisher: a long straight thrust.
static SAMURAI_THRUST: MoveData = MoveData {
    name: "thrust",
    total_frames: 32,
    hitboxes: &[hit(5, 7, int(13), int(6), half(7), 6, 35, 40, 95), hit(5, 7, int(7), int(6), int(3), 5, 40, 35, 90)],
    ..BASE
};

/// A level cut at arm's length, strongest at the tip.
static SAMURAI_FORWARD_CUT: MoveData = MoveData {
    name: "forward_cut",
    total_frames: 30,
    hitboxes: &[hit(7, 9, int(13), int(7), int(3), 11, 35, 30, 100), hit(7, 9, int(8), int(7), int(4), 8, 40, 25, 90)],
    ..BASE
};

/// An arc from in front up over the head.
static SAMURAI_RISING_CUT: MoveData = MoveData {
    name: "rising_cut",
    total_frames: 30,
    hitboxes: &[hit(6, 8, int(9), int(9), int(5), 8, 80, 30, 105), hit(9, 12, int(2), int(17), int(5), 8, 88, 30, 105)],
    ..BASE
};

/// Kneeling sweep along the floor: long, low and sent at a low angle.
static SAMURAI_LOW_CUT: MoveData = MoveData {
    name: "low_cut",
    total_frames: 24,
    hitboxes: &[hit(6, 8, int(12), int(2), int(3), 7, 25, 25, 70), hit(6, 8, int(7), int(2), int(4), 6, 30, 25, 65)],
    ..BASE
};

/// A running cut that carries him forward.
static SAMURAI_DASH_CUT: MoveData = MoveData {
    name: "dash_cut",
    total_frames: 40,
    hitboxes: &[hit(7, 11, int(10), int(6), int(5), 11, 45, 40, 70)],
    motion: &[Motion { first: 5, last: 11, vx: Some(Fx::int(2)), vy: None }],
    ..BASE
};

/// Two-handed overhead cleave: slow, long and the hardest hit he has.
static SAMURAI_CLEAVE: MoveData = MoveData {
    name: "cleave",
    total_frames: 56,
    hitboxes: &[hit(17, 19, int(13), int(6), int(4), 19, 38, 34, 102), hit(17, 19, int(7), int(10), int(4), 15, 40, 30, 100)],
    charge_frame: Some(12),
    ..BASE
};

/// Straight up: the blade sweeps from in front to overhead.
static SAMURAI_SKY_CUT: MoveData = MoveData {
    name: "sky_cut",
    total_frames: 48,
    hitboxes: &[hit(12, 16, int(2), int(18), int(6), 15, 90, 32, 100), hit(11, 12, int(8), int(9), int(5), 13, 85, 30, 100)],
    charge_frame: Some(8),
    ..BASE
};

/// A spin along the floor: in front first, then behind.
static SAMURAI_SPIN_SWEEP: MoveData = MoveData {
    name: "spin_sweep",
    total_frames: 50,
    hitboxes: &[hit(10, 11, int(12), int(2), int(4), 14, 30, 28, 98), hit(16, 17, int(-12), int(2), int(4), 15, 150, 28, 100)],
    charge_frame: Some(6),
    ..BASE
};

/// A full turn of the blade around him: in front and above, then behind.
static SAMURAI_AIR_SPIN: MoveData = MoveData {
    name: "air_spin",
    total_frames: 38,
    hitboxes: &[hit(5, 8, int(8), int(9), int(5), 9, 45, 15, 95), hit(9, 12, int(-8), int(5), int(5), 8, 135, 15, 95)],
    landing: Landing::Lag(12),
    ..BASE
};

/// A quick downward arc in front.
static SAMURAI_AIR_CUT: MoveData = MoveData {
    name: "air_cut",
    total_frames: 36,
    hitboxes: &[hit(6, 10, int(11), int(7), int(5), 10, 40, 22, 95)],
    landing: Landing::Lag(12),
    ..BASE
};

/// Turns and cuts behind him.
static SAMURAI_BACK_CUT: MoveData = MoveData {
    name: "back_cut",
    total_frames: 38,
    hitboxes: &[hit(8, 11, int(-11), int(6), int(5), 13, 145, 26, 100)],
    landing: Landing::Lag(14),
    ..BASE
};

static SAMURAI_SKY_ARC: MoveData = MoveData {
    name: "sky_arc",
    total_frames: 36,
    hitboxes: &[hit(5, 10, int(2), int(17), int(6), 10, 85, 25, 95)],
    landing: Landing::Lag(10),
    ..BASE
};

/// Stabs straight down: a meteor, with a lot of landing lag.
static SAMURAI_PLUNGE_STAB: MoveData = MoveData {
    name: "plunge_stab",
    total_frames: 46,
    hitboxes: &[hit(12, 16, int(1), int(-4), int(4), 14, 270, 20, 90)],
    landing: Landing::Lag(22),
    ..BASE
};

/// Focus cut: raises the blade beside his head and gathers himself, then a sweeping
/// cut. Hold special to charge it (up to 1 s, then it swings by itself): a full charge
/// hits far harder than any smash attack.
static SAMURAI_FOCUS_CUT: MoveData = MoveData {
    name: "focus_cut",
    total_frames: 46,
    hitboxes: &[hit(13, 16, int(13), int(7), int(4), 10, 40, 40, 95), hit(13, 16, int(7), int(8), int(5), 8, 42, 36, 92)],
    charge_frame: Some(9),
    charge_with: Input::SPECIAL,
    charge_growth: Some(HitGrowth { damage: 10, base_kb: 30 }),
    landing: Landing::Lag(12),
    ..BASE
};

/// Vault: crouches, then hops up over whoever is in front, turning around at the top
/// to land behind them facing their back. Press attack once airborne (frame 9 on) to
/// strike down instead (`SAMURAI_VAULT_STRIKE`). Once per airtime, like every side
/// special.
static SAMURAI_VAULT: MoveData = MoveData {
    name: "vault",
    total_frames: 34,
    motion: &[
        Motion { first: 1, last: 6, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 7, last: 12, vx: Some(Fx::ratio(18, 10)), vy: Some(Fx::ratio(24, 10)) },
        Motion { first: 13, last: 14, vx: Some(Fx::ratio(18, 10)), vy: Some(Fx::ratio(12, 10)) },
        // Turned around on 15, so the same way is now backward. Back down to the
        // starting height on 22.
        Motion { first: 15, last: 16, vx: Some(Fx::ratio(-18, 10)), vy: Some(Fx::ratio(-12, 10)) },
        Motion { first: 17, last: 22, vx: Some(Fx::ratio(-18, 10)), vy: Some(Fx::ratio(-24, 10)) },
    ],
    turn: Some(15),
    combo: Some((MoveId::SamuraiVaultStrike, 9)),
    landing: Landing::Lag(10),
    ..BASE
};

/// Points the blade down and drops straight onto whoever is below: a meteor.
static SAMURAI_VAULT_STRIKE: MoveData = MoveData {
    name: "vault_strike",
    total_frames: 36,
    hitboxes: &[hit(4, 22, int(1), int(-2), int(5), 12, 270, 25, 80)],
    motion: &[
        Motion { first: 1, last: 3, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 4, last: 22, vx: Some(Fx::ZERO), vy: Some(Fx::int(-3)) },
    ],
    landing: Landing::Lag(16),
    ..BASE
};

/// Cyclone, the recovery: spins with the blade held out level, climbing about 40
/// units, steerable. The blade sweeps both sides, hardest as it starts. Helpless
/// afterwards.
static SAMURAI_CYCLONE: MoveData = MoveData {
    name: "cyclone",
    total_frames: 46,
    hitboxes: &[
        hit(4, 7, int(9), int(7), int(5), 11, 75, 45, 80),
        hit(4, 7, int(-9), int(7), int(5), 11, 105, 45, 80),
        hit(8, 18, int(8), int(9), int(5), 5, 80, 25, 60),
        hit(8, 18, int(-8), int(9), int(5), 5, 100, 25, 60),
    ],
    motion: &[
        Motion { first: 1, last: 3, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 4, last: 18, vx: None, vy: Some(Fx::ratio(26, 10)) },
        Motion { first: 19, last: 20, vx: None, vy: Some(Fx::ratio(8, 10)) },
    ],
    landing: Landing::Lag(22),
    special_fall: true,
    ..BASE
};

/// Parry stance. Hit on frames 5-24, he turns the blow aside and ripostes.
static SAMURAI_PARRY: MoveData = MoveData {
    name: "parry",
    total_frames: 46,
    counter: Some(Counter { first: 5, last: 24, into: MoveId::SamuraiRiposte }),
    ..BASE
};

static SAMURAI_RIPOSTE: MoveData = MoveData {
    name: "riposte",
    total_frames: 32,
    hitboxes: &[hit(4, 7, int(10), int(7), int(6), 14, 35, 50, 90)],
    ..BASE
};

/// Hip throw forward.
static SAMURAI_HIP_THROW: MoveData = MoveData {
    name: "hip_throw",
    total_frames: 32,
    throws: &[Throw { frame: 13, release: true, x: int(9), damage: 8, angle: 40, base_kb: 60, kb_growth: 60 }],
    ..BASE
};

/// The kill throw: over the shoulder and out behind.
static SAMURAI_SHOULDER_THROW: MoveData = MoveData {
    name: "shoulder_throw",
    total_frames: 38,
    throws: &[Throw { frame: 16, release: true, x: int(-9), damage: 11, angle: 135, base_kb: 58, kb_growth: 78 }],
    ..BASE
};

static SAMURAI_TOSS_UP: MoveData = MoveData {
    name: "toss_up",
    total_frames: 34,
    throws: &[Throw { frame: 12, release: true, x: int(2), damage: 7, angle: 90, base_kb: 70, kb_growth: 55 }],
    ..BASE
};

/// Pins them with a knee, then lets them pop up in front: the combo throw.
static SAMURAI_PIN: MoveData = MoveData {
    name: "pin",
    total_frames: 34,
    throws: &[Throw { frame: 15, release: true, x: int(7), damage: 6, angle: 75, base_kb: 50, kb_growth: 40 }],
    ..BASE
};

// --- Ninja ------------------------------------------------------------------
// The lightest, fastest fighter: low damage per hit, quick startup, short total
// frames and low landing lag, all knife-hand chops and fast kicks.

/// Quick knife-hand slash. Press attack again for a second, then a third.
static NINJA_KUNAI: MoveData = MoveData {
    name: "ninja_kunai",
    total_frames: 16,
    hitboxes: &[hit(2, 3, int(5), int(6), half(7), 2, 45, 8, 50)],
    combo: Some((MoveId::NinjaKunai2, 4)),
    ..BASE
};

static NINJA_KUNAI2: MoveData = MoveData {
    name: "ninja_kunai2",
    total_frames: 16,
    hitboxes: &[hit(2, 3, int(5), int(6), half(7), 2, 45, 8, 50)],
    combo: Some((MoveId::NinjaKunai3, 4)),
    ..BASE
};

/// Combo finisher: a harder knife-hand that sends.
static NINJA_KUNAI3: MoveData = MoveData {
    name: "ninja_kunai3",
    total_frames: 28,
    hitboxes: &[hit(4, 6, int(6), int(5), int(4), 4, 40, 40, 100)],
    ..BASE
};

/// A fast straight palm thrust.
static NINJA_PALM_THRUST: MoveData = MoveData {
    name: "ninja_palm_thrust",
    total_frames: 20,
    hitboxes: &[hit(3, 5, int(7), int(7), int(4), 6, 40, 20, 95)],
    ..BASE
};

/// An upward knife-hand chop that juggles.
static NINJA_RISING_CHOP: MoveData = MoveData {
    name: "ninja_rising_chop",
    total_frames: 24,
    hitboxes: &[hit(4, 10, int(2), int(13), int(5), 5, 85, 30, 105)],
    ..BASE
};

/// A low sweeping kick from a crouch.
static NINJA_SWEEP: MoveData = MoveData {
    name: "ninja_sweep",
    total_frames: 20,
    hitboxes: &[hit(4, 6, int(7), int(2), int(4), 5, 75, 28, 70)],
    ..BASE
};

/// A sliding slash out of a run, carrying the fighter forward.
static NINJA_DASH_SLICE: MoveData = MoveData {
    name: "ninja_dash_slice",
    total_frames: 34,
    hitboxes: &[hit(5, 9, int(5), int(5), int(5), 7, 50, 35, 70)],
    motion: &[Motion { first: 5, last: 9, vx: Some(Fx::ratio(15, 10)), vy: None }],
    ..BASE
};

/// A two-hand overhead chop.
static NINJA_CHOP: MoveData = MoveData {
    name: "ninja_chop",
    total_frames: 42,
    hitboxes: &[hit(12, 14, int(9), int(7), int(5), 13, 40, 30, 100)],
    charge_frame: Some(8),
    ..BASE
};

/// A rising flip kick.
static NINJA_FLIP_KICK: MoveData = MoveData {
    name: "ninja_flip_kick",
    total_frames: 40,
    hitboxes: &[hit(9, 12, int(2), int(14), int(6), 12, 88, 30, 100)],
    charge_frame: Some(6),
    ..BASE
};

/// A low spin kick that hits both sides, each sending its own way.
static NINJA_SPIN_KICK: MoveData = MoveData {
    name: "ninja_spin_kick",
    total_frames: 38,
    hitboxes: &[hit(7, 9, int(7), int(2), int(5), 11, 30, 25, 95), hit(7, 9, int(-7), int(2), int(5), 11, 150, 25, 95)],
    charge_frame: Some(5),
    ..BASE
};

/// A spin kick around the body: strong early, weaker lingering hitbox.
static NINJA_AIR_SPIN: MoveData = MoveData {
    name: "ninja_air_spin",
    total_frames: 30,
    hitboxes: &[hit(3, 5, int(2), int(6), int(6), 6, 45, 10, 95), hit(6, 20, int(2), int(6), int(5), 4, 45, 5, 80)],
    landing: Landing::Lag(8),
    ..BASE
};

/// A side kick.
static NINJA_FLYING_KICK: MoveData = MoveData {
    name: "ninja_flying_kick",
    total_frames: 32,
    hitboxes: &[hit(5, 8, int(7), int(6), half(9), 8, 40, 22, 95)],
    landing: Landing::Lag(10),
    ..BASE
};

/// A back hook kick; the angle points backward.
static NINJA_BACK_HOOK: MoveData = MoveData {
    name: "ninja_back_hook",
    total_frames: 30,
    hitboxes: &[hit(4, 7, int(-6), int(6), half(9), 9, 140, 25, 95)],
    landing: Landing::Lag(9),
    ..BASE
};

/// An upward flip kick.
static NINJA_UP_FLIP: MoveData = MoveData {
    name: "ninja_up_flip",
    total_frames: 28,
    hitboxes: &[hit(4, 7, int(1), int(14), int(5), 7, 85, 24, 95)],
    landing: Landing::Lag(8),
    ..BASE
};

/// A downward axe kick that meteors (sends straight down).
static NINJA_AXE_KICK: MoveData = MoveData {
    name: "ninja_axe_kick",
    total_frames: 38,
    hitboxes: &[hit(10, 13, int(1), int(-1), half(9), 10, 270, 20, 90)],
    landing: Landing::Lag(16),
    ..BASE
};

/// Throws a shuriken straight ahead. No arc, no charge: quick and reusable.
static NINJA_SHURIKEN: MoveData = MoveData {
    name: "ninja_shuriken",
    total_frames: 26,
    projectile: Some(ProjectileData {
        frame: 10,
        x: int(7),
        y: int(7),
        speed: Fx::ratio(28, 10),
        vy: Fx::ZERO,
        gravity: Fx::ZERO,
        lifetime: 60,
        radius: int(2),
        damage: 5,
        angle: 40,
        base_kb: 20,
        kb_growth: 55,
        growth: None,
        explosion: None,
    }),
    landing: Landing::Lag(6),
    ..BASE
};

/// Shadow dash: a quick, intangible dash past the opponent, slashing as it goes.
static NINJA_SHADOW_DASH: MoveData = MoveData {
    name: "ninja_shadow_dash",
    total_frames: 34,
    hitboxes: &[hit(6, 14, int(5), int(6), int(5), 6, 45, 30, 80)],
    motion: &[
        Motion { first: 1, last: 5, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 6, last: 14, vx: Some(Fx::ratio(34, 10)), vy: Some(Fx::ZERO) },
        Motion { first: 15, last: 34, vx: Some(Fx::ZERO), vy: None },
    ],
    intangible: Some((6, 14)),
    landing: Landing::Lag(12),
    ..BASE
};

/// Smoke bomb: vanishes (intangible) and reappears higher, then helpless. It holds
/// its height while it vanishes and hangs after the teleport (gravity off), then falls.
static NINJA_SMOKE_BOMB: MoveData = MoveData {
    name: "ninja_smoke_bomb",
    total_frames: 40,
    teleport: Some(Teleport { frame: 8, dx: Fx::ZERO, dy: int(34) }),
    motion: &[Motion { first: 1, last: 16, vx: None, vy: Some(Fx::ZERO) }],
    intangible: Some((1, 20)),
    landing: Landing::Lag(20),
    special_fall: true,
    ..BASE
};

/// Substitution: if hit on frames 5-24, a log appears and the ninja strikes from
/// behind (turning toward the attacker, briefly intangible).
static NINJA_SUBSTITUTION: MoveData = MoveData {
    name: "ninja_substitution",
    total_frames: 40,
    counter: Some(Counter { first: 5, last: 24, into: MoveId::NinjaSubstitutionStrike }),
    ..BASE
};

static NINJA_SUBSTITUTION_STRIKE: MoveData = MoveData {
    name: "ninja_substitution_strike",
    total_frames: 28,
    hitboxes: &[hit(4, 8, int(8), int(6), int(6), 12, 40, 45, 95)],
    ..BASE
};

/// Grabs with the near hand; shorter reach than the chef's.
static NINJA_GRAB: MoveData = MoveData {
    name: "ninja_grab",
    total_frames: 28,
    grabbox: Some(GrabBox { first: 6, last: 7, x: int(7), y: int(6), radius: half(7), misses_shields: false }),
    ..BASE
};

static NINJA_DASH_GRAB: MoveData = MoveData {
    name: "ninja_dash_grab",
    total_frames: 36,
    grabbox: Some(GrabBox { first: 8, last: 9, x: int(8), y: int(6), radius: int(4), misses_shields: false }),
    ..BASE
};

/// A kunai-hilt pommel: a quick, light pummel.
static NINJA_PUMMEL: MoveData = MoveData {
    name: "ninja_pummel",
    total_frames: 14,
    throws: &[Throw { frame: 3, release: false, x: Fx::ZERO, damage: 1, angle: 0, base_kb: 0, kb_growth: 0 }],
    ..BASE
};

static NINJA_THROW_FORWARD: MoveData = MoveData {
    name: "ninja_throw_forward",
    total_frames: 28,
    throws: &[Throw { frame: 11, release: true, x: int(8), damage: 7, angle: 40, base_kb: 60, kb_growth: 60 }],
    ..BASE
};

/// The kill throw: flips them over and out behind.
static NINJA_THROW_BACK: MoveData = MoveData {
    name: "ninja_throw_back",
    total_frames: 34,
    throws: &[Throw { frame: 14, release: true, x: int(-8), damage: 9, angle: 140, base_kb: 55, kb_growth: 75 }],
    ..BASE
};

static NINJA_THROW_UP: MoveData = MoveData {
    name: "ninja_throw_up",
    total_frames: 30,
    throws: &[Throw { frame: 11, release: true, x: int(2), damage: 6, angle: 90, base_kb: 65, kb_growth: 60 }],
    ..BASE
};

/// Flips them onto the floor and pops them up in front: the combo throw.
static NINJA_THROW_DOWN: MoveData = MoveData {
    name: "ninja_throw_down",
    total_frames: 30,
    throws: &[Throw { frame: 12, release: true, x: int(6), damage: 5, angle: 75, base_kb: 50, kb_growth: 40 }],
    ..BASE
};

// --- Soldier ----------------------------------------------------------------
// A heavyweight in fatigues with a rifle and bayonet. He hits harder and reaches
// further than the chef's fists, in exchange for slower startups, and he falls
// like a stone (see `FighterParams::SOLDIER`). The rifle is a two-handed prop, so
// several moves hit out at x 8-13.

/// Rifle-butt jab. Press attack again for a second, harder butt strike.
static SOLDIER_BUTT_STRIKE: MoveData = MoveData {
    name: "soldier_butt_strike",
    total_frames: 20,
    hitboxes: &[hit(4, 5, int(7), int(7), int(4), 4, 50, 10, 50)],
    combo: Some((MoveId::SoldierButtStrike2, 7)),
    ..BASE
};

static SOLDIER_BUTT_STRIKE2: MoveData = MoveData {
    name: "soldier_butt_strike_2",
    total_frames: 24,
    hitboxes: &[hit(4, 6, int(8), int(7), int(4), 6, 40, 40, 95)],
    ..BASE
};

/// Bayonet thrust, the forward tilt: long and straight, hardest at the tip.
static SOLDIER_BAYONET: MoveData = MoveData {
    name: "soldier_bayonet",
    total_frames: 32,
    hitboxes: &[hit(7, 9, int(12), int(7), int(3), 13, 35, 28, 100), hit(7, 9, int(8), int(7), int(4), 10, 40, 25, 90)],
    ..BASE
};

/// Swings the rifle up over his head.
static SOLDIER_RIFLE_UP: MoveData = MoveData {
    name: "soldier_rifle_up",
    total_frames: 32,
    hitboxes: &[hit(7, 9, int(5), int(10), int(5), 9, 85, 32, 105), hit(10, 13, int(2), int(16), int(5), 9, 88, 32, 105)],
    ..BASE
};

/// Low leg sweep that trips and pops opponents up.
static SOLDIER_LEG_SWEEP: MoveData = MoveData {
    name: "soldier_leg_sweep",
    total_frames: 26,
    hitboxes: &[hit(7, 9, int(9), int(2), int(4), 8, 70, 30, 75)],
    ..BASE
};

/// Shoulder charge out of a run, carried forward on the run's momentum.
static SOLDIER_SHOULDER_CHARGE: MoveData = MoveData {
    name: "soldier_shoulder_charge",
    total_frames: 42,
    hitboxes: &[hit(7, 11, int(7), int(6), int(5), 14, 45, 45, 75), hit(12, 18, int(6), int(6), int(4), 8, 55, 30, 55)],
    motion: &[Motion { first: 5, last: 14, vx: Some(Fx::int(2)), vy: None }],
    ..BASE
};

/// Heavy rifle-stock smash. The charge pose is held while charging.
static SOLDIER_STOCK_SMASH: MoveData = MoveData {
    name: "soldier_stock_smash",
    total_frames: 52,
    hitboxes: &[hit(16, 18, int(11), int(7), int(5), 20, 38, 34, 103), hit(16, 18, int(7), int(7), int(4), 16, 40, 30, 100)],
    charge_frame: Some(12),
    ..BASE
};

static SOLDIER_BAYONET_UPPER: MoveData = MoveData {
    name: "soldier_bayonet_upper",
    total_frames: 48,
    hitboxes: &[hit(12, 16, int(3), int(17), int(6), 17, 90, 34, 100), hit(11, 12, int(7), int(10), int(5), 15, 85, 32, 100)],
    charge_frame: Some(8),
    ..BASE
};

/// Spinning stock sweep: in front first, then behind.
static SOLDIER_STOCK_SWEEP: MoveData = MoveData {
    name: "soldier_stock_sweep",
    total_frames: 46,
    hitboxes: &[hit(9, 11, int(10), int(3), int(5), 15, 30, 28, 98), hit(15, 17, int(-10), int(3), int(5), 16, 150, 28, 100)],
    charge_frame: Some(6),
    ..BASE
};

/// Spins with the rifle out level: strong early, weaker as it slows.
static SOLDIER_AIR_SPIN: MoveData = MoveData {
    name: "soldier_air_spin",
    total_frames: 38,
    hitboxes: &[hit(5, 8, int(8), int(6), int(6), 11, 45, 15, 95), hit(9, 20, int(0), int(6), int(6), 6, 45, 8, 80)],
    landing: Landing::Lag(14),
    ..BASE
};

/// Airborne bayonet thrust.
static SOLDIER_AIR_BAYONET: MoveData = MoveData {
    name: "soldier_air_bayonet",
    total_frames: 40,
    hitboxes: &[hit(9, 12, int(11), int(7), int(4), 14, 40, 26, 95)],
    landing: Landing::Lag(16),
    ..BASE
};

/// Back elbow.
static SOLDIER_BACK_ELBOW: MoveData = MoveData {
    name: "soldier_back_elbow",
    total_frames: 36,
    hitboxes: &[hit(7, 10, int(-7), int(7), int(5), 14, 145, 28, 100)],
    landing: Landing::Lag(13),
    ..BASE
};

/// Upward rifle jab.
static SOLDIER_AIR_UP: MoveData = MoveData {
    name: "soldier_air_up",
    total_frames: 34,
    hitboxes: &[hit(6, 10, int(2), int(15), int(5), 11, 85, 27, 95)],
    landing: Landing::Lag(10),
    ..BASE
};

/// Stomps straight down: a meteor, with a lot of landing lag.
static SOLDIER_AIR_STOMP: MoveData = MoveData {
    name: "soldier_air_stomp",
    total_frames: 46,
    hitboxes: &[hit(13, 16, int(1), int(-1), int(5), 15, 270, 20, 90)],
    landing: Landing::Lag(20),
    ..BASE
};

/// Rifle shot: a fast, straight bullet.
static SOLDIER_RIFLE_SHOT: MoveData = MoveData {
    name: "soldier_rifle_shot",
    total_frames: 30,
    projectile: Some(ProjectileData {
        frame: 10,
        x: int(9),
        y: int(7),
        speed: Fx::ratio(35, 10),
        vy: Fx::ZERO,
        gravity: Fx::ZERO,
        lifetime: 40,
        radius: int(2),
        damage: 8,
        angle: 30,
        base_kb: 30,
        kb_growth: 60,
        growth: None,
        explosion: None,
    }),
    ..BASE
};

/// Grenade: a lobbed shell that explodes where it lands or on whatever it touches.
static SOLDIER_GRENADE: MoveData = MoveData {
    name: "soldier_grenade",
    total_frames: 40,
    projectile: Some(ProjectileData {
        frame: 14,
        x: int(7),
        y: int(8),
        speed: Fx::int(2),
        vy: Fx::ratio(1, 2),
        gravity: Fx::ratio(7, 200),
        lifetime: 60,
        radius: int(2),
        // The shell itself doesn't hit: the blast it sets off does.
        damage: 0,
        angle: 45,
        base_kb: 0,
        kb_growth: 0,
        growth: None,
        explosion: Some(Explosion { radius: int(8), damage: 13, angle: 70, base_kb: 45, kb_growth: 75, on_contact: true }),
    }),
    landing: Landing::Lag(10),
    ..BASE
};

/// Blast jump: an explosion below launches him up (his recovery) while spiking
/// whoever is underneath.
static SOLDIER_BLAST_JUMP: MoveData = MoveData {
    name: "soldier_blast_jump",
    total_frames: 46,
    hitboxes: &[hit(4, 7, int(0), int(-4), int(6), 10, 270, 30, 60), hit(6, 12, int(0), int(4), int(5), 5, 80, 25, 60)],
    motion: &[
        Motion { first: 1, last: 3, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 4, last: 18, vx: None, vy: Some(Fx::ratio(26, 10)) },
        Motion { first: 19, last: 20, vx: None, vy: Some(Fx::ratio(8, 10)) },
    ],
    landing: Landing::Lag(22),
    special_fall: true,
    ..BASE
};

/// Riot shield stance. Hit during the window, he blocks the blow and bashes back.
static SOLDIER_RIOT_SHIELD: MoveData = MoveData {
    name: "soldier_riot_shield",
    total_frames: 48,
    counter: Some(Counter { first: 6, last: 26, into: MoveId::SoldierShieldBash }),
    ..BASE
};

static SOLDIER_SHIELD_BASH: MoveData = MoveData {
    name: "soldier_shield_bash",
    total_frames: 34,
    hitboxes: &[hit(5, 8, int(8), int(7), int(6), 15, 40, 50, 90)],
    ..BASE
};

/// Grabs with one hand while the rifle stays in the other.
static SOLDIER_GRAB: MoveData = MoveData {
    name: "soldier_grab",
    total_frames: 32,
    grabbox: Some(GrabBox { first: 7, last: 8, x: int(8), y: int(6), radius: int(4), misses_shields: false }),
    ..BASE
};

static SOLDIER_DASH_GRAB: MoveData = MoveData {
    name: "soldier_dash_grab",
    total_frames: 42,
    grabbox: Some(GrabBox { first: 9, last: 10, x: int(9), y: int(6), radius: int(4), misses_shields: false }),
    ..BASE
};

/// Rifle-butt pommel.
static SOLDIER_PUMMEL: MoveData = MoveData {
    name: "soldier_pummel",
    total_frames: 18,
    throws: &[Throw { frame: 3, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 }],
    ..BASE
};

static SOLDIER_THROW_FORWARD: MoveData = MoveData {
    name: "soldier_throw_forward",
    total_frames: 32,
    throws: &[Throw { frame: 13, release: true, x: int(9), damage: 8, angle: 45, base_kb: 65, kb_growth: 60 }],
    ..BASE
};

/// The kill throw: swings the opponent over and out behind.
static SOLDIER_THROW_BACK: MoveData = MoveData {
    name: "soldier_throw_back",
    total_frames: 38,
    throws: &[Throw { frame: 16, release: true, x: int(-9), damage: 11, angle: 135, base_kb: 60, kb_growth: 80 }],
    ..BASE
};

static SOLDIER_THROW_UP: MoveData = MoveData {
    name: "soldier_throw_up",
    total_frames: 34,
    throws: &[Throw { frame: 14, release: true, x: int(2), damage: 7, angle: 90, base_kb: 72, kb_growth: 60 }],
    ..BASE
};

/// Slams them down in front, popping them up: the combo throw.
static SOLDIER_THROW_DOWN: MoveData = MoveData {
    name: "soldier_throw_down",
    total_frames: 34,
    throws: &[Throw { frame: 15, release: true, x: int(7), damage: 7, angle: 70, base_kb: 55, kb_growth: 40 }],
    ..BASE
};

// --- Hobo -------------------------------------------------------------------
// A floaty, wobbly drunken brawler: the chef's height, but his swings come out late
// and lurch through odd arcs. Startups run a few frames longer than the other cast
// and several moves carry him forward as he over-commits to the swing.

/// A swaying slap. Press attack again for a backhand, then a shove.
static HOBO_SLAP: MoveData = MoveData {
    name: "hobo_slap",
    total_frames: 20,
    hitboxes: &[hit(4, 5, int(6), int(6), half(7), 3, 40, 8, 55)],
    combo: Some((MoveId::HoboSlap2, 7)),
    ..BASE
};

static HOBO_SLAP2: MoveData = MoveData {
    name: "hobo_slap2",
    total_frames: 20,
    hitboxes: &[hit(5, 6, half(13), int(6), half(7), 3, 40, 8, 55)],
    combo: Some((MoveId::HoboSlap3, 7)),
    ..BASE
};

/// Combo finisher: a lurching two-handed shove that sends.
static HOBO_SLAP3: MoveData = MoveData {
    name: "hobo_slap3",
    total_frames: 32,
    hitboxes: &[hit(7, 9, int(8), int(5), half(9), 6, 35, 40, 95)],
    ..BASE
};

/// A punch that lurches forward as it lands.
static HOBO_PUNCH: MoveData = MoveData {
    name: "hobo_punch",
    total_frames: 28,
    hitboxes: &[hit(8, 10, int(8), int(7), int(4), 9, 35, 22, 100)],
    motion: &[Motion { first: 7, last: 10, vx: Some(Fx::ONE), vy: None }],
    ..BASE
};

/// An upward flail, arms swinging past his head.
static HOBO_UP_SWING: MoveData = MoveData {
    name: "hobo_up_swing",
    total_frames: 32,
    hitboxes: &[hit(7, 14, int(2), int(14), int(5), 7, 85, 30, 110)],
    ..BASE
};

/// A low trip: he swings a leg out and sweeps the floor.
static HOBO_TRIP: MoveData = MoveData {
    name: "hobo_trip",
    total_frames: 24,
    hitboxes: &[hit(6, 8, int(8), int(2), int(4), 6, 80, 30, 70)],
    ..BASE
};

/// A stumbling dash that flails into the target: strong early, weaker as he loses his
/// footing and coasts.
static HOBO_STUMBLE: MoveData = MoveData {
    name: "hobo_stumble",
    total_frames: 40,
    hitboxes: &[hit(8, 12, int(6), int(6), int(5), 10, 50, 40, 70), hit(13, 20, int(5), int(6), int(4), 6, 55, 30, 50)],
    motion: &[
        Motion { first: 4, last: 12, vx: Some(Fx::int(2)), vy: None },
        Motion { first: 13, last: 18, vx: Some(Fx::ONE), vy: None },
    ],
    ..BASE
};

// --- Hobo smash attacks -----------------------------------------------------

/// A huge two-handed swing of the bottle.
static HOBO_BOTTLE_SWING: MoveData = MoveData {
    name: "hobo_bottle_swing",
    total_frames: 50,
    hitboxes: &[hit(16, 18, int(11), int(7), int(5), 16, 38, 30, 105)],
    charge_frame: Some(12),
    ..BASE
};

/// Heaves the bottle straight up.
static HOBO_UP_HEAVE: MoveData = MoveData {
    name: "hobo_up_heave",
    total_frames: 48,
    hitboxes: &[hit(12, 16, int(1), int(16), int(6), 14, 88, 32, 100)],
    charge_frame: Some(8),
    ..BASE
};

/// A drunken spin: flails in front first, then around behind.
static HOBO_SPIN_FLAIL: MoveData = MoveData {
    name: "hobo_spin_flail",
    total_frames: 46,
    hitboxes: &[hit(10, 12, int(8), int(2), int(5), 13, 30, 25, 100), hit(15, 17, int(-8), int(2), int(5), 14, 150, 25, 100)],
    charge_frame: Some(6),
    ..BASE
};

// --- Hobo aerials -----------------------------------------------------------

/// A flailing spin, limbs thrown out around him.
static HOBO_FLAIL: MoveData = MoveData {
    name: "hobo_flail",
    total_frames: 38,
    hitboxes: &[hit(5, 8, int(3), int(6), int(6), 8, 45, 10, 100), hit(9, 24, int(3), int(6), int(5), 5, 45, 5, 80)],
    landing: Landing::Lag(16),
    ..BASE
};

/// A wild haymaker, telegraphed but heavy.
static HOBO_HAYMAKER: MoveData = MoveData {
    name: "hobo_haymaker",
    total_frames: 42,
    hitboxes: &[hit(10, 13, int(7), int(6), half(9), 12, 40, 25, 95)],
    landing: Landing::Lag(18),
    ..BASE
};

/// A backhand swing behind him.
static HOBO_BACKHAND: MoveData = MoveData {
    name: "hobo_backhand",
    total_frames: 36,
    hitboxes: &[hit(8, 11, int(-7), int(6), half(9), 12, 140, 25, 100)],
    landing: Landing::Lag(14),
    ..BASE
};

static HOBO_UP_FLAIL: MoveData = MoveData {
    name: "hobo_up_flail",
    total_frames: 34,
    hitboxes: &[hit(6, 10, int(1), int(15), int(5), 9, 85, 25, 95)],
    landing: Landing::Lag(12),
    ..BASE
};

/// A downward stomp: a meteor with a lot of landing lag.
static HOBO_STOMP: MoveData = MoveData {
    name: "hobo_stomp",
    total_frames: 46,
    hitboxes: &[hit(13, 16, int(1), int(-1), half(9), 13, 270, 20, 90)],
    landing: Landing::Lag(22),
    ..BASE
};

// --- Hobo specials ----------------------------------------------------------

/// Bottle throw: lobs a bottle overhand. It arcs and shatters where it lands, catching
/// anyone close by; a direct hit mid-flight still counts for a smaller hit.
static HOBO_BOTTLE_THROW: MoveData = MoveData {
    name: "hobo_bottle_throw",
    total_frames: 36,
    projectile: Some(ProjectileData {
        frame: 12,
        x: int(8),
        y: int(7),
        speed: Fx::ratio(16, 10),
        vy: Fx::ratio(11, 20),
        gravity: Fx::ratio(7, 200),
        lifetime: 90,
        radius: int(3),
        damage: 5,
        angle: 40,
        base_kb: 22,
        kb_growth: 50,
        growth: None,
        explosion: None,
    }),
    shatter: Some(Shatter { radius: int(8), damage: 6, angle: 70, base_kb: 30, kb_growth: 55 }),
    landing: Landing::Lag(8),
    ..BASE
};

/// Shopping-cart charge: crouches, then bursts forward fast behind the cart, plowing
/// through whoever's in the way. The ride leaves him wobbling (a long coast out), and
/// helpless if he goes off a ledge.
static HOBO_CART_CHARGE: MoveData = MoveData {
    name: "hobo_cart_charge",
    total_frames: 44,
    hitboxes: &[hit(7, 20, int(6), int(6), int(6), 12, 40, 40, 90)],
    motion: &[
        Motion { first: 1, last: 6, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 7, last: 20, vx: Some(Fx::int(3)), vy: Some(Fx::ZERO) },
        Motion { first: 21, last: 28, vx: Some(Fx::ratio(1, 2)), vy: None },
    ],
    landing: Landing::Lag(18),
    special_fall: true,
    ..BASE
};

/// Fizz rocket: shakes a soda bottle and lets the fizz launch him upward, a steerable
/// recovery that ends helpless.
static HOBO_FIZZ_ROCKET: MoveData = MoveData {
    name: "hobo_fizz_rocket",
    total_frames: 44,
    hitboxes: &[hit(5, 7, int(3), int(12), int(5), 8, 80, 40, 80), hit(8, 15, int(1), int(14), int(4), 4, 80, 20, 60)],
    motion: &[
        Motion { first: 1, last: 4, vx: Some(Fx::ZERO), vy: Some(Fx::ZERO) },
        Motion { first: 5, last: 18, vx: None, vy: Some(Fx::ratio(26, 10)) },
        Motion { first: 19, last: 20, vx: None, vy: Some(Fx::ratio(8, 10)) },
    ],
    landing: Landing::Lag(20),
    special_fall: true,
    ..BASE
};

/// Passed out: flops over and lies there. Hit on frames 8-28, he shrugs it off and
/// jolts awake swinging.
static HOBO_PASSED_OUT: MoveData = MoveData {
    name: "hobo_passed_out",
    total_frames: 46,
    counter: Some(Counter { first: 8, last: 28, into: MoveId::HoboJolt }),
    ..BASE
};

static HOBO_JOLT: MoveData = MoveData {
    name: "hobo_jolt",
    total_frames: 30,
    hitboxes: &[hit(5, 8, int(6), int(4), half(11), 12, 40, 45, 95)],
    motion: &[Motion { first: 2, last: 8, vx: Some(Fx::ratio(18, 10)), vy: None }],
    ..BASE
};

// --- Hobo grabs and throws --------------------------------------------------

/// A rough headlock grab.
static HOBO_GRAB: MoveData = MoveData {
    name: "hobo_grab",
    total_frames: 30,
    grabbox: Some(GrabBox { first: 7, last: 8, x: int(7), y: int(6), radius: int(4), misses_shields: false }),
    ..BASE
};

static HOBO_DASH_GRAB: MoveData = MoveData {
    name: "hobo_dash_grab",
    total_frames: 40,
    grabbox: Some(GrabBox { first: 9, last: 10, x: int(9), y: int(6), radius: half(9), misses_shields: false }),
    ..BASE
};

/// Shakes the held fighter by the collar.
static HOBO_PUMMEL: MoveData = MoveData {
    name: "hobo_pummel",
    total_frames: 16,
    throws: &[Throw { frame: 3, release: false, x: Fx::ZERO, damage: 2, angle: 0, base_kb: 0, kb_growth: 0 }],
    ..BASE
};

static HOBO_THROW_FORWARD: MoveData = MoveData {
    name: "hobo_throw_forward",
    total_frames: 32,
    throws: &[Throw { frame: 13, release: true, x: int(9), damage: 8, angle: 40, base_kb: 60, kb_growth: 60 }],
    ..BASE
};

/// The kill throw: slings them over his shoulder and out behind.
static HOBO_THROW_BACK: MoveData = MoveData {
    name: "hobo_throw_back",
    total_frames: 38,
    throws: &[Throw { frame: 16, release: true, x: int(-9), damage: 11, angle: 135, base_kb: 58, kb_growth: 78 }],
    ..BASE
};

static HOBO_THROW_UP: MoveData = MoveData {
    name: "hobo_throw_up",
    total_frames: 34,
    throws: &[Throw { frame: 12, release: true, x: int(2), damage: 7, angle: 90, base_kb: 70, kb_growth: 55 }],
    ..BASE
};

/// Drops them at his feet and stumbles over them, popping them up: the combo throw.
static HOBO_THROW_DOWN: MoveData = MoveData {
    name: "hobo_throw_down",
    total_frames: 34,
    throws: &[Throw { frame: 15, release: true, x: int(7), damage: 6, angle: 75, base_kb: 50, kb_growth: 40 }],
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
    pub const ALL: [DodgeKind; 5] = [DodgeKind::Spot, DodgeKind::RollForward, DodgeKind::RollBack, DodgeKind::Air, DodgeKind::AirDirectional];

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
