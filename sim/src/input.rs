use crate::fixed::Fx;

/// One player's controller state for one frame. This is the only thing that
/// enters the simulation, and exactly what rollback netcode would send.
#[derive(Clone, Copy, Default, Debug, PartialEq, Eq, Hash)]
pub struct Input {
    /// -100 (left) ..= 100 (right).
    pub stick_x: i8,
    /// -100 (down) ..= 100 (up).
    pub stick_y: i8,
    pub buttons: u8,
}

impl Input {
    pub const ATTACK: u8 = 1 << 0;
    pub const JUMP: u8 = 1 << 1;
    pub const SPECIAL: u8 = 1 << 2;
    pub const SHIELD: u8 = 1 << 3;
    pub const GRAB: u8 = 1 << 4;
    /// Attack as a smash attack in the stick's direction (forward if neutral).
    /// The C-stick / "strong attack" button; flicking the stick with ATTACK does the same.
    pub const SMASH: u8 = 1 << 5;

    pub fn held(&self, button: u8) -> bool {
        self.buttons & button != 0
    }

    pub fn stick(&self) -> (Fx, Fx) {
        let axis = |v: i8| Fx::ratio(v.clamp(-100, 100) as i64, 100);
        (axis(self.stick_x), axis(self.stick_y))
    }
}
