use fight_sim::fighter::knockback;
use fight_sim::{Character, DodgeKind, Event, Fx, Input, MoveId, SHIELD_MAX, Stage, StageId, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Chef; 2], 3)
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

/// Puts fighter `i` in mid-air at (x, y), facing right.
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
fn idle_fighters_stay_on_their_spawns() {
    let mut w = world();
    run(&mut w, 120, NONE, NONE);
    let (sx, sy) = w.stage.spawns[0];
    assert_eq!((w.fighters[0].x, w.fighters[0].y), (sx, sy));
    assert_eq!(w.fighters[0].state, State::Ground);
    assert_eq!(w.fighters[1].facing, -1);
}

#[test]
fn stages_are_scaled_down_so_fighters_read_bigger() {
    // The main stage was 136 units wide; at 5/6 it reads ~113 (68 -> 56 2/3), so
    // characters are ~20% larger relative to it.
    let stage = Stage::battlefield();
    assert_eq!(stage.platforms[0].right.floor_to_int(), 56);
    assert_eq!(stage.platforms[0].left.floor_to_int(), -57);
}

#[test]
fn every_stage_spawns_four_fighters_on_the_floor() {
    for id in StageId::ALL {
        let mut w = World::new(id.stage(), &[Character::Chef, Character::Pug, Character::Chef, Character::Pug], 3);
        w.step(&[NONE; 4]);
        for (i, f) in w.fighters.iter().enumerate() {
            assert_eq!((f.state, f.y), (State::Ground, Fx::ZERO), "{} P{}", id.name(), i + 1);
            assert_eq!(f.facing, if f.x < Fx::ZERO { 1 } else { -1 }, "{} P{} should face the middle", id.name(), i + 1);
        }
    }
}

#[test]
fn full_hop_goes_higher_than_short_hop_and_both_land() {
    let peak = |hold_frames: usize| {
        let mut w = world();
        let mut peak = Fx::ZERO;
        for f in 0..120 {
            let input = if f < hold_frames { press(Input::JUMP) } else { NONE };
            w.step(&[input, NONE]);
            peak = peak.max(w.fighters[0].y);
        }
        assert_eq!(w.fighters[0].state, State::Ground, "should have landed");
        peak
    };
    let short = peak(1);
    let full = peak(10);
    assert!(full > short + Fx::int(10), "full {full:?} vs short {short:?}");
}

#[test]
fn jab_connects_on_frame_2_and_only_once() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);

    w.step(&[press(Input::ATTACK), NONE]);
    assert!(matches!(w.fighters[0].state, State::Attack { mv: MoveId::Jab, frame: 1, .. }));
    assert_eq!(w.fighters[1].percent, 0);

    w.step(&[press(Input::ATTACK), NONE]);
    assert_eq!(w.fighters[1].percent, 3);
    assert!(matches!(w.events[0], Event::Hit { attacker: 0, defender: 1, damage: 3, .. }));
    assert!(w.fighters[0].hitlag > 0 && w.fighters[1].hitlag > 0);

    run(&mut w, 30, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 3, "one swing hits each target once");
}

#[test]
fn knockback_matches_reference_formula() {
    let reference = |p: f64, d: f64, w: f64, b: f64, g: f64| ((((p / 10.0 + p * d / 20.0) * 200.0 / (w + 100.0) * 1.4) + 18.0) * g / 100.0) + b;
    for &(p, d, w, b, g) in &[(0, 3, 100, 8, 60), (59, 9, 100, 20, 100), (150, 12, 85, 30, 110), (300, 20, 120, 40, 90)] {
        let got = knockback(p, d, w, b, g).to_f32() as f64;
        let want = reference(p as f64, d as f64, w as f64, b as f64, g as f64);
        assert!((got - want).abs() < 0.01, "p={p} d={d}: got {got}, want {want}");
    }
}

#[test]
fn ftilt_kos_at_high_percent_but_not_at_zero() {
    let stocks_after_ftilt = |percent| {
        let mut w = world();
        let (p1, p2) = (0, 1);
        w.fighters[p1].x = Fx::int(16);
        w.fighters[p2].x = Fx::int(24);
        w.fighters[p2].percent = percent;
        // Tilt strength: a full flick from neutral with attack would be a smash attack.
        w.step(&[Input { stick_x: 60, ..press(Input::ATTACK) }, NONE]);
        assert!(matches!(w.fighters[p1].state, State::Attack { mv: MoveId::FTilt, .. }));
        run(&mut w, 400, NONE, NONE);
        w.fighters[p2].stocks
    };
    assert_eq!(stocks_after_ftilt(150), 2);
    assert_eq!(stocks_after_ftilt(0), 3);
}

#[test]
fn walking_off_stage_falls_into_blast_zone_then_respawns() {
    let mut w = world();
    let mut ko_frame = None;
    for _ in 0..400 {
        w.step(&[stick(100, 0), NONE]);
        if w.events.contains(&Event::Ko { fighter: 0 }) {
            ko_frame = Some(w.frame);
            break;
        }
    }
    assert!(ko_frame.is_some(), "never fell off");
    assert_eq!(w.fighters[0].stocks, 2);
    assert_eq!(w.fighters[0].percent, 0);

    run(&mut w, 60, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::Air);
    assert!(!w.fighters[0].hittable(), "respawn invincibility");
}

#[test]
fn tapping_down_drops_through_soft_platforms() {
    let mut w = world();
    let plat = w.stage.platforms[1].clone();
    let f = &mut w.fighters[0];
    (f.x, f.y, f.grounded_on) = (plat.left + Fx::int(8), plat.y, Some(1));

    w.step(&[stick(0, -100), NONE]);
    run(&mut w, 5, NONE, NONE);
    assert!(w.fighters[0].y < plat.y);
    run(&mut w, 120, NONE, NONE);
    assert_eq!(w.fighters[0].grounded_on, Some(0), "lands on the main stage");
}

#[test]
fn landing_during_an_aerial_uses_its_landing_lag() {
    let mut w = world();
    w.step(&[press(Input::JUMP), NONE]);
    run(&mut w, 4, NONE, NONE);
    w.step(&[press(Input::ATTACK), NONE]);
    let mut saw = false;
    for _ in 0..60 {
        w.step(&[NONE, NONE]);
        saw |= w.fighters[0].state == State::Landing { frames_left: 15 };
    }
    assert!(saw, "nair should end in 15 frames of landing lag");
}

#[test]
fn rollback_resimulation_is_bit_identical() {
    // A tiny LCG keeps the "random" inputs reproducible.
    let mut seed = 12345u32;
    let mut random_input = || {
        let mut next = || {
            seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12345);
            seed >> 16
        };
        Input {
            stick_x: ((next() % 201) as i32 - 100) as i8,
            stick_y: ((next() % 201) as i32 - 100) as i8,
            // Every button, including shield, grab and smash.
            buttons: (next() % 64) as u8,
        }
    };
    let inputs: Vec<[Input; 2]> = (0..600).map(|_| [random_input(), random_input()]).collect();

    let mut w = world();
    for i in &inputs[..300] {
        w.step(i);
    }
    let snapshot = w.clone();
    for i in &inputs[300..] {
        w.step(i);
    }

    let mut replay = snapshot;
    for i in &inputs[300..] {
        replay.step(i);
    }
    assert_eq!(w, replay);
}

// --- Ground attacks ---------------------------------------------------------

#[test]
fn flicking_the_stick_with_attack_is_a_smash_holding_it_first_is_a_tilt() {
    let mut w = world();
    w.step(&[input(100, 0, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::FSmash), "flick + attack on the same frame");

    let mut w = world();
    run(&mut w, 4, stick(100, 0), NONE);
    w.step(&[input(100, 0, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::FTilt), "stick held 4 frames before attack");

    let mut w = world();
    w.step(&[input(0, 100, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::USmash));
}

#[test]
fn smash_button_picks_the_smash_attack_by_stick_direction() {
    for (x, y, expected) in [(0, 0, MoveId::FSmash), (40, 0, MoveId::FSmash), (0, 60, MoveId::USmash), (0, -60, MoveId::DSmash)] {
        let mut w = world();
        w.step(&[input(x, y, Input::SMASH), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
        assert_eq!(w.fighters[0].facing, 1, "neutral smash goes forward");
    }
}

#[test]
fn crouching_then_attacking_is_a_down_tilt() {
    let mut w = world();
    run(&mut w, 5, stick(0, -100), NONE);
    assert_eq!(w.fighters[0].state, State::Crouch);
    w.step(&[input(0, -100, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::DTilt));
}

#[test]
fn attacking_out_of_a_run_is_a_dash_attack() {
    let mut w = world();
    run(&mut w, 15, stick(100, 0), NONE);
    assert_eq!(w.fighters[0].anim(), "run");
    w.step(&[input(100, 0, Input::ATTACK), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::DashAttack));
    let start = w.fighters[0].x;
    run(&mut w, 20, stick(100, 0), NONE);
    assert!(w.fighters[0].x > start + Fx::int(8), "slides on its run momentum");
}

#[test]
fn smash_attacks_charge_while_held_for_up_to_1_4x_damage() {
    let damage_after = |hold_frames: usize| {
        let mut w = world();
        w.fighters[1].x = Fx::int(-30);
        w.step(&[input(100, 0, Input::ATTACK), NONE]);
        for f in 0..hold_frames {
            w.step(&[input(0, 0, Input::ATTACK), NONE]);
            if f == 30 {
                assert!(w.fighters[0].charging());
                assert!(matches!(w.fighters[0].state, State::Attack { mv: MoveId::FSmash, frame: 10, .. }), "frozen on the charge frame");
            }
        }
        run(&mut w, 60, NONE, NONE);
        w.fighters[1].percent
    };
    assert_eq!(damage_after(0), 15);
    assert_eq!(damage_after(100), 21, "full 60-frame charge");
}

#[test]
fn pressing_attack_during_jab_chains_jab2_then_jab3() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    let mut seen = Vec::new();
    for f in 0..80 {
        let attack = if [0, 8, 16].contains(&f) { Input::ATTACK } else { 0 };
        w.step(&[press(attack), NONE]);
        if let Some(m) = mv(&w, 0)
            && seen.last() != Some(&m)
        {
            seen.push(m);
        }
    }
    assert_eq!(seen, [MoveId::Jab, MoveId::Jab2, MoveId::Jab3]);
    assert_eq!(w.fighters[1].percent, 3 + 2 + 5);
}

// --- Aerials ----------------------------------------------------------------

#[test]
fn aerials_follow_the_stick_relative_to_facing() {
    for (x, y, expected) in
        [(0, 0, MoveId::Nair), (100, 0, MoveId::Fair), (-100, 0, MoveId::Bair), (0, 100, MoveId::Uair), (0, -100, MoveId::Dair)]
    {
        let mut w = world();
        airborne(&mut w, 0, -40, 100);
        w.step(&[input(x, y, Input::ATTACK), NONE]);
        assert_eq!(mv(&w, 0), Some(expected), "stick ({x}, {y})");
        assert_eq!(w.fighters[0].facing, 1, "aerials never turn the fighter");
    }
}

#[test]
fn bair_launches_backward() {
    let mut w = world();
    airborne(&mut w, 0, -40, 100);
    airborne(&mut w, 1, -47, 100);
    w.step(&[input(-100, 0, Input::ATTACK), NONE]);
    run(&mut w, 10, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 12);
    assert!(w.fighters[1].kb_x < Fx::ZERO);
}

#[test]
fn each_aerial_has_its_own_landing_lag() {
    let mut w = world();
    airborne(&mut w, 0, -40, 8);
    w.step(&[input(0, -100, Input::ATTACK), NONE]);
    let mut saw = false;
    for _ in 0..60 {
        w.step(&[NONE, NONE]);
        saw |= w.fighters[0].state == State::Landing { frames_left: 20 };
    }
    assert!(saw, "dair lands with 20 frames of lag");
}

// --- Specials ---------------------------------------------------------------

#[test]
fn pie_throw_lobs_a_pie_that_arcs_into_its_target() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::ZERO;
    w.step(&[press(Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::PieThrow));
    run(&mut w, 10, NONE, NONE);
    assert!(w.projectiles.is_empty());
    w.step(&[NONE, NONE]);
    assert_eq!(w.projectiles.len(), 1, "thrown on frame 12");
    let pie = &w.projectiles[0];
    assert_eq!((pie.x, pie.y), (Fx::int(-32), Fx::int(7)));

    let mut hit = false;
    for _ in 0..40 {
        w.step(&[NONE, NONE]);
        hit |= w.events.iter().any(|e| matches!(e, Event::Hit { attacker: 0, defender: 1, damage: 7, projectile: true, .. }));
    }
    assert!(hit);
    assert_eq!(w.fighters[1].percent, 7);
    assert!(w.projectiles.is_empty(), "used up by the hit");
}

#[test]
fn a_pie_that_misses_lands_on_the_floor_about_half_a_stage_away() {
    let mut w = world();
    w.fighters[0].x = Fx::int(-40);
    w.fighters[1].x = Fx::int(-50); // out of the pie's rightward path
    w.step(&[press(Input::SPECIAL), NONE]);
    let mut landed = None;
    let mut heights = Vec::new();
    for f in 2..80 {
        w.step(&[NONE, NONE]);
        heights.extend(w.projectiles.first().map(|p| p.y));
        for e in &w.events {
            if let Event::ProjectileLanded { owner: 0, x, y } = *e {
                landed = Some((f, x, y));
            }
        }
    }
    // Thrown at y = 7, it rises for 14 frames (vy 1/2, gravity 7/200 a frame) to just
    // over 10, then comes down.
    let apex = (0..heights.len()).max_by_key(|&i| heights[i].raw()).unwrap();
    assert!((13..=14).contains(&apex), "{apex}: {heights:?}");
    assert!(heights[apex] > Fx::int(10) && heights[apex] < Fx::int(11), "{heights:?}");
    let (frame, x, y) = landed.expect("the pie never landed");
    assert!(w.projectiles.is_empty());
    assert_eq!(y, Fx::ZERO, "on the main stage");
    // Thrown at x = -32 on frame 12, then 2 units a frame for the 39 frames of its arc;
    // P2 waits behind the throw, and the pie lands just past half a stage.
    assert_eq!(frame, 51, "{heights:?}");
    assert_eq!(x, Fx::int(46));
    assert_eq!(w.fighters[1].percent, 0);
}


#[test]
fn side_special_lunges_forward_and_only_once_per_airtime() {
    let mut w = world();
    airborne(&mut w, 0, -40, 150);
    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::SideSpecial));
    run(&mut w, 7, NONE, NONE);
    assert_eq!(w.fighters[0].y, Fx::int(150), "hangs in the air before lunging");
    run(&mut w, 33, NONE, NONE);
    assert!(w.fighters[0].x > Fx::int(-20));
    assert_eq!(w.fighters[0].state, State::Air);

    w.step(&[input(100, 0, Input::SPECIAL), NONE]);
    assert_eq!(w.fighters[0].state, State::Air, "already used this airtime");
}

#[test]
fn up_special_rises_then_leaves_you_helpless_until_landing() {
    let mut w = world();
    w.fighters[0].x = Fx::ZERO; // clear of the side platforms
    w.step(&[input(0, 100, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::UpSpecial));
    let mut peak = Fx::ZERO;
    for _ in 0..39 {
        w.step(&[NONE, NONE]);
        peak = peak.max(w.fighters[0].y);
    }
    assert!(peak > Fx::int(32), "peak {peak:?}");
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[0].state, State::SpecialFall);

    w.step(&[press(Input::JUMP | Input::ATTACK), NONE]);
    assert_eq!(w.fighters[0].state, State::SpecialFall, "no jumps or attacks while helpless");
    let mut lag = None;
    for _ in 0..120 {
        w.step(&[NONE, NONE]);
        if let State::Landing { frames_left } = w.fighters[0].state {
            lag.get_or_insert(frames_left);
        }
    }
    assert_eq!(lag, Some(20));
}

#[test]
fn down_special_plunges_and_makes_a_shockwave_on_landing() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-34);
    w.step(&[input(0, -100, Input::SPECIAL), NONE]);
    assert_eq!(mv(&w, 0), Some(MoveId::DownSpecial));
    let mut moves = Vec::new();
    for _ in 0..40 {
        w.step(&[NONE, NONE]);
        moves.extend(mv(&w, 0));
    }
    assert!(moves.contains(&MoveId::DownSpecialLanding));
    assert_eq!(w.fighters[1].percent, 10 + 8, "plunge, then shockwave");
}

// --- Shield and dodges ------------------------------------------------------

#[test]
fn shield_blocks_damage_but_takes_shield_damage_and_shieldstun() {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    let shield = press(Input::SHIELD);
    w.step(&[input(60, 0, Input::ATTACK), shield]);
    assert_eq!(w.fighters[1].state, State::Shield);
    let mut stun = None;
    for _ in 0..10 {
        w.step(&[NONE, shield]);
        if w.events.iter().any(|e| matches!(e, Event::ShieldHit { defender: 1, damage: 9, .. })) {
            stun = Some(w.fighters[1].state);
        }
    }
    assert_eq!(stun, Some(State::ShieldStun { frames_left: 7 }));
    assert_eq!(w.fighters[1].percent, 0);
    assert!(w.fighters[1].shield < SHIELD_MAX - Fx::int(9));
}

#[test]
fn holding_shield_too_long_breaks_it_then_it_refills() {
    let mut w = world();
    let mut broke_at = None;
    for f in 0..400 {
        w.step(&[press(Input::SHIELD), NONE]);
        if broke_at.is_none() && matches!(w.fighters[0].state, State::ShieldBreak { .. }) {
            broke_at = Some(f);
        }
    }
    // Frame 1 raises it, then 50 HP drains at (just under, in Q16.16) 0.15 per frame.
    assert_eq!(broke_at, Some(334));
    run(&mut w, 240, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::Ground, "dizzy wears off");
    let low = w.fighters[0].shield;
    run(&mut w, 60, NONE, NONE);
    assert!(w.fighters[0].shield > low);
}

#[test]
fn shield_options_jump_grab_and_up_smash() {
    for (buttons, y, expected) in [(Input::JUMP, 0, None), (Input::ATTACK, 0, Some(MoveId::Grab)), (Input::SMASH, 100, Some(MoveId::USmash))] {
        let mut w = world();
        w.step(&[press(Input::SHIELD), NONE]);
        w.step(&[input(0, y, Input::SHIELD | buttons), NONE]);
        match expected {
            Some(m) => assert_eq!(mv(&w, 0), Some(m)),
            None => assert_eq!(w.fighters[0].state, State::JumpSquat { frame: 0 }),
        }
    }
}

#[test]
fn rolls_move_and_are_invincible_in_the_middle() {
    let mut w = world();
    w.step(&[press(Input::SHIELD), NONE]);
    w.step(&[input(100, 0, Input::SHIELD), NONE]);
    assert_eq!(w.fighters[0].state, State::Dodge { kind: DodgeKind::RollForward, frame: 1 });
    w.step(&[NONE, NONE]);
    assert!(w.fighters[0].hittable(), "roll frame 2");
    run(&mut w, 3, NONE, NONE);
    assert!(!w.fighters[0].hittable(), "roll frame 5");
    run(&mut w, 30, NONE, NONE);
    assert_eq!(w.fighters[0].state, State::Ground);
    assert!(w.fighters[0].x > Fx::int(-15), "x = {:?}", w.fighters[0].x);
    assert_eq!(w.fighters[0].facing, -1, "forward roll ends facing back");
}

#[test]
fn spot_dodge_makes_a_jab_whiff() {
    let percent_after_jab = |dodge: bool| {
        let mut w = world();
        w.fighters[1].x = Fx::int(-32);
        let p1 = if dodge { input(0, -100, Input::SHIELD) } else { NONE };
        w.step(&[p1, NONE]);
        w.step(&[NONE, NONE]);
        w.step(&[NONE, press(Input::ATTACK)]);
        run(&mut w, 20, NONE, NONE);
        w.fighters[0].percent
    };
    assert_eq!(percent_after_jab(false), 3);
    assert_eq!(percent_after_jab(true), 0);
}

#[test]
fn directional_air_dodge_travels_without_gravity_once_per_airtime() {
    let mut w = world();
    airborne(&mut w, 0, -40, 100);
    w.step(&[input(100, 0, Input::SHIELD), NONE]);
    assert!(matches!(w.fighters[0].state, State::Dodge { kind: DodgeKind::AirDirectional, .. }));
    run(&mut w, 9, NONE, NONE);
    assert!(!w.fighters[0].hittable(), "invincible on frame 10");
    run(&mut w, 10, NONE, NONE);
    assert_eq!(w.fighters[0].y, Fx::int(100), "no gravity for the first 20 frames");
    assert!(w.fighters[0].x > Fx::int(-15), "x = {:?}", w.fighters[0].x);
    run(&mut w, 20, NONE, NONE);
    w.step(&[input(100, 0, Input::SHIELD), NONE]);
    assert_eq!(w.fighters[0].state, State::Air, "one air dodge per airtime");
}

// --- Grabs ------------------------------------------------------------------

/// P1 grabs P2 (standing at x = -32, optionally shielding).
fn grabbed(shielding: bool) -> World {
    let mut w = world();
    w.fighters[1].x = Fx::int(-32);
    let p2 = if shielding { press(Input::SHIELD) } else { NONE };
    w.step(&[press(Input::GRAB), p2]);
    for _ in 0..6 {
        w.step(&[NONE, p2]);
    }
    w
}

#[test]
fn grab_comes_out_on_frame_7_and_beats_shield() {
    let w = grabbed(true);
    assert_eq!(w.fighters[0].state, State::Holding { frame: 0 });
    assert_eq!(w.fighters[0].holding, Some(1));
    assert!(matches!(w.fighters[1].state, State::Held { by: 0, .. }));
    assert!(w.events.contains(&Event::Grab { attacker: 0, defender: 1 }));
}

#[test]
fn whiffed_grab_has_endlag() {
    let mut w = world();
    w.step(&[press(Input::GRAB), NONE]);
    run(&mut w, 29, NONE, NONE);
    assert!(matches!(w.fighters[0].state, State::Attack { mv: MoveId::Grab, frame: 30, .. }));
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[0].state, State::Ground);
}

#[test]
fn pummel_damages_without_letting_go() {
    let mut w = grabbed(false);
    w.step(&[press(Input::ATTACK), NONE]);
    run(&mut w, 20, NONE, NONE);
    assert_eq!(w.fighters[1].percent, 2);
    assert!(matches!(w.fighters[1].state, State::Held { .. }));
    assert_eq!(w.fighters[0].state, State::Holding { frame: 4 }, "back to holding after the pummel");
}

#[test]
fn throws_launch_in_their_direction() {
    for (x, y, throw, damage) in [(60, 0, MoveId::FThrow, 8), (-60, 0, MoveId::BThrow, 10), (0, 60, MoveId::UThrow, 7), (0, -60, MoveId::DThrow, 6)] {
        let mut w = grabbed(false);
        w.step(&[stick(x, y), NONE]);
        assert_eq!(mv(&w, 0), Some(throw));
        run(&mut w, 20, NONE, NONE);
        let (thrower, victim) = (&w.fighters[0], &w.fighters[1]);
        assert_eq!(victim.percent, damage, "{throw:?}");
        assert!(matches!(victim.state, State::Hitstun { .. }), "{throw:?}");
        assert_eq!(thrower.holding, None);
        match throw {
            MoveId::BThrow => assert!(victim.x < thrower.x && victim.kb_x < Fx::ZERO, "thrown behind"),
            MoveId::UThrow => assert!(victim.y > Fx::int(10)),
            _ => assert!(victim.x > thrower.x),
        }
    }
}

#[test]
fn mashing_breaks_out_of_a_grab_sooner() {
    let frames_held = |mash: bool| {
        let mut w = grabbed(false);
        let mut frames = 0;
        while matches!(w.fighters[1].state, State::Held { .. }) {
            let p2 = if mash && frames % 2 == 0 { press(Input::ATTACK) } else { NONE };
            w.step(&[NONE, p2]);
            frames += 1;
        }
        assert_eq!(w.fighters[0].holding, None);
        frames
    };
    assert_eq!(frames_held(false), 90);
    assert!(frames_held(true) < 35, "{}", frames_held(true));
}

#[test]
fn projectiles_hit_shields() {
    let mut w = world();
    w.fighters[1].x = Fx::ZERO;
    let shield = press(Input::SHIELD);
    w.step(&[press(Input::SPECIAL), shield]);
    let mut blocked = false;
    for _ in 0..50 {
        w.step(&[NONE, shield]);
        blocked |= w.events.iter().any(|e| matches!(e, Event::ShieldHit { attacker: 0, defender: 1, damage: 7, projectile: true, .. }));
    }
    assert!(blocked);
    assert_eq!(w.fighters[1].percent, 0);
    assert!(w.projectiles.is_empty());
}

// --- Ledge hang and getups ---------------------------------------------------

/// Puts fighter `i` just outside the main stage's right edge, falling into a grab.
fn falling_off_right_edge(w: &mut World, i: usize) {
    let right = w.stage.platforms[0].right;
    let h = w.fighters[i].params.height;
    let f = &mut w.fighters[i];
    (f.x, f.y, f.grounded_on, f.state, f.vx, f.vy) = (right + Fx::int(2), -h, None, State::Air, Fx::ZERO, -Fx::ONE);
}

/// Steps once and asserts `i` grabbed the main stage's right edge.
fn grab_right_edge(w: &mut World, i: usize) {
    falling_off_right_edge(w, i);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[i].state, State::LedgeHang, "fighter {i} should hang from the ledge");
}

/// Stick pushed toward the stage (`side` = the direction into it).
fn toward_stage(side: i32) -> Input {
    stick((side * 100) as i8, 0)
}

#[test]
fn falling_past_an_edge_grabs_the_ledge() {
    let mut w = world();
    let right = w.stage.platforms[0].right;
    let h = w.fighters[0].params.height;
    grab_right_edge(&mut w, 0);
    assert_eq!(w.fighters[0].ledge_on, Some(0));
    assert_eq!(w.fighters[0].ledge_side, -1, "the right edge: the stage is to the left");
    assert_eq!(w.fighters[0].facing, -1, "faces the stage");
    assert_eq!(w.fighters[0].y + h, Fx::ZERO, "hands at the ledge");
    assert!(w.fighters[0].x > right, "hangs just off the edge");
}

#[test]
fn only_solid_platform_edges_are_grabbable() {
    let mut w = world();
    let (soft_right, soft_y) = (w.stage.platforms[2].right, w.stage.platforms[2].y);
    let (solid_right, solid_y) = (w.stage.platforms[0].right, w.stage.platforms[0].y);
    let h = w.fighters[0].params.height;

    // Falling just outside a soft platform's edge: it must NOT grab.
    let f = &mut w.fighters[0];
    (f.x, f.y, f.grounded_on, f.state, f.vx, f.vy) = (soft_right + Fx::int(2), soft_y - h, None, State::Air, Fx::ZERO, -Fx::ONE);
    w.step(&[NONE, NONE]);
    assert_ne!(w.fighters[0].state, State::LedgeHang, "a soft platform edge must not be grabbable");
    assert_eq!(w.fighters[0].ledge_on, None);

    // Falling just outside the solid main stage's edge: it must grab.
    let f = &mut w.fighters[0];
    (f.x, f.y, f.grounded_on, f.state, f.vx, f.vy) = (solid_right + Fx::int(2), solid_y - h, None, State::Air, Fx::ZERO, -Fx::ONE);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[0].state, State::LedgeHang, "the solid main stage edge is grabbable");
    assert_eq!(w.fighters[0].ledge_on, Some(0));
}

#[test]
fn the_left_edge_grabs_too() {
    let mut w = world();
    let left = w.stage.platforms[0].left;
    let h = w.fighters[0].params.height;
    let f = &mut w.fighters[0];
    (f.x, f.y, f.grounded_on, f.state, f.vx, f.vy) = (left - Fx::int(2), -h, None, State::Air, Fx::ZERO, -Fx::ONE);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[0].state, State::LedgeHang);
    assert_eq!(w.fighters[0].ledge_side, 1, "the left edge: the stage is to the right");
    assert_eq!(w.fighters[0].facing, 1);
}

#[test]
fn ledge_grab_restores_the_double_jump() {
    let mut w = world();
    w.fighters[0].air_jumps_left = 0;
    grab_right_edge(&mut w, 0);
    assert_eq!(w.fighters[0].air_jumps_left, w.fighters[0].params.air_jumps);
}

#[test]
fn ledge_grab_grants_brief_invincibility() {
    let mut w = world();
    grab_right_edge(&mut w, 0);
    assert!(w.fighters[0].intangible > 0, "invincible just after grabbing");
    assert!(!w.fighters[0].hittable());
}

#[test]
fn ledge_climb_gets_back_on_stage() {
    let mut w = world();
    grab_right_edge(&mut w, 0);
    let side = w.fighters[0].ledge_side;
    for _ in 0..40 {
        w.step(&[toward_stage(side), NONE]);
    }
    assert_eq!(w.fighters[0].state, State::Ground);
    assert_eq!(w.fighters[0].grounded_on, Some(0));
    assert_eq!(w.fighters[0].y, Fx::ZERO);
    assert_eq!(w.fighters[0].ledge_on, None);
}

#[test]
fn ledge_jump_leaves_the_ledge_airborne() {
    let mut w = world();
    grab_right_edge(&mut w, 0);
    w.step(&[press(Input::JUMP), NONE]);
    assert_eq!(w.fighters[0].state, State::Air);
    assert_eq!(w.fighters[0].ledge_on, None);
    assert!(w.fighters[0].vy > Fx::ZERO, "launched upward");
}

#[test]
fn ledge_roll_gets_back_on_stage() {
    let mut w = world();
    grab_right_edge(&mut w, 0);
    w.step(&[press(Input::SHIELD), NONE]);
    for _ in 0..40 {
        w.step(&[NONE, NONE]);
    }
    assert_eq!(w.fighters[0].state, State::Ground);
    assert_eq!(w.fighters[0].grounded_on, Some(0));
}

#[test]
fn ledge_drop_falls_off() {
    let mut w = world();
    grab_right_edge(&mut w, 0);
    w.step(&[stick(0, -100), NONE]);
    assert_eq!(w.fighters[0].state, State::Air);
    assert_eq!(w.fighters[0].ledge_on, None);
}

#[test]
fn ledge_attack_swings_and_can_hit() {
    let mut w = world();
    let right = w.stage.platforms[0].right;
    w.fighters[1].x = right - Fx::int(3); // standing just inside the ledge
    w.fighters[1].facing = -1;
    grab_right_edge(&mut w, 0);
    w.step(&[press(Input::ATTACK), NONE]);
    let mut hit = false;
    for _ in 0..40 {
        w.step(&[NONE, NONE]);
        hit |= w.events.iter().any(|e| matches!(e, Event::Hit { attacker: 0, defender: 1, .. }));
    }
    assert!(hit, "the getup attack reaches the defender on the ledge");
    assert!(w.fighters[1].percent > 0);
}

#[test]
fn grabbing_an_occupied_ledge_steals_it() {
    let mut w = world();
    grab_right_edge(&mut w, 0);
    // P2 falls into the same edge and takes it over.
    falling_off_right_edge(&mut w, 1);
    w.step(&[NONE, NONE]);
    assert_eq!(w.fighters[1].state, State::LedgeHang, "the new grabber holds the ledge");
    assert_eq!(w.fighters[1].ledge_on, Some(0));
    assert_eq!(w.fighters[0].state, State::Air, "the previous holder is knocked off");
    assert_eq!(w.fighters[0].ledge_on, None);
}

#[test]
fn ledge_play_resimulates_bit_identically() {
    // Both fighters grab opposite ledges, then take every getup option in turn.
    let script = |f: usize| {
        let side = if f % 240 < 120 { 1 } else { -1 };
        let p1 = match f % 60 {
            0..=2 => toward_stage(side),
            3 => press(Input::JUMP),
            _ => NONE,
        };
        let p2 = match f % 60 {
            0..=2 => toward_stage(-side),
            3 => press(Input::SHIELD),
            _ => NONE,
        };
        [p1, p2]
    };
    let inputs: Vec<[Input; 2]> = (0..400).map(script).collect();

    let mut w = world();
    for i in &inputs[..200] {
        w.step(i);
    }
    let snapshot = w.clone();
    for i in &inputs[200..] {
        w.step(i);
    }
    let mut replay = snapshot;
    for i in &inputs[200..] {
        replay.step(i);
    }
    assert_eq!(w, replay);
}
