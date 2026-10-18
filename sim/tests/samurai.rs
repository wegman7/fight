//! The samurai's own moveset and tuning. P1 (fighter 0, standing at x = -40 facing
//! right) is the samurai unless a test says otherwise; P2 is a chef standing in as the
//! target.

use fight_sim::{Character, Event, Fx, Input, MoveId, Stage, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Samurai, Character::Chef], 3)
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
fn samurai_is_the_chefs_height_heavier_and_slower_to_run() {
    let w = world();
    assert_eq!(w.fighters[0].character, Character::Samurai);
    assert_eq!(w.fighters[0].params, Character::Samurai.params());
    let (samurai, chef) = (w.fighters[0].params, w.fighters[1].params);
    assert_eq!(samurai.height, chef.height);
    assert!(samurai.weight > chef.weight);
    assert!(samurai.run_speed < chef.run_speed);
}

#[test]
fn samurai_moves_are_his_own_except_the_grab() {
    let moves = Character::Samurai.moves();
    for follow_up in [MoveId::SamuraiSlash2, MoveId::SamuraiThrust, MoveId::SamuraiRiposte] {
        assert!(moves.contains(&follow_up), "{follow_up:?}");
    }
    for shared in [MoveId::Grab, MoveId::DashGrab, MoveId::Pummel] {
        assert!(moves.contains(&shared), "{shared:?}");
    }
    assert!(!moves.contains(&MoveId::Jab));
    assert!(!moves.contains(&MoveId::FThrow));
}

#[test]
fn samurai_inputs_start_samurai_moves() {
    let ground = [
        (0, 0, Input::ATTACK, MoveId::SamuraiSlash),
        (60, 0, Input::ATTACK, MoveId::SamuraiForwardCut),
        (0, 60, Input::ATTACK, MoveId::SamuraiRisingCut),
        (0, -60, Input::ATTACK, MoveId::SamuraiLowCut),
        (0, 0, Input::SMASH, MoveId::SamuraiCleave),
        (0, 100, Input::SMASH, MoveId::SamuraiSkyCut),
        (0, -100, Input::SMASH, MoveId::SamuraiSpinSweep),
        (0, 0, Input::SPECIAL, MoveId::SamuraiWindSlash),
        (100, 0, Input::SPECIAL, MoveId::SamuraiDashStrike),
        (0, 100, Input::SPECIAL, MoveId::SamuraiRisingDragon),
        (0, -100, Input::SPECIAL, MoveId::SamuraiParry),
        (0, 0, Input::GRAB, MoveId::Grab),
    ];
    for (x, y, buttons, expected) in ground {
        let mut w = world();
        w.step(&[input(x, y, buttons), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
    let air = [
        (0, 0, MoveId::SamuraiAirSpin),
        (100, 0, MoveId::SamuraiAirCut),
        (-100, 0, MoveId::SamuraiBackCut),
        (0, 100, MoveId::SamuraiSkyArc),
        (0, -100, MoveId::SamuraiPlungeStab),
    ];
    for (x, y, expected) in air {
        let mut w = world();
        airborne(&mut w, 0, 0, 150);
        w.step(&[input(x, y, Input::ATTACK), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
}

#[test]
fn slashes_chain_into_a_thrust() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-31);
    let mut seen = Vec::new();
    for f in 0..60 {
        w.step(&[press(if f % 6 == 0 { Input::ATTACK } else { 0 }), NONE]);
        if let State::Attack { mv, frame: 1, .. } = w.fighters[0].state {
            seen.push(mv);
        }
    }
    assert_eq!(seen, [MoveId::SamuraiSlash, MoveId::SamuraiSlash2, MoveId::SamuraiThrust]);
    assert_eq!(w.fighters[1].percent, 4 + 3 + 6);
}

/// Forward tilt at a target standing `distance` units in front.
fn forward_cut_at(distance: i32) -> i32 {
    let mut w = world();
    w.fighters[1].x = Fx::int(-40 + distance);
    w.step(&[input(60, 0, Input::ATTACK), NONE]);
    run(&mut w, 12, NONE, NONE);
    w.fighters[1].percent
}

#[test]
fn forward_cut_hits_hardest_with_the_tip() {
    assert_eq!(forward_cut_at(13), 11, "tip");
    assert_eq!(forward_cut_at(5), 8, "near the hilt");
}

#[test]
fn forward_cut_outreaches_the_chefs_kick() {
    let distance = 18;
    assert!(forward_cut_at(distance) > 0);
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Chef], 3);
    w.fighters[1].x = Fx::int(-40 + distance);
    w.step(&[input(60, 0, Input::ATTACK), NONE]);
    run(&mut w, 12, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 0);
}

/// Starts the wind slash, then feeds `held` every frame until it fires (frame 14).
fn wind_slash(w: &mut World, held: Input) {
    w.step(&[press(Input::SPECIAL), NONE]);
    for _ in 0..120 {
        if !w.projectiles.is_empty() {
            return;
        }
        w.step(&[held, NONE]);
    }
    panic!("no wind slash");
}

#[test]
fn tapped_wind_slash_fires_a_fast_blade_on_frame_14() {
    let mut w = world();
    w.step(&[press(Input::SPECIAL), NONE]);
    run(&mut w, 12, NONE, NONE);
    assert!(w.projectiles.is_empty());
    w.step(&[NONE, NONE]);
    assert_eq!(w.projectiles.len(), 1, "fired on frame 14");
    let blade = &w.projectiles[0];
    assert_eq!((blade.charge, blade.radius(), blade.damage(), blade.frames_left), (0, Fx::int(3), 6, 26));
    // Fast: it crosses to P2, standing 80 units away at x = 40, before it fades.
    run(&mut w, 26, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 6);
}

#[test]
fn a_fully_charged_wind_slash_is_bigger_and_stronger() {
    let mut w = world();
    wind_slash(&mut w, press(Input::SPECIAL));
    let blade = &w.projectiles[0];
    assert_eq!(blade.charge, 60, "fires by itself at full charge");
    assert_eq!((blade.radius(), blade.damage(), blade.base_kb(), blade.frames_left), (Fx::int(5), 14, 50, 40));
    assert_eq!(w.fighters[0].kb_x, Fx::ZERO, "no recoil");
}

#[test]
fn dash_strike_crosses_a_third_of_the_stage_once_per_airtime() {
    let mut w = world();
    airborne(&mut w, 0, -60, 150);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SamuraiDashStrike));
    let start = w.fighters[0].x;
    run(&mut w, 7, NONE, NONE);
    assert_eq!(w.fighters[0].x, start, "holds still while it winds up");
    run(&mut w, 39, NONE, NONE);
    assert!(w.fighters[0].x - start >= Fx::int(25), "moved {:?}", w.fighters[0].x - start);
    assert_eq!(w.fighters[0].state, State::Air);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(w.fighters[0].state, State::Air, "already used this airtime");
}

#[test]
fn dash_strike_cuts_through_a_target_in_its_path() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-15);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    run(&mut w, 20, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 12);
}

#[test]
fn rising_dragon_climbs_steers_and_ends_helpless() {
    let climb = |drift: i8| {
        // High in the air: it climbs fast enough to land again before it ends.
        let mut w = world();
        airborne(&mut w, 0, 0, 150);
        w.step(&[input(0, 100, Input::SPECIAL), NONE]);
        assert_eq!(mv(&w, 0), Some(MoveId::SamuraiRisingDragon));
        let mut peak = Fx::ZERO;
        for _ in 2..=46 {
            w.step(&[stick(drift, 0), NONE]);
            peak = peak.max(w.fighters[0].y);
        }
        w.step(&[NONE, NONE]);
        assert_eq!(w.fighters[0].state, State::SpecialFall);
        (peak, w.fighters[0].x)
    };
    let (peak, x) = climb(0);
    assert!(peak >= Fx::int(150 + 38), "peak {peak:?}");
    let (_, steered) = climb(100);
    assert!(steered > x + Fx::int(10), "steered to {steered:?}");
}

#[test]
fn parry_turns_a_hit_aside_and_ripostes() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Samurai], 3);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    assert_eq!(mv(&w, 1), Some(MoveId::SamuraiParry));
    run(&mut w, 5, NONE, NONE);
    // The chef's jab lands on its frame 2: the samurai's frame 8, inside the window.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert!(w.events.iter().any(|e| matches!(e, Event::Counter { fighter: 1, attacker: 0, .. })), "{:?}", w.events);
    assert_eq!(w.fighters[1].percent, 0);
    assert_eq!(mv(&w, 1), Some(MoveId::SamuraiRiposte));
    assert_eq!(w.fighters[1].facing, -1, "turned toward the attacker");

    run(&mut w, 30, NONE, NONE);
    assert_eq!(w.fighters[0].percent, 14, "the riposte lands");
    assert_eq!(w.fighters[1].percent, 0);
}

#[test]
fn parry_too_late_just_gets_hit() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Samurai], 3);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    run(&mut w, 25, NONE, NONE);
    // Jab lands on the samurai's frame 28, after the window closed on 24.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[1].percent, 3);
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
}

/// The samurai grabs P2 (standing at x = -32).
fn grabbed() -> World {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    w.step(&[press(Input::GRAB), NONE]);
    run(&mut w, 7, NONE, NONE);
    w
}

#[test]
fn samurai_throws() {
    let w = grabbed();
    assert_eq!(w.fighters[0].holding, Some(1));

    for (x, y, throw, damage) in [
        (60, 0, MoveId::SamuraiHipThrow, 8),
        (-60, 0, MoveId::SamuraiShoulderThrow, 11),
        (0, 60, MoveId::SamuraiTossUp, 7),
        (0, -60, MoveId::SamuraiPin, 6),
    ] {
        let mut w = grabbed();
        w.step(&[stick(x, y), NONE]);
        assert_eq!(mv(&w, 0), Some(throw));
        run(&mut w, 25, NONE, NONE);
        let (thrower, victim) = (&w.fighters[0], &w.fighters[1]);
        assert_eq!(victim.percent, damage, "{throw:?}");
        assert_eq!(thrower.holding, None, "{throw:?}");
        if throw == MoveId::SamuraiShoulderThrow {
            assert!(victim.x < thrower.x, "thrown behind");
        }
    }
}

#[test]
fn plunge_stab_meteors() {
    let mut w = world();
    airborne(&mut w, 0, 0, 150);
    airborne(&mut w, 1, 0, 140);
    w.fighters[1].percent = 50;
    // -60: past the tilt threshold without the down tap that would fast-fall.
    w.step(&[input(0, -60, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SamuraiPlungeStab));
    let mut sent_down = false;
    for _ in 0..20 {
        w.step(&[NONE, NONE]);
        sent_down |= w.fighters[1].kb_y < Fx::ZERO;
    }
    assert!(sent_down);
}

#[test]
fn samurai_matches_resimulate_bit_identically() {
    let play = |w: &mut World| {
        for f in 0..600u32 {
            let axis = |n: u32| ((n % 201) as i32 - 100) as i8;
            let p1 = input(axis(f * 37), axis(f * 53), (f % 7) as u8 * 3);
            let p2 = input(axis(f * 11), 0, ((f * 5) % 64) as u8);
            w.step(&[p1, p2]);
        }
    };
    let mut a = World::new(Stage::battlefield(), &[Character::Samurai, Character::Pug], 3);
    let mut b = a.clone();
    play(&mut a);
    play(&mut b);
    assert_eq!(a, b);
}
