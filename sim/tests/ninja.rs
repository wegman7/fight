//! The ninja's own moveset and tuning. P1 (fighter 0, standing at x = -40 facing
//! right) is the ninja unless a test says otherwise; P2 is a chef standing in as the
//! target.

use fight_sim::{Character, Event, Fx, Input, MoveId, Stage, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Ninja, Character::Chef], 3)
}

fn press(buttons: u8) -> Input {
    Input { buttons, ..NONE }
}

fn input(x: i8, y: i8, buttons: u8) -> Input {
    Input { stick_x: x, stick_y: y, buttons }
}

fn airborne(w: &mut World, i: usize, x: i32, y: i32) {
    let f = &mut w.fighters[i];
    (f.x, f.y, f.grounded_on, f.state, f.facing) = (Fx::int(x), Fx::int(y), None, State::Air, 1);
}

fn mv(w: &World, i: usize) -> Option<MoveId> {
    match w.fighters[i].state {
        State::Attack { mv, .. } => Some(mv),
        _ => None,
    }
}

fn run(w: &mut World, frames: usize, p1: Input, p2: Input) {
    for _ in 0..frames {
        w.step(&[p1, p2]);
    }
}

#[test]
fn ninja_is_the_lightest_and_fastest() {
    let w = world();
    assert_eq!(w.fighters[0].character, Character::Ninja);
    assert_eq!(w.fighters[0].params, Character::Ninja.params());
    let ninja = w.fighters[0].params;
    let chef = w.fighters[1].params;
    for character in Character::ALL {
        assert!(ninja.weight <= character.params().weight, "lighter than {}", character.name());
    }
    assert!(ninja.run_speed > chef.run_speed);
    assert!(ninja.air_speed > chef.air_speed);
    assert!(ninja.ground_accel > chef.ground_accel);
    assert!(ninja.jump_squat < chef.jump_squat);
    assert!(ninja.landing_lag < chef.landing_lag);
}

#[test]
fn ninja_moves_are_all_his_own() {
    let moves = Character::Ninja.moves();
    for follow_up in [MoveId::NinjaKunai2, MoveId::NinjaKunai3, MoveId::NinjaSubstitutionStrike] {
        assert!(moves.contains(&follow_up), "{follow_up:?}");
    }
    // Unlike the samurai, the ninja doesn't share the chef's grab, dash grab or pummel.
    for shared in [MoveId::Grab, MoveId::DashGrab, MoveId::Pummel] {
        assert!(!moves.contains(&shared), "the ninja has his own {shared:?}");
    }
    assert!(!moves.contains(&MoveId::Jab));
    assert!(!moves.contains(&MoveId::FThrow));

    // Every one of the 24 moveset slots is a distinct ninja move.
    let ms = Character::Ninja.moveset();
    let slots = [
        ms.jab, ms.ftilt, ms.utilt, ms.dtilt, ms.dash_attack, ms.fsmash, ms.usmash, ms.dsmash, ms.nair, ms.fair, ms.bair, ms.uair, ms.dair,
        ms.neutral_special, ms.side_special, ms.up_special, ms.down_special, ms.grab, ms.dash_grab, ms.pummel, ms.fthrow, ms.bthrow,
        ms.uthrow, ms.dthrow,
    ];
    for (i, &a) in slots.iter().enumerate() {
        assert!(a.data().name.starts_with("ninja_"), "slot {i} is {:?} ({})", a, a.data().name);
        for &b in &slots[i + 1..] {
            assert_ne!(a, b, "two slots share {a:?}");
        }
    }
}

#[test]
fn ninja_inputs_start_ninja_moves() {
    let ground = [
        (0, 0, Input::ATTACK, MoveId::NinjaKunai),
        (60, 0, Input::ATTACK, MoveId::NinjaPalmThrust),
        (0, 60, Input::ATTACK, MoveId::NinjaRisingChop),
        (0, -60, Input::ATTACK, MoveId::NinjaSweep),
        (0, 0, Input::SMASH, MoveId::NinjaChop),
        (0, 100, Input::SMASH, MoveId::NinjaFlipKick),
        (0, -100, Input::SMASH, MoveId::NinjaSpinKick),
        (0, 0, Input::SPECIAL, MoveId::NinjaShuriken),
        (100, 0, Input::SPECIAL, MoveId::NinjaShadowDash),
        (0, 100, Input::SPECIAL, MoveId::NinjaSmokeBomb),
        (0, -100, Input::SPECIAL, MoveId::NinjaSubstitution),
        (0, 0, Input::GRAB, MoveId::NinjaGrab),
    ];
    for (x, y, buttons, expected) in ground {
        let mut w = world();
        w.step(&[input(x, y, buttons), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
    let air = [
        (0, 0, MoveId::NinjaAirSpin),
        (100, 0, MoveId::NinjaFlyingKick),
        (-100, 0, MoveId::NinjaBackHook),
        (0, 100, MoveId::NinjaUpFlip),
        (0, -100, MoveId::NinjaAxeKick),
    ];
    for (x, y, expected) in air {
        let mut w = world();
        airborne(&mut w, 0, 0, 150);
        w.step(&[input(x, y, Input::ATTACK), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
}

#[test]
fn kunai_chains_into_a_finisher() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-34);
    let mut seen = Vec::new();
    for f in 0..60 {
        w.step(&[press(if matches!(f, 0 | 6 | 12) { Input::ATTACK } else { 0 }), NONE]);
        if let State::Attack { mv, frame: 1, .. } = w.fighters[0].state {
            seen.push(mv);
        }
    }
    assert_eq!(seen, [MoveId::NinjaKunai, MoveId::NinjaKunai2, MoveId::NinjaKunai3]);
    assert_eq!(w.fighters[1].percent, 2 + 2 + 4);
}

#[test]
fn shuriken_fires_on_frame_10_and_hits() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-20);
    w.step(&[press(Input::SPECIAL), NONE]);
    run(&mut w, 8, NONE, NONE);
    assert!(w.projectiles.is_empty());
    w.step(&[NONE, NONE]);
    assert_eq!(w.projectiles.len(), 1, "fired on frame 10");
    let sh = &w.projectiles[0];
    assert_eq!(sh.mv, MoveId::NinjaShuriken);
    assert_eq!(sh.vy, Fx::ZERO, "a shuriken flies straight, no arc");
    assert!(sh.vx > Fx::ZERO);
    for _ in 0..20 {
        w.step(&[NONE, NONE]);
        if w.fighters[1].percent > 0 {
            break;
        }
    }
    assert_eq!(w.fighters[1].percent, 5);
    assert!(w.projectiles.is_empty(), "the shuriken is used up on the hit");
}

#[test]
fn shadow_dash_is_intangible_and_dashes_past_the_target() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-28);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::NinjaShadowDash));
    run(&mut w, 4, NONE, NONE);
    assert_eq!(w.fighters[0].x, Fx::int(-40), "the windup holds him in place");
    run(&mut w, 1, NONE, NONE);
    assert!(!w.fighters[0].hittable(), "intangible during the dash");
    run(&mut w, 8, NONE, NONE);
    assert!(w.fighters[0].x > Fx::int(-28), "dashed past where P2 stood");
    assert!(w.fighters[0].x < Fx::int(-5), "and stopped after the dash");
    assert_eq!(w.fighters[1].percent, 6, "the slash hits as it passes");
}

#[test]
fn shadow_dash_passes_through_a_jab_unhurt() {
    // P2 faces the oncoming ninja and jabs as he dashes through: the intangibility
    // lets the ninja pass through the hitbox without taking damage.
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.fighters[1].facing = 1;
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    run(&mut w, 6, NONE, NONE); // dash underway
    for _ in 0..8 {
        w.step(&[NONE, press(Input::ATTACK)]);
    }
    assert_eq!(w.fighters[0].percent, 0, "intangible while dashing through the jab");
}

#[test]
fn smoke_bomb_vanishes_and_reappears_higher_then_helpless() {
    let mut w = world();
    airborne(&mut w, 0, 0, 100);
    w.step(&[input(0, 100, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::NinjaSmokeBomb));
    run(&mut w, 6, NONE, NONE);
    assert_eq!(w.fighters[0].y, Fx::int(100), "hasn't moved before the teleport");
    assert!(!w.fighters[0].hittable(), "intangible while it vanishes");
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[0].y, Fx::int(134), "teleported 34 units up on frame 8");
    run(&mut w, 33, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::SpecialFall);
}

#[test]
fn substitution_counters_a_hit_and_strikes_back() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Ninja], 3);
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    assert_eq!(mv(&w, 1), Some(MoveId::NinjaSubstitution));
    run(&mut w, 5, NONE, NONE);
    // The chef's jab lands on its frame 2: the ninja's frame 8, inside the window.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert!(w.events.iter().any(|e| matches!(e, Event::Counter { fighter: 1, attacker: 0, .. })), "{:?}", w.events);
    assert_eq!(w.fighters[1].percent, 0, "countered hits do no damage");
    assert_eq!(mv(&w, 1), Some(MoveId::NinjaSubstitutionStrike));
    assert_eq!(w.fighters[1].facing, -1, "turned toward the attacker");
    assert!(w.fighters[1].intangible > 0);

    run(&mut w, 28, NONE, NONE);
    assert_eq!(w.fighters[0].percent, 12, "the strike lands");
    assert_eq!(w.fighters[1].percent, 0);
}

#[test]
fn substitution_too_late_just_gets_hit() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Ninja], 3);
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    run(&mut w, 25, NONE, NONE);
    // Jab lands on the ninja's frame 28, after the window closed on 24.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[1].percent, 3);
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
}

/// The ninja grabs P2 (standing at x = -32).
fn grabbed() -> World {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[press(Input::GRAB), NONE]);
    run(&mut w, 6, NONE, NONE);
    w
}

#[test]
fn ninja_grab_pummel_and_throws() {
    let w = grabbed();
    assert_eq!(w.fighters[0].holding, Some(1));

    for (x, y, throw, damage) in [
        (60, 0, MoveId::NinjaThrowForward, 7),
        (-60, 0, MoveId::NinjaThrowBack, 9),
        (0, 60, MoveId::NinjaThrowUp, 6),
        (0, -60, MoveId::NinjaThrowDown, 5),
    ] {
        let mut w = grabbed();
        w.step(&[input(x, y, 0), NONE]);
        assert_eq!(mv(&w, 0), Some(throw));
        run(&mut w, 25, NONE, NONE);
        let (thrower, victim) = (&w.fighters[0], &w.fighters[1]);
        assert_eq!(victim.percent, damage, "{throw:?}");
        assert_eq!(thrower.holding, None, "{throw:?}");
        if throw == MoveId::NinjaThrowBack {
            assert!(victim.x < thrower.x, "thrown behind");
        }
    }

    let mut w = grabbed();
    w.step(&[press(Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::NinjaPummel));
}

#[test]
fn axe_kick_meteors() {
    let mut w = world();
    airborne(&mut w, 0, 0, 150);
    airborne(&mut w, 1, 0, 140);
    w.fighters[1].percent = 50;
    // -60: past the tilt threshold without the down tap that would fast-fall.
    w.step(&[input(0, -60, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::NinjaAxeKick));
    let mut sent_down = false;
    for _ in 0..20 {
        w.step(&[NONE, NONE]);
        sent_down |= w.fighters[1].kb_y < Fx::ZERO;
    }
    assert!(sent_down);
}

#[test]
fn ninja_matches_resimulate_bit_identically() {
    let play = |w: &mut World| {
        for f in 0..600u32 {
            let axis = |n: u32| ((n % 201) as i32 - 100) as i8;
            let p1 = input(axis(f * 37), axis(f * 53), (f % 7) as u8 * 3);
            let p2 = input(axis(f * 11), 0, ((f * 5) % 64) as u8);
            w.step(&[p1, p2]);
        }
    };
    let mut a = World::new(Stage::battlefield(), &[Character::Ninja, Character::Pug], 3);
    let mut b = a.clone();
    play(&mut a);
    play(&mut b);
    assert_eq!(a, b);
}
