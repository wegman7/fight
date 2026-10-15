use fight_sim::fighter::knockback;
use fight_sim::{Event, Fx, Input, MoveId, Stage, State, World};

const NONE: Input = Input { stick_x: 0, stick_y: 0, buttons: 0 };

fn world() -> World {
    World::new(Stage::battlefield(), 2, 3)
}

fn press(buttons: u8) -> Input {
    Input { buttons, ..NONE }
}

fn stick(x: i8, y: i8) -> Input {
    Input { stick_x: x, stick_y: y, buttons: 0 }
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
    assert_eq!((w.fighters[0].x, w.fighters[0].y), (Fx::int(-40), Fx::ZERO));
    assert_eq!(w.fighters[0].state, State::Ground);
    assert_eq!(w.fighters[1].facing, -1);
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
        w.fighters[p1].x = Fx::int(40);
        w.fighters[p2].x = Fx::int(48);
        w.fighters[p2].percent = percent;
        w.step(&[Input { stick_x: 100, ..press(Input::ATTACK) }, NONE]);
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
    let f = &mut w.fighters[0];
    (f.x, f.y, f.grounded_on) = (Fx::int(-40), Fx::int(27), Some(1));

    w.step(&[stick(0, -100), NONE]);
    run(&mut w, 5, NONE, NONE);
    assert!(w.fighters[0].y < Fx::int(27));
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
            buttons: (next() % 4) as u8,
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
