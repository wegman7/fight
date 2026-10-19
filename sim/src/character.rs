//! Playable characters. Each has its own tuning ([`FighterParams`]) and its own
//! [`Moveset`]: which move every input starts.

use crate::fighter::FighterParams;
use crate::moves::{Landing, MoveId};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Character {
    /// The all-rounder, dressed in chef's whites: punches, kicks, a thrown pie, an uppercut
    /// recovery and a ground pound.
    Chef,
    /// Small, light and quick, with two air jumps: bites, a chargeable sneeze, a pounce
    /// tackle that rides its target, an ear-flapping recovery and a play-dead counter.
    Pug,
    /// A katana swordsman: the longest reach, a little heavier and slower to start:
    /// slashes, a chargeable focus cut, a vault over the opponent, a spinning recovery
    /// and a parry that ripostes.
    Samurai,
    /// The heavyweight: a soldier in fatigues and a helmet with a rifle and bayonet.
    /// Slow and falls fast, but hits hard — and shoots, lobs grenades, blast-jumps and
    /// counters with a riot shield.
    Soldier,
}

/// The move each input starts. Follow-ups (jab chains, landings, counter attacks)
/// are named by the moves themselves.
#[derive(Debug)]
pub struct Moveset {
    pub jab: MoveId,
    pub ftilt: MoveId,
    pub utilt: MoveId,
    pub dtilt: MoveId,
    pub dash_attack: MoveId,
    pub fsmash: MoveId,
    pub usmash: MoveId,
    pub dsmash: MoveId,
    pub nair: MoveId,
    pub fair: MoveId,
    pub bair: MoveId,
    pub uair: MoveId,
    pub dair: MoveId,
    pub neutral_special: MoveId,
    pub side_special: MoveId,
    pub up_special: MoveId,
    pub down_special: MoveId,
    pub grab: MoveId,
    pub dash_grab: MoveId,
    pub pummel: MoveId,
    pub fthrow: MoveId,
    pub bthrow: MoveId,
    pub uthrow: MoveId,
    pub dthrow: MoveId,
}

impl Moveset {
    fn slots(&self) -> [MoveId; 24] {
        [
            self.jab,
            self.ftilt,
            self.utilt,
            self.dtilt,
            self.dash_attack,
            self.fsmash,
            self.usmash,
            self.dsmash,
            self.nair,
            self.fair,
            self.bair,
            self.uair,
            self.dair,
            self.neutral_special,
            self.side_special,
            self.up_special,
            self.down_special,
            self.grab,
            self.dash_grab,
            self.pummel,
            self.fthrow,
            self.bthrow,
            self.uthrow,
            self.dthrow,
        ]
    }
}

static CHEF_MOVES: Moveset = Moveset {
    jab: MoveId::Jab,
    ftilt: MoveId::FTilt,
    utilt: MoveId::UTilt,
    dtilt: MoveId::DTilt,
    dash_attack: MoveId::DashAttack,
    fsmash: MoveId::FSmash,
    usmash: MoveId::USmash,
    dsmash: MoveId::DSmash,
    nair: MoveId::Nair,
    fair: MoveId::Fair,
    bair: MoveId::Bair,
    uair: MoveId::Uair,
    dair: MoveId::Dair,
    neutral_special: MoveId::PieThrow,
    side_special: MoveId::SideSpecial,
    up_special: MoveId::UpSpecial,
    down_special: MoveId::DownSpecial,
    grab: MoveId::Grab,
    dash_grab: MoveId::DashGrab,
    pummel: MoveId::Pummel,
    fthrow: MoveId::FThrow,
    bthrow: MoveId::BThrow,
    uthrow: MoveId::UThrow,
    dthrow: MoveId::DThrow,
};

static PUG_MOVES: Moveset = Moveset {
    jab: MoveId::PugBite,
    ftilt: MoveId::PugPawSwipe,
    utilt: MoveId::PugHeadToss,
    dtilt: MoveId::PugScoot,
    dash_attack: MoveId::PugBellySlide,
    fsmash: MoveId::PugRam,
    usmash: MoveId::PugHowl,
    dsmash: MoveId::PugShake,
    nair: MoveId::PugTailSpin,
    fair: MoveId::PugAirHeadbutt,
    bair: MoveId::PugBuck,
    uair: MoveId::PugSnap,
    dair: MoveId::PugPancake,
    neutral_special: MoveId::PugSneeze,
    side_special: MoveId::PugTackle,
    up_special: MoveId::PugEarCopter,
    down_special: MoveId::PugPlayDead,
    grab: MoveId::PugBiteGrab,
    dash_grab: MoveId::PugDashBiteGrab,
    pummel: MoveId::PugNom,
    fthrow: MoveId::PugToss,
    bthrow: MoveId::PugTugSpin,
    uthrow: MoveId::PugFlingUp,
    dthrow: MoveId::PugSit,
};

static SAMURAI_MOVES: Moveset = Moveset {
    jab: MoveId::SamuraiSlash,
    ftilt: MoveId::SamuraiForwardCut,
    utilt: MoveId::SamuraiRisingCut,
    dtilt: MoveId::SamuraiLowCut,
    dash_attack: MoveId::SamuraiDashCut,
    fsmash: MoveId::SamuraiCleave,
    usmash: MoveId::SamuraiSkyCut,
    dsmash: MoveId::SamuraiSpinSweep,
    nair: MoveId::SamuraiAirSpin,
    fair: MoveId::SamuraiAirCut,
    bair: MoveId::SamuraiBackCut,
    uair: MoveId::SamuraiSkyArc,
    dair: MoveId::SamuraiPlungeStab,
    neutral_special: MoveId::SamuraiFocusCut,
    side_special: MoveId::SamuraiVault,
    up_special: MoveId::SamuraiCyclone,
    down_special: MoveId::SamuraiParry,
    grab: MoveId::Grab,
    dash_grab: MoveId::DashGrab,
    pummel: MoveId::Pummel,
    fthrow: MoveId::SamuraiHipThrow,
    bthrow: MoveId::SamuraiShoulderThrow,
    uthrow: MoveId::SamuraiTossUp,
    dthrow: MoveId::SamuraiPin,
};

/// The soldier uses his own grab, dash grab, pummel and all four throws, unlike the
/// samurai, which shares the chef's.
static SOLDIER_MOVES: Moveset = Moveset {
    jab: MoveId::SoldierButtStrike,
    ftilt: MoveId::SoldierBayonet,
    utilt: MoveId::SoldierRifleUp,
    dtilt: MoveId::SoldierLegSweep,
    dash_attack: MoveId::SoldierShoulderCharge,
    fsmash: MoveId::SoldierStockSmash,
    usmash: MoveId::SoldierBayonetUpper,
    dsmash: MoveId::SoldierStockSweep,
    nair: MoveId::SoldierAirSpin,
    fair: MoveId::SoldierAirBayonet,
    bair: MoveId::SoldierBackElbow,
    uair: MoveId::SoldierAirUp,
    dair: MoveId::SoldierAirStomp,
    neutral_special: MoveId::SoldierRifleShot,
    side_special: MoveId::SoldierGrenade,
    up_special: MoveId::SoldierBlastJump,
    down_special: MoveId::SoldierRiotShield,
    grab: MoveId::SoldierGrab,
    dash_grab: MoveId::SoldierDashGrab,
    pummel: MoveId::SoldierPummel,
    fthrow: MoveId::SoldierThrowForward,
    bthrow: MoveId::SoldierThrowBack,
    uthrow: MoveId::SoldierThrowUp,
    dthrow: MoveId::SoldierThrowDown,
};

impl Character {
    pub const ALL: [Character; 4] = [Character::Chef, Character::Pug, Character::Samurai, Character::Soldier];

    pub fn name(self) -> &'static str {
        match self {
            Character::Chef => "Chef",
            Character::Pug => "Pug",
            Character::Samurai => "Samurai",
            Character::Soldier => "Soldier",
        }
    }

    pub fn params(self) -> &'static FighterParams {
        match self {
            Character::Chef => &FighterParams::CHEF,
            Character::Pug => &FighterParams::PUG,
            Character::Samurai => &FighterParams::SAMURAI,
            Character::Soldier => &FighterParams::SOLDIER,
        }
    }

    pub fn moveset(self) -> &'static Moveset {
        match self {
            Character::Chef => &CHEF_MOVES,
            Character::Pug => &PUG_MOVES,
            Character::Samurai => &SAMURAI_MOVES,
            Character::Soldier => &SOLDIER_MOVES,
        }
    }

    /// Every move this character can be in: its moveset plus the follow-ups those
    /// moves lead to. Each needs an animation of the same name in its model.
    pub fn moves(self) -> Vec<MoveId> {
        let mut moves: Vec<MoveId> = Vec::new();
        let mut todo: Vec<MoveId> = self.moveset().slots().to_vec();
        while let Some(mv) = todo.pop() {
            if moves.contains(&mv) {
                continue;
            }
            moves.push(mv);
            let data = mv.data();
            todo.extend(data.combo.map(|(next, _)| next));
            todo.extend(data.counter.as_ref().map(|c| c.into));
            todo.extend(data.on_grab);
            if let Landing::Into(next) = data.landing {
                todo.push(next);
            }
        }
        moves
    }
}
