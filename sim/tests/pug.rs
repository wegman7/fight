//! The pug's own moveset and tuning. P1 (fighter 0) is the pug unless a test says
//! otherwise; P2 is a mannequin standing in as the target.

use fight_sim::{Character, Event, Fx, Input, MoveId, Stage, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Pug, Character::Mannequin], 3)
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
fn each_fighter_gets_its_characters_tuning() {
    let w = world();
    assert_eq!(w.fighters[0].character, Character::Pug);
    assert_eq!(w.fighters[0].params, Character::Pug.params());
    assert_eq!(w.fighters[1].params, Character::Mannequin.params());
    let (pug, mannequin) = (w.fighters[0].params, w.fighters[1].params);
    assert!(pug.weight < mannequin.weight && pug.height < mannequin.height);
    assert!(pug.run_speed > mannequin.run_speed);
}

#[test]
fn move_lists_include_follow_ups_and_have_unique_names() {
    for character in Character::ALL {
        let moves = character.moves();
        let mut names: Vec<&str> = moves.iter().map(|m| m.data().name).collect();
        names.sort();
        names.dedup();
        assert_eq!(names.len(), moves.len(), "{character:?} has two moves with one animation name");
    }
    let pug = Character::Pug.moves();
    for follow_up in [MoveId::PugBite2, MoveId::PugNibbles, MoveId::PugPounce, MoveId::PugTackleRide] {
        assert!(pug.contains(&follow_up), "{follow_up:?}");
    }
    assert!(!pug.contains(&MoveId::Jab), "the pug only uses its own moves");
}

#[test]
fn pug_inputs_start_pug_moves() {
    let ground = [
        (0, 0, Input::ATTACK, MoveId::PugBite),
        (60, 0, Input::ATTACK, MoveId::PugPawSwipe),
        (0, 60, Input::ATTACK, MoveId::PugHeadToss),
        (0, -60, Input::ATTACK, MoveId::PugScoot),
        (0, 0, Input::SMASH, MoveId::PugRam),
        (0, 100, Input::SMASH, MoveId::PugHowl),
        (0, -100, Input::SMASH, MoveId::PugShake),
        (0, 0, Input::SPECIAL, MoveId::PugSneeze),
        (100, 0, Input::SPECIAL, MoveId::PugTackle),
        (0, 100, Input::SPECIAL, MoveId::PugEarCopter),
        (0, -100, Input::SPECIAL, MoveId::PugPlayDead),
        (0, 0, Input::GRAB, MoveId::PugBiteGrab),
    ];
    for (x, y, buttons, expected) in ground {
        let mut w = world();
        w.step(&[input(x, y, buttons), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
    let air = [(0, 0, MoveId::PugTailSpin), (100, 0, MoveId::PugAirHeadbutt), (-100, 0, MoveId::PugBuck), (0, 100, MoveId::PugSnap), (0, -100, MoveId::PugPancake)];
    for (x, y, expected) in air {
        let mut w = world();
        airborne(&mut w, 0, 0, 150);
        w.step(&[input(x, y, Input::ATTACK), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
    }
}

#[test]
fn mannequin_keeps_its_own_moves_next_to_a_pug() {
    let mut w = world();
    w.step(&[NONE, press(Input::ATTACK)]);
    assert_eq!(mv(&w, 1), Some(MoveId::Jab));
}

#[test]
fn pug_has_two_air_jumps() {
    let mut w = world();
    airborne(&mut w, 0, 0, 150);
    assert_eq!(w.fighters[0].air_jumps_left, 2);
    let mut left = Vec::new();
    for _ in 0..2 {
        w.step(&[press(Input::JUMP), NONE]);
        left.push(w.fighters[0].air_jumps_left);
        run(&mut w, 20, NONE, NONE);
    }
    assert_eq!(left, [1, 0]);
    let falling = w.fighters[0].vy;
    w.step(&[press(Input::JUMP), NONE]);
    assert!(w.fighters[0].vy <= falling, "no third air jump");
}

#[test]
fn bites_chain_into_nibbles_that_repeat_while_attack_is_mashed() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    let mut seen = Vec::new();
    let mut nibbles_started = 0;
    for f in 0..90 {
        w.step(&[press(if f % 4 == 0 { Input::ATTACK } else { 0 }), NONE]);
        if let State::Attack { mv, frame: 1, .. } = w.fighters[0].state {
            seen.push(mv);
            nibbles_started += (mv == MoveId::PugNibbles) as usize;
        }
    }
    assert_eq!(seen[..3], [MoveId::PugBite, MoveId::PugBite2, MoveId::PugNibbles]);
    assert!(nibbles_started >= 4, "only {nibbles_started} nibbles");
    assert!(w.fighters[1].percent >= 3 + 2 + 2, "{}%", w.fighters[1].percent);

    // Stop pressing and the flurry ends.
    run(&mut w, 20, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::Ground);
}

#[test]
fn scoot_slides_forward_along_the_floor() {
    let mut w = world();
    w.step(&[stick(0, -60), NONE]);
    w.step(&[input(0, -60, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::PugScoot));
    let start = w.fighters[0].x;
    run(&mut w, 20, NONE, NONE);
    assert!(w.fighters[0].x - start > Fx::int(10), "moved {:?}", w.fighters[0].x - start);
    assert!(w.fighters[0].grounded());
}

/// Starts the sneeze, then feeds `held` every frame until the cloud comes out.
fn sneeze(w: &mut World, held: Input) {
    w.step(&[press(Input::SPECIAL), NONE]);
    finish_sneeze(w, held);
}

/// Feeds `held` every frame until the sneeze reaches its firing frame (16).
fn finish_sneeze(w: &mut World, held: Input) {
    for _ in 0..120 {
        if matches!(w.fighters[0].state, State::Attack { mv: MoveId::PugSneeze, frame: 16.., .. }) {
            return;
        }
        w.step(&[held, NONE]);
    }
    panic!("no sneeze");
}

#[test]
fn tapped_sneeze_is_a_small_short_puff_on_frame_16() {
    let mut w = world();
    w.step(&[press(Input::SPECIAL), NONE]);
    run(&mut w, 14, NONE, NONE);
    assert!(w.projectiles.is_empty());
    w.step(&[NONE, NONE]);
    assert_eq!(w.projectiles.len(), 1, "fired on frame 16");
    let puff = &w.projectiles[0];
    assert_eq!((puff.charge, puff.radius(), puff.damage(), puff.frames_left), (0, Fx::int(3), 4, 28));
    assert_eq!(w.fighters[0].kb_x, Fx::ZERO, "no recoil");
    // P2 is far away (x = 40): the puff runs out first.
    run(&mut w, 28, NONE, NONE);
    assert!(w.projectiles.is_empty());
    assert_eq!(w.fighters[1].percent, 0);
}

#[test]
fn holding_special_charges_the_sneeze_into_a_big_cloud_with_recoil() {
    let mut w = world();
    sneeze(&mut w, press(Input::SPECIAL));
    let cloud = &w.projectiles[0];
    assert_eq!(cloud.charge, 60, "fires by itself at full charge");
    assert_eq!((cloud.radius(), cloud.damage(), cloud.base_kb(), cloud.frames_left), (Fx::int(6), 16, 65, 50));
    assert!(w.fighters[0].kb_x < Fx::ZERO, "knocked back by its own sneeze");
}

#[test]
fn a_half_charged_sneeze_grows_halfway() {
    let mut w = world();
    w.step(&[press(Input::SPECIAL), NONE]);
    run(&mut w, 12, press(Input::SPECIAL), NONE); // up to the charge frame (13)
    run(&mut w, 30, press(Input::SPECIAL), NONE);
    assert!(w.fighters[0].charging());
    finish_sneeze(&mut w, NONE);
    let cloud = &w.projectiles[0];
    assert_eq!(cloud.charge, 30);
    assert_eq!((cloud.damage(), cloud.base_kb()), (4 + 6, 20 + 22));
}

#[test]
fn only_special_charges_the_sneeze() {
    let mut w = world();
    sneeze(&mut w, press(Input::ATTACK));
    assert_eq!(w.projectiles[0].charge, 0);
}

#[test]
fn a_full_sneeze_launches_a_close_target() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-25);
    sneeze(&mut w, press(Input::SPECIAL));
    run(&mut w, 5, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 16);
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
}

#[test]
fn tackle_latches_on_rides_for_three_bites_then_hops_off() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-25);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::PugTackle));
    let mut caught = false;
    for _ in 0..20 {
        w.step(&[NONE, NONE]);
        caught |= w.events.contains(&Event::Grab { attacker: 0, defender: 1 });
        if caught {
            break;
        }
    }
    assert!(caught, "the leap catches a standing target");
    assert_eq!(mv(&w, 0), Some(MoveId::PugTackleRide), "straight into the ride, no throw to pick");
    assert!(matches!(w.fighters[1].state, State::Held { by: 0, .. }));

    run(&mut w, 31, stick(-100, 0), press(Input::ATTACK)); // inputs don't matter mid-ride
    assert_eq!(w.fighters[1].percent, 6, "three bites");
    assert!(matches!(w.fighters[1].state, State::Held { .. }), "can't mash out mid-ride");

    run(&mut w, 10, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 10, "bites plus the kick-off");
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
    assert_eq!(w.fighters[0].holding, None);
}

#[test]
fn tackle_whiffs_on_a_shield() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-25);
    let shield = press(Input::SHIELD);
    w.step(&[input(100, 0, Input::SPECIAL), shield]);
    let mut grabbed = false;
    for _ in 0..40 {
        w.step(&[NONE, shield]);
        grabbed |= w.events.iter().any(|e| matches!(e, Event::Grab { .. }));
    }
    assert!(!grabbed);
    assert_eq!(w.fighters[1].percent, 0);
    assert!(w.fighters[1].shielding());
    assert_eq!(w.fighters[0].holding, None);
}

#[test]
fn tackle_only_once_per_airtime() {
    let mut w = world();
    airborne(&mut w, 0, 0, 150);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::PugTackle));
    run(&mut w, 40, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::Air);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(w.fighters[0].state, State::Air, "already used this airtime");
}

#[test]
fn ear_copter_climbs_slowly_steers_and_ends_helpless() {
    let climb = |drift: i8| {
        let mut w = world();
        w.fighters[0].x = Fx::ZERO; // clear of the side platforms
        w.step(&[input(0, 100, Input::SPECIAL), NONE]);
        assert_eq!(mv(&w, 0), Some(MoveId::PugEarCopter));
        let mut peak = Fx::ZERO;
        let mut at_frame_20 = Fx::ZERO;
        for f in 2..=56 {
            w.step(&[stick(drift, 0), NONE]);
            peak = peak.max(w.fighters[0].y);
            if f == 20 {
                at_frame_20 = w.fighters[0].y;
            }
        }
        w.step(&[NONE, NONE]);
        assert_eq!(w.fighters[0].state, State::SpecialFall);
        (peak, at_frame_20, w.fighters[0].x)
    };
    let (peak, at_frame_20, x) = climb(0);
    assert!(peak >= Fx::int(44), "peak {peak:?}");
    assert!(at_frame_20 < Fx::int(18), "slow climb: {at_frame_20:?} by frame 20");
    let (_, _, steered) = climb(100);
    assert!(steered > x + Fx::int(15), "steered to {steered:?}");
}

#[test]
fn play_dead_counters_a_hit_and_pounces_back() {
    let mut w = World::new(Stage::battlefield(), &[Character::Mannequin, Character::Pug], 3);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    assert_eq!(mv(&w, 1), Some(MoveId::PugPlayDead));
    run(&mut w, 5, NONE, NONE);
    // The mannequin's jab lands on its frame 2: the pug's frame 8, inside the window.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert!(w.events.iter().any(|e| matches!(e, Event::Counter { fighter: 1, attacker: 0, .. })), "{:?}", w.events);
    assert_eq!(w.fighters[1].percent, 0, "countered hits do no damage");
    assert_eq!(mv(&w, 1), Some(MoveId::PugPounce));
    assert_eq!(w.fighters[1].facing, -1, "turned toward the attacker");
    assert!(w.fighters[1].intangible > 0);

    run(&mut w, 30, NONE, NONE);
    assert_eq!(w.fighters[0].percent, 12, "the pounce lands");
    assert_eq!(w.fighters[1].percent, 0);
}

#[test]
fn play_dead_outside_its_window_just_gets_hit() {
    let mut w = World::new(Stage::battlefield(), &[Character::Mannequin, Character::Pug], 3);
    w.fighters[1].x = Fx::int(-32);
    w.step(&[NONE, input(0, -100, Input::SPECIAL)]);
    run(&mut w, 27, NONE, NONE);
    // Jab lands on the pug's frame 30, after the window closed on 26.
    w.step(&[press(Input::ATTACK), NONE]);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[1].percent, 3);
    assert!(matches!(w.fighters[1].state, State::Hitstun { .. }));
}

#[test]
fn play_dead_counters_projectiles_too() {
    let mut w = World::new(Stage::battlefield(), &[Character::Mannequin, Character::Pug], 3);
    w.fighters[1].x = Fx::ZERO;
    w.step(&[press(Input::SPECIAL), NONE]); // energy shot leaves on frame 12
    let mut countered = false;
    for f in 1..60 {
        let pug = if f == 12 { input(0, -100, Input::SPECIAL) } else { NONE };
        w.step(&[NONE, pug]);
        countered |= w.events.iter().any(|e| matches!(e, Event::Counter { fighter: 1, .. }));
    }
    assert!(countered);
    assert_eq!(w.fighters[1].percent, 0);
    assert!(w.projectiles.is_empty(), "the shot is used up");
}

/// The pug grabs P2 (standing at x = -32).
fn grabbed() -> World {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    w.step(&[press(Input::GRAB), NONE]);
    run(&mut w, 6, NONE, NONE);
    w
}

#[test]
fn pug_bite_grab_and_throws() {
    let w = grabbed();
    assert_eq!(w.fighters[0].holding, Some(1));

    for (x, y, throw, damage) in
        [(60, 0, MoveId::PugToss, 7), (-60, 0, MoveId::PugTugSpin, 11), (0, 60, MoveId::PugFlingUp, 6), (0, -60, MoveId::PugSit, 7)]
    {
        let mut w = grabbed();
        w.step(&[stick(x, y), NONE]);
        assert_eq!(mv(&w, 0), Some(throw));
        run(&mut w, 25, NONE, NONE);
        let (thrower, victim) = (&w.fighters[0], &w.fighters[1]);
        assert_eq!(victim.percent, damage, "{throw:?}");
        assert_eq!(thrower.holding, None, "{throw:?}");
        if throw == MoveId::PugTugSpin {
            assert!(victim.x < thrower.x, "thrown behind");
        }
    }

    let mut w = grabbed();
    w.step(&[press(Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::PugNom));
}

#[test]
fn pancake_meteors() {
    let mut w = world();
    airborne(&mut w, 0, 0, 150);
    airborne(&mut w, 1, 0, 140);
    w.fighters[1].percent = 50;
    // -60: past the tilt threshold without the down tap that would fast-fall.
    w.step(&[input(0, -60, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::PugPancake));
    let mut sent_down = false;
    for _ in 0..20 {
        w.step(&[NONE, NONE]);
        sent_down |= w.fighters[1].kb_y < Fx::ZERO;
    }
    assert!(sent_down);
}

#[test]
fn mixed_matches_resimulate_bit_identically() {
    let play = |w: &mut World| {
        for f in 0..600u32 {
            let axis = |n: u32| ((n % 201) as i32 - 100) as i8;
            let p1 = input(axis(f * 37), axis(f * 53), (f % 7) as u8 * 3);
            let p2 = input(axis(f * 11), 0, ((f * 5) % 64) as u8);
            w.step(&[p1, p2]);
        }
    };
    let mut a = world();
    let mut b = world();
    play(&mut a);
    play(&mut b);
    assert_eq!(a, b);
}
