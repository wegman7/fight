//! Deterministic platform-fighter simulation.
//!
//! Everything here is engine-agnostic: the renderer (Godot, via the `fight_gd`
//! crate) feeds one [`Input`] per player into [`World::step`] at a fixed 60 Hz
//! and draws whatever state comes out. All gameplay math uses [`Fx`]
//! fixed-point so the same inputs produce bit-identical results on every
//! platform — a prerequisite for replays and rollback netcode.

pub mod cpu;
pub mod fighter;
pub mod fixed;
pub mod input;
pub mod moves;
pub mod stage;
pub mod world;

pub use cpu::{Cpu, CpuLevel};
pub use fighter::{Fighter, FighterParams, State};
pub use fixed::Fx;
pub use input::Input;
pub use moves::{Hitbox, MoveData, MoveId};
pub use stage::{Platform, Stage};
pub use world::{ActiveHitbox, Event, World};
