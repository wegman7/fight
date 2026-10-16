//! Playable characters. Each has its own tuning ([`FighterParams`]) and its own
//! [`Moveset`]: which move every input starts.

use crate::fighter::FighterParams;
use crate::moves::{Landing, MoveId};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Character {
    /// The all-rounder: punches, kicks, an energy shot, an uppercut recovery and a ground pound.
    Mannequin,
    /// Small, light and quick, with two air jumps: bites, a chargeable sneeze, a pounce
    /// tackle that rides its target, an ear-flapping recovery and a play-dead counter.
    Pug,
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

static MANNEQUIN_MOVES: Moveset = Moveset {
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
    neutral_special: MoveId::NeutralSpecial,
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

impl Character {
    pub const ALL: [Character; 2] = [Character::Mannequin, Character::Pug];

    pub fn name(self) -> &'static str {
        match self {
            Character::Mannequin => "Mannequin",
            Character::Pug => "Pug",
        }
    }

    pub fn params(self) -> &'static FighterParams {
        match self {
            Character::Mannequin => &FighterParams::MANNEQUIN,
            Character::Pug => &FighterParams::PUG,
        }
    }

    pub fn moveset(self) -> &'static Moveset {
        match self {
            Character::Mannequin => &MANNEQUIN_MOVES,
            Character::Pug => &PUG_MOVES,
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
