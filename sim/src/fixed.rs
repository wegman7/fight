//! Q16.16 fixed-point numbers and integer-degree trig.
//!
//! Floats can differ in the last bit between CPUs/compilers (FMA fusion, libm
//! implementations), which desyncs rollback netcode. Integer math can't.

use core::fmt;
use core::ops::{Add, AddAssign, Div, Mul, Neg, Sub, SubAssign};

#[derive(Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Fx(i32);

impl Fx {
    pub const FRAC_BITS: u32 = 16;
    pub const ZERO: Fx = Fx(0);
    pub const ONE: Fx = Fx(1 << Self::FRAC_BITS);

    pub const fn from_raw(raw: i32) -> Fx {
        Fx(raw)
    }

    pub const fn raw(self) -> i32 {
        self.0
    }

    pub const fn int(n: i32) -> Fx {
        Fx(n << Self::FRAC_BITS)
    }

    /// `num / den`, usable in consts: `Fx::ratio(95, 1000)` is 0.095.
    pub const fn ratio(num: i64, den: i64) -> Fx {
        Fx(((num << Self::FRAC_BITS) / den) as i32)
    }

    /// For rendering only — never feed the result back into the simulation.
    pub fn to_f32(self) -> f32 {
        self.0 as f32 / (1 << Self::FRAC_BITS) as f32
    }

    pub const fn floor_to_int(self) -> i32 {
        self.0 >> Self::FRAC_BITS
    }

    pub const fn abs(self) -> Fx {
        Fx(self.0.abs())
    }

    pub const fn signum(self) -> i32 {
        self.0.signum()
    }

    /// Length of the vector (x, y), via an integer square root.
    pub fn hypot(x: Fx, y: Fx) -> Fx {
        let (x, y) = (x.0 as i64, y.0 as i64);
        Fx(isqrt(x * x + y * y) as i32)
    }

    /// Moves `self` toward `target` by at most `step` (which must be >= 0).
    pub fn approach(self, target: Fx, step: Fx) -> Fx {
        if self < target {
            (self + step).min(target)
        } else {
            (self - step).max(target)
        }
    }
}

impl fmt::Debug for Fx {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:.4}", self.to_f32())
    }
}

impl Add for Fx {
    type Output = Fx;
    fn add(self, rhs: Fx) -> Fx {
        Fx(self.0 + rhs.0)
    }
}

impl Sub for Fx {
    type Output = Fx;
    fn sub(self, rhs: Fx) -> Fx {
        Fx(self.0 - rhs.0)
    }
}

impl Neg for Fx {
    type Output = Fx;
    fn neg(self) -> Fx {
        Fx(-self.0)
    }
}

impl Mul for Fx {
    type Output = Fx;
    fn mul(self, rhs: Fx) -> Fx {
        Fx(((self.0 as i64 * rhs.0 as i64) >> Self::FRAC_BITS) as i32)
    }
}

impl Mul<i32> for Fx {
    type Output = Fx;
    fn mul(self, rhs: i32) -> Fx {
        Fx(self.0 * rhs)
    }
}

impl Div for Fx {
    type Output = Fx;
    fn div(self, rhs: Fx) -> Fx {
        Fx((((self.0 as i64) << Self::FRAC_BITS) / rhs.0 as i64) as i32)
    }
}

impl AddAssign for Fx {
    fn add_assign(&mut self, rhs: Fx) {
        self.0 += rhs.0;
    }
}

impl SubAssign for Fx {
    fn sub_assign(&mut self, rhs: Fx) {
        self.0 -= rhs.0;
    }
}

/// floor(sqrt(n)) for n >= 0, by Newton's method on integers.
fn isqrt(n: i64) -> i64 {
    if n < 2 {
        return n.max(0);
    }
    let mut x = n;
    let mut y = (x + 1) / 2;
    while y < x {
        x = y;
        y = (x + n / x) / 2;
    }
    x
}

/// sin(0..=90 degrees) in Q16.16, precomputed so trig is a table lookup.
const SIN_TABLE: [i32; 91] = [
    0, 1144, 2287, 3430, 4572, 5712, 6850, 7987, 9121, 10252, //
    11380, 12505, 13626, 14742, 15855, 16962, 18064, 19161, 20252, 21336, //
    22415, 23486, 24550, 25607, 26656, 27697, 28729, 29753, 30767, 31772, //
    32768, 33754, 34729, 35693, 36647, 37590, 38521, 39441, 40348, 41243, //
    42126, 42995, 43852, 44695, 45525, 46341, 47143, 47930, 48703, 49461, //
    50203, 50931, 51643, 52339, 53020, 53684, 54332, 54963, 55578, 56175, //
    56756, 57319, 57865, 58393, 58903, 59396, 59870, 60326, 60764, 61183, //
    61584, 61966, 62328, 62672, 62997, 63303, 63589, 63856, 64104, 64332, //
    64540, 64729, 64898, 65048, 65177, 65287, 65376, 65446, 65496, 65526, //
    65536,
];

pub fn sin_deg(deg: i32) -> Fx {
    let d = deg.rem_euclid(360);
    let (idx, sign) = match d {
        0..=90 => (d, 1),
        91..=180 => (180 - d, 1),
        181..=270 => (d - 180, -1),
        _ => (360 - d, -1),
    };
    Fx(SIN_TABLE[idx as usize] * sign)
}

pub fn cos_deg(deg: i32) -> Fx {
    sin_deg(deg + 90)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arithmetic() {
        assert_eq!(Fx::int(3) * Fx::int(4), Fx::int(12));
        assert_eq!(Fx::int(10) / Fx::int(4), Fx::ratio(5, 2));
        assert_eq!(Fx::ratio(-3, 2).floor_to_int(), -2);
        assert_eq!(Fx::int(5).approach(Fx::ZERO, Fx::int(2)), Fx::int(3));
        assert_eq!(Fx::int(1).approach(Fx::ZERO, Fx::int(2)), Fx::ZERO);
        assert_eq!(Fx::hypot(Fx::int(3), Fx::int(-4)), Fx::int(5));
        assert!((Fx::hypot(Fx::ONE, Fx::ONE).to_f32() - core::f32::consts::SQRT_2).abs() < 1e-4);
    }

    #[test]
    fn trig() {
        assert_eq!(sin_deg(0), Fx::ZERO);
        assert_eq!(sin_deg(90), Fx::ONE);
        assert_eq!(sin_deg(270), -Fx::ONE);
        assert_eq!(cos_deg(0), Fx::ONE);
        assert_eq!(cos_deg(180), -Fx::ONE);
        assert_eq!(sin_deg(-90), -Fx::ONE);
        assert!((sin_deg(45).to_f32() - core::f32::consts::FRAC_1_SQRT_2).abs() < 1e-4);
    }
}
