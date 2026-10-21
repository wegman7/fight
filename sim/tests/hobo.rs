//! The drunk hobo's own moveset and tuning. P1 (fighter 0, standing at x = -40 facing
//! right) is the hobo unless a test says otherwise; P2 is a chef standing in as the
//! target.

use fight_sim::{Character, Event, Fx, Input, MoveId, Stage, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Hobo, Character::Chef], 3)
}

fn press(buttons: u8) -> Input {
    Input { buttons, ..NONE }
}

fn stick(x: i8, y: i8) -> Input {
    Input { stick_x: x, stick_y: y, buttons: 0 }
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
fn hobo_is_floaty_and_wobbly() {
    let w = world();
    assert_eq!(w.fighters[0].character, Character::Hobo);
    assert_eq!(w.fighters[0].params, Character::Hobo.params());
    assert_eq!(w.fighters[1].params, Character::Chef.params());
    let (hobo, chef) = (w.fighters[0].params, w.fighters[1].params);
    assert_eq!(hobo.height, chef.height, "the chef's height, so the skeleton fits");
    assert!(hobo.weight < chef.weight, "lighter: {weight}", weight = hobo.weight);
    assert!(hobo.gravity < chef.gravity, "floatier: slower to fall");
    assert!(hobo.max_fall < chef.max_fall, "lower top fall speed");
    assert!(hobo.air_speed > chef.air_speed, "drifts more in the air");
    assert!(hobo.traction < chef.traction, "slides on the ground");
}

#[test]
fn every_hobo_slot_is_his_own_move() {
    let moves = Character::Hobo.moves();
    for follow_up in [MoveId::HoboSlap2, MoveId::HoboSlap3, MoveId::HoboJolt] {
        assert!(moves.contains(&follow_up), "{follow_up:?}");
    }
    // Unlike the samurai, the hobo shares no moves with the chef — not even the grab.
    for shared in [MoveId::Grab, MoveId::DashGrab, MoveId::Pummel, MoveId::Jab, MoveId::FThrow] {
        assert!(!moves.contains(&shared), "should not use {shared:?}");
    }
    // 24 slots plus the two jab follow-ups and the counter's answer, each named `hobo_*`.
    assert_eq!(moves.len(), 27);
    assert!(moves.iter().all(|m| m.data().name.starts_with("hobo_")), "{moves:?}");
    let mut names: Vec<&str> = moves.iter().map(|m| m.data().name).collect();
    names.sort();
    names.dedup();
    assert_eq!(names.len(), moves.len(), "two moves share one animation name");
}

#[test]
fn hobo_inputs_start_hobo_moves() {
    let ground = [
        (0, 0, Input::ATTACK, MoveId::HoboSlap),
        (60, 0, Input::ATTACK, MoveId::HoboPunch),
        (0, 60, Input::ATTACK, MoveId::HoboUpSwing),
        (0, -60, Input::ATTACK, MoveId::HoboTrip),
        (0, 0, Input::SMASH, MoveId::HoboBottleSwing),
        (0, 100, Input::SMASH, MoveId::HoboUpHeave),
        (0, -100, Input::SMASH, MoveId::HoboSpinFlail),
        (0, 0, Input::SPECIAL, MoveId::HoboBottleThrow),
        (100, 0, Input::SPECIAL, MoveId::HoboCartCharge),
        (0, 100, Input::SPECIAL, MoveId::HoboFizzRocket),
        (0, -100, Input::SPECIAL, MoveId::HoboPassedOut),
        (0, 0, Input::GRAB, MoveId::HoboGrab),
    ];
    for (x, y, buttons, expected) in ground {
        let mut w = world();
        w.step(&[input(x, y, buttons), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
    let air = [
        (0, 0, MoveId::HoboFlail),
        (100, 0, MoveId::HoboHaymaker),
        (-100, 0, MoveId::HoboBackhand),
        (0, 100, MoveId::HoboUpFlail),
        (0, -100, MoveId::HoboStomp),
    ];
    for (x, y, expected) in air {
        let mut w = world();
        airborne(&mut w, 0, 0, 150);
        w.step(&[input(x, y, Input::ATTACK), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
}

#[test]
fn running_attack_is_the_stumble() {
    let mut w = world();
    run(&mut w, 8, stick(100, 0), NONE);
    assert!(w.fighters[0].vx > w.fighters[0].params.walk_speed, "should be running");
    w.step(&[input(100, 0, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::HoboStumble));
}

#[test]
fn slaps_chain_into_a_shove() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-31);
    let mut seen = Vec::new();
    for f in 0..60 {
        w.step(&[press(if f % 6 == 0 { Input::ATTACK } else { 0 }), NONE]);
        if let State::Attack { mv, frame: 1, .. } = w.fighters[0].state {
            seen.push(mv);
        }
    }
    assert_eq!(seen, [MoveId::HoboSlap, MoveId::HoboSlap2, MoveId::HoboSlap3]);
    assert_eq!(w.fighters[1].percent, 3 + 3 + 6);
}

/// Throws the bottle and steps until it shatters. Returns (peak height, events).
fn thrown_and_shattered(w: &mut World) -> Fx {
    w.step(&[press(Input::SPECIAL), NONE]);
    assert_eq!(mv(w, 0), Some(MoveId::HoboBottleThrow));
    run(w, 10, NONE, NONE); // frames 2..11: the bottle hasn't left yet
    assert!(w.projectiles.is_empty());
    w.step(&[NONE, NONE]); // frame 12: it fires
    assert_eq!(w.projectiles.len(), 1);
    let mut peak = w.projectiles[0].y;
    for _ in 0..90 {
        w.step(&[NONE, NONE]);
        peak = peak.max(w.projectiles.first().map_or(Fx::ZERO, |p| p.y));
        if w.events.iter().any(|e| matches!(e, Event::Shatter { .. })) {
            return peak;
        }
    }
    panic!("the bottle never landed and shattered");
}

#[test]
fn bottle_arcs_then_shatters_and_catches_a_nearby_fighter() {
    // P2 stands 80 units ahead: just past where the bottle comes down, so it's inside
    // the shatter's blast but the bottle never beans it mid-flight.
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(40);
    let peak = thrown_and_shattered(&mut w);
    assert!(peak > Fx::int(7), "the bottle rose above its throw height: peak {peak:?}");
    assert!(w.projectiles.is_empty(), "shattered, so it's gone");
    assert!(w.events.iter().any(|e| matches!(e, Event::ProjectileLanded { .. })));
    // The shatter — not a direct 5% hit — caught P2.
    assert!(w.events.iter().any(|e| matches!(e, Event::Hit { defender: 1, damage: 6, projectile: false, .. })), "{:?}", w.events);
    assert_eq!(w.fighters[1].percent, 6);
}

#[test]
fn cart_charge_is_fast_strong_and_wobbly() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-26);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::HoboCartCharge));
    let start = w.fighters[0].x;
    run(&mut w, 20, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 12, "plowed through P2");
    assert!(w.fighters[0].x - start > Fx::int(15), "moved {:?}", w.fighters[0].x - start);
    // Still in the move's long coast-out: the wobbly recovery.
    assert_eq!(mv(&w, 0), Some(MoveId::HoboCartCharge));
    run(&mut w, 40, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::Ground);
}

#[test]
fn fizz_rocket_climbs_steers_and_ends_helpless() {
    let climb = |drift: i8| {
        let mut w = world();
        airborne(&mut w, 0, 0, 100);
        w.step(&[input(0, 100, Input::SPECIAL), NONE]);
        assert_eq!(mv(&w, 0), Some(MoveId::HoboFizzRocket));
        let mut peak = Fx::ZERO;
        for _ in 2..=44 {
            w.step(&[stick(drift, 0), NONE]);
            peak = peak.max(w.fighters[0].y);
        }
        w.step(&[NONE, NONE]);
        assert_eq!(w.fighters[0].state, State::SpecialFall);
        (peak, w.fighters[0].x)
    };
    let (peak, x) = climb(0);
    assert!(peak >= Fx::int(100 + 34), "peak {peak:?}");
    let (_, steered) = climb(100);
    assert!(steered > x + Fx::int(10), "steered to {steered:?}");
}

#[test]
fn passed_out_counters_a_hit_and_jolts_awake() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Hobo], 3);
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    assert_eq!(mv(&w, 1), Some(MoveId::HoboPassedOut));
    run(&mut w, 5, NONE, NONE);
    // The chef's jab lands on its frame 2: the hobo's frame 8, inside the window.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert!(w.events.iter().any(|e| matches!(e, Event::Counter { fighter: 1, attacker: 0, .. })), "{:?}", w.events);
    assert_eq!(w.fighters[1].percent, 0, "countered hits do no damage");
    assert_eq!(mv(&w, 1), Some(MoveId::HoboJolt));
    assert_eq!(w.fighters[1].facing, -1, "turned toward the attacker");
    assert!(w.fighters[1].intangible > 0);

    run(&mut w, 30, NONE, NONE);
    assert_eq!(w.fighters[0].percent, 12, "the jolt lands");
    assert_eq!(w.fighters[1].percent, 0);
}

#[test]
fn passed_out_outside_its_window_just_gets_hit() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Hobo], 3);
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    run(&mut w, 27, NONE, NONE);
    // Jab lands on the hobo's frame 30, after the window closed on 28.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[1].percent, 3);
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
}

/// The hobo grabs P2 (standing at x = -32).
fn grabbed() -> World {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[press(Input::GRAB), NONE]);
    run(&mut w, 7, NONE, NONE);
    w
}

#[test]
fn hobo_grab_pummel_and_throws() {
    let w = grabbed();
    assert_eq!(w.fighters[0].holding, Some(1));

    for (x, y, throw, damage) in [
        (60, 0, MoveId::HoboThrowForward, 8),
        (-60, 0, MoveId::HoboThrowBack, 11),
        (0, 60, MoveId::HoboThrowUp, 7),
        (0, -60, MoveId::HoboThrowDown, 6),
    ] {
        let mut w = grabbed();
        w.step(&[stick(x, y), NONE]);
        assert_eq!(mv(&w, 0), Some(throw));
        run(&mut w, 25, NONE, NONE);
        let (thrower, victim) = (&w.fighters[0], &w.fighters[1]);
        assert_eq!(victim.percent, damage, "{throw:?}");
        assert_eq!(thrower.holding, None, "{throw:?}");
        if throw == MoveId::HoboThrowBack {
            assert!(victim.x < thrower.x, "thrown behind");
        }
    }

    let mut w = grabbed();
    w.step(&[press(Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::HoboPummel));
}

#[test]
fn hobo_matches_resimulate_bit_identically() {
    let play = |w: &mut World| {
        for f in 0..600u32 {
            let axis = |n: u32| ((n % 201) as i32 - 100) as i8;
            let p1 = input(axis(f * 37), axis(f * 53), (f % 7) as u8 * 3);
            let p2 = input(axis(f * 11), 0, ((f * 5) % 64) as u8);
            w.step(&[p1, p2]);
        }
    };
    let mut a = World::new(Stage::battlefield(), &[Character::Hobo, Character::Pug], 3);
    let mut b = a.clone();
    play(&mut a);
    play(&mut b);
    assert_eq!(a, b);
}
