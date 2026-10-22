//! Deterministic platform-fighter simulation.
//!
//! Everything here is engine-agnostic: the renderer (Godot, via the `fight_gd`
//! crate) feeds one [`Input`] per player into [`World::step`] at a fixed 60 Hz
//! and draws whatever state comes out. All gameplay math uses [`Fx`]
//! fixed-point so the same inputs produce bit-identical results on every
//! platform — a prerequisite for replays and rollback netcode.

pub mod character;
pub mod cpu;
pub mod fighter;
pub mod fixed;
pub mod input;
pub mod moves;
pub mod stage;
pub mod world;

pub use character::{Character, Moveset};
pub use cpu::{Cpu, CpuLevel};
pub use fighter::{Fighter, FighterParams, MAX_DI_DEGREES, SHIELD_MAX, STATE_ANIMS, State, Trajectory, di_angle, world_angle};
pub use fixed::Fx;
pub use input::Input;
pub use moves::{Counter, DodgeKind, Explosion, Hitbox, MoveData, MoveId, Shatter};
pub use stage::{Platform, STAGE_SCALE, Stage, StageId};
pub use world::{ActiveHitbox, Event, Projectile, World};
