//! The soldier's own moveset and tuning. P1 (fighter 0, standing at x = -40 facing
//! right) is the soldier unless a test says otherwise; P2 is a chef standing in as the
//! target.

use fight_sim::{Character, Event, Fx, Input, MoveId, Stage, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Soldier, Character::Chef], 3)
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
fn soldier_is_the_heaviest_slowest_and_falls_fast() {
    let w = world();
    assert_eq!(w.fighters[0].character, Character::Soldier);
    assert_eq!(w.fighters[0].params, Character::Soldier.params());
    let (soldier, chef) = (w.fighters[0].params, w.fighters[1].params);
    assert!(soldier.weight > chef.weight);
    assert!(soldier.run_speed < chef.run_speed);
    assert!(soldier.gravity > chef.gravity);
    assert!(soldier.max_fall > chef.max_fall);
    assert!(soldier.fast_fall > chef.fast_fall);
    for other in Character::ALL {
        assert!(soldier.weight >= other.params().weight, "heavier than {:?}", other);
        assert!(soldier.run_speed <= other.params().run_speed, "slower than {:?}", other);
    }
}

#[test]
fn soldier_moves_are_all_his_own_including_grab_pummel_and_throws() {
    let moves = Character::Soldier.moves();
    for follow_up in [MoveId::SoldierButtStrike2, MoveId::SoldierShieldBash] {
        assert!(moves.contains(&follow_up), "{follow_up:?}");
    }
    // Unlike the samurai, the soldier never borrows the chef's shared grab moves.
    for shared in [MoveId::Grab, MoveId::DashGrab, MoveId::Pummel, MoveId::FThrow, MoveId::BThrow, MoveId::UThrow, MoveId::DThrow] {
        assert!(!moves.contains(&shared), "the soldier must not reuse {shared:?}");
    }
    assert!(!moves.contains(&MoveId::Jab), "no chef moves");
    assert!(!moves.contains(&MoveId::SamuraiSlash), "no samurai moves");
}

#[test]
fn soldier_inputs_start_soldier_moves() {
    let ground = [
        (0, 0, Input::ATTACK, MoveId::SoldierButtStrike),
        (60, 0, Input::ATTACK, MoveId::SoldierBayonet),
        (0, 60, Input::ATTACK, MoveId::SoldierRifleUp),
        (0, -60, Input::ATTACK, MoveId::SoldierLegSweep),
        (0, 0, Input::SMASH, MoveId::SoldierStockSmash),
        (0, 100, Input::SMASH, MoveId::SoldierBayonetUpper),
        (0, -100, Input::SMASH, MoveId::SoldierStockSweep),
        (0, 0, Input::SPECIAL, MoveId::SoldierRifleShot),
        (100, 0, Input::SPECIAL, MoveId::SoldierGrenade),
        (0, 100, Input::SPECIAL, MoveId::SoldierBlastJump),
        (0, -100, Input::SPECIAL, MoveId::SoldierRiotShield),
        (0, 0, Input::GRAB, MoveId::SoldierGrab),
    ];
    for (x, y, buttons, expected) in ground {
        let mut w = world();
        w.step(&[input(x, y, buttons), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
    let air = [
        (0, 0, MoveId::SoldierAirSpin),
        (100, 0, MoveId::SoldierAirBayonet),
        (-100, 0, MoveId::SoldierBackElbow),
        (0, 100, MoveId::SoldierAirUp),
        (0, -100, MoveId::SoldierAirStomp),
    ];
    for (x, y, expected) in air {
        let mut w = world();
        airborne(&mut w, 0, 0, 150);
        w.step(&[input(x, y, Input::ATTACK), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
}

#[test]
fn attacking_out_of_a_run_is_a_shoulder_charge_and_a_dash_grab() {
    let mut w = world();
    run(&mut w, 15, stick(100, 0), NONE);
    w.step(&[input(100, 0, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SoldierShoulderCharge));

    let mut w = world();
    run(&mut w, 15, stick(100, 0), NONE);
    w.step(&[input(100, 0, Input::GRAB), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SoldierDashGrab));
}

#[test]
fn rifle_shot_fires_on_frame_10_and_hits_straight() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::ZERO;
    w.step(&[press(Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SoldierRifleShot));
    run(&mut w, 8, NONE, NONE);
    assert!(w.projectiles.is_empty(), "not yet fired on frame 9");
    w.step(&[NONE, NONE]);
    assert_eq!(w.projectiles.len(), 1, "fired on frame 10");
    let shot = &w.projectiles[0];
    assert_eq!((shot.x, shot.y), (Fx::int(-31), Fx::int(7)));
    assert_eq!(shot.vy, Fx::ZERO, "a straight shot, not lobbed");

    let mut hit = false;
    for _ in 0..20 {
        w.step(&[NONE, NONE]);
        hit |= w.events.iter().any(|e| matches!(e, Event::Hit { attacker: 0, defender: 1, damage: 8, projectile: true, .. }));
        if hit {
            break;
        }
    }
    assert!(hit);
    assert_eq!(w.fighters[1].percent, 8);
    assert!(w.projectiles.is_empty(), "used up by the hit");
}

#[test]
fn grenade_arcs_and_explodes_where_it_lands() {
    let mut w = world();
    // Far from P2, so the grenade lands on the floor well short of them.
    w.fighters[0].x = Fx::int(-50);
    w.fighters[1].x = Fx::int(50);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SoldierGrenade));
    run(&mut w, 12, NONE, NONE);
    assert!(w.projectiles.is_empty(), "not yet thrown on frame 13");
    w.step(&[NONE, NONE]);
    assert_eq!(w.projectiles.len(), 1, "thrown on frame 14");

    let mut exploded = None;
    let mut heights = Vec::new();
    for f in 2..80 {
        w.step(&[NONE, NONE]);
        heights.extend(w.projectiles.first().map(|p| p.y));
        for e in &w.events {
            if let Event::Explosion { owner: 0, x, y } = *e {
                exploded = Some((f, x, y));
            }
        }
    }
    // Lobbed: it rises from y = 8, then comes down to the floor and blows up there.
    let apex = (0..heights.len()).max_by_key(|&i| heights[i].raw()).unwrap();
    assert!(heights[apex] > Fx::int(8), "arcs upward: {heights:?}");
    let (_, x, y) = exploded.expect("the grenade never exploded");
    assert_eq!(y, Fx::ZERO, "explodes on the main stage");
    assert!(x > Fx::int(-53) && x < Fx::int(50), "lands on the stage short of P2, at {x:?}");
    assert!(w.projectiles.is_empty());
    assert_eq!(w.fighters[1].percent, 0, "P2 was out of the blast");
}

#[test]
fn grenade_explodes_on_contact() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-28);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    run(&mut w, 12, NONE, NONE);
    assert!(w.projectiles.is_empty());
    w.step(&[NONE, NONE]);
    // Touches P2 as soon as it is thrown, and the blast catches them.
    assert_eq!(w.fighters[1].percent, 13, "the blast hits");
    assert!(w.events.iter().any(|e| matches!(e, Event::Explosion { owner: 0, .. })), "{:?}", w.events);
    assert!(w.projectiles.is_empty());
}

#[test]
fn grenade_blast_catches_its_owner_too_if_they_stand_close() {
    // The grenade doesn't hit whoever threw it, even if the blast reaches them.
    let mut w = world();
    w.fighters[1].x = Fx::int(-44); // behind the thrower, but inside a blast there
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    run(&mut w, 13, NONE, NONE);
    for _ in 0..60 {
        w.step(&[NONE, NONE]);
    }
    assert_eq!(w.fighters[0].percent, 0, "own grenade never hurts the thrower");
}

#[test]
fn blast_jump_launches_him_up_and_ends_helpless() {
    let climb = |drift: i8| {
        let mut w = world();
        w.fighters[0].x = Fx::ZERO; // clear of the side platforms
        airborne(&mut w, 0, 0, 100);
        w.step(&[input(0, 100, Input::SPECIAL), NONE]);
        assert_eq!(mv(&w, 0), Some(MoveId::SoldierBlastJump));
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
    assert!(peak >= Fx::int(100 + 38), "peak {peak:?}");
    let (_, steered) = climb(100);
    assert!(steered > x + Fx::int(10), "steered to {steered:?}");
}

#[test]
fn blast_jump_spikes_opponents_below() {
    let mut w = world();
    airborne(&mut w, 0, 0, 150);
    airborne(&mut w, 1, 0, 140);
    w.fighters[1].percent = 50;
    w.step(&[input(0, 100, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SoldierBlastJump));
    let mut sent_down = false;
    for _ in 0..12 {
        w.step(&[NONE, NONE]);
        sent_down |= w.fighters[1].kb_y < Fx::ZERO;
    }
    assert!(sent_down, "the blast below spikes P2");
}

#[test]
fn riot_shield_counters_and_bashes_back() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Soldier], 3);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    assert_eq!(mv(&w, 1), Some(MoveId::SoldierRiotShield));
    run(&mut w, 5, NONE, NONE);
    // The chef's jab lands on its frame 2: the soldier's frame 8, inside the window.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert!(w.events.iter().any(|e| matches!(e, Event::Counter { fighter: 1, attacker: 0, .. })), "{:?}", w.events);
    assert_eq!(w.fighters[1].percent, 0);
    assert_eq!(mv(&w, 1), Some(MoveId::SoldierShieldBash));
    assert_eq!(w.fighters[1].facing, -1, "turned toward the attacker");

    run(&mut w, 30, NONE, NONE);
    assert_eq!(w.fighters[0].percent, 15, "the bash lands");
    assert_eq!(w.fighters[1].percent, 0);
}

#[test]
fn riot_shield_outside_its_window_just_gets_hit() {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef, Character::Soldier], 3);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    run(&mut w, 27, NONE, NONE);
    // Jab lands on the soldier's frame 30, after the window closed on 26.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[1].percent, 3);
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
}

/// The soldier grabs P2 (standing at x = -32).
fn grabbed() -> World {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    w.step(&[press(Input::GRAB), NONE]);
    run(&mut w, 7, NONE, NONE);
    w
}

#[test]
fn soldier_grab_pummel_and_throws_are_his_own() {
    let w = grabbed();
    assert_eq!(w.fighters[0].holding, Some(1));

    for (x, y, throw, damage) in [
        (60, 0, MoveId::SoldierThrowForward, 8),
        (-60, 0, MoveId::SoldierThrowBack, 11),
        (0, 60, MoveId::SoldierThrowUp, 7),
        (0, -60, MoveId::SoldierThrowDown, 7),
    ] {
        let mut w = grabbed();
        w.step(&[stick(x, y), NONE]);
        assert_eq!(mv(&w, 0), Some(throw));
        run(&mut w, 25, NONE, NONE);
        let (thrower, victim) = (&w.fighters[0], &w.fighters[1]);
        assert_eq!(victim.percent, damage, "{throw:?}");
        assert_eq!(thrower.holding, None, "{throw:?}");
        if throw == MoveId::SoldierThrowBack {
            assert!(victim.x < thrower.x, "thrown behind");
        }
    }

    let mut w = grabbed();
    w.step(&[press(Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SoldierPummel));
}

#[test]
fn soldier_matches_resimulate_bit_identically() {
    let play = |w: &mut World| {
        for f in 0..600u32 {
            let axis = |n: u32| ((n % 201) as i32 - 100) as i8;
            let p1 = input(axis(f * 37), axis(f * 53), (f % 7) as u8 * 3);
            let p2 = input(axis(f * 11), 0, ((f * 5) % 64) as u8);
            w.step(&[p1, p2]);
        }
    };
    let mut a = World::new(Stage::battlefield(), &[Character::Soldier, Character::Chef], 3);
    let mut b = a.clone();
    play(&mut a);
    play(&mut b);
    assert_eq!(a, b);
}
