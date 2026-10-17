use fight_sim::{Character, Cpu, Event, Fx, Input, MoveId, Stage, State, World};

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Chef; 2], 3)
}

/// Runs P1 idle against an easy CPU as P2. Returns (attacks started, hits landed).
fn vs_idle(w: &mut World, cpu: &mut Cpu, frames: usize) -> (usize, usize) {
    let (mut attacks, mut hits) = (0, 0);
    for _ in 0..frames {
        let was_attacking = matches!(w.fighters[1].state, State::Attack { .. });
        let input = cpu.think(w);
        w.step(&[Input::default(), input]);
        attacks += (!was_attacking && matches!(w.fighters[1].state, State::Attack { .. })) as usize;
        hits += w.events.iter().filter(|e| matches!(e, Event::Hit { attacker: 1, .. })).count();
    }
    (attacks, hits)
}

#[test]
fn easy_cpu_walks_over_and_lands_hits() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    let (_, hits) = vs_idle(&mut w, &mut cpu, 600);
    assert!(hits > 0, "never hit an idle opponent in 10 s");
}

#[test]
fn easy_cpu_eventually_takes_a_stock() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    vs_idle(&mut w, &mut cpu, 60 * 180);
    assert!(w.fighters[0].stocks < 3, "no KO on an idle opponent in 3 minutes");
}

#[test]
fn easy_cpu_does_not_self_destruct() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    vs_idle(&mut w, &mut cpu, 60 * 120);
    assert_eq!(w.fighters[1].stocks, 3);
}

#[test]
fn easy_cpu_recovers_from_offstage() {
    for x in [-80, 80] {
        let (mut w, mut cpu) = (world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state) = (Fx::int(x), Fx::int(-5), None, State::Air);
        vs_idle(&mut w, &mut cpu, 180);
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x}");
        assert!(w.fighters[1].grounded(), "not back on stage from x={x}");
    }
}

#[test]
fn easy_cpu_is_not_relentless() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    w.fighters[1].x = Fx::int(-30);
    // With a jab-locked opponent a perfect bot could swing every ~17 frames;
    // easy should leave plenty of gaps (at most one swing per 40 frames here).
    let (attacks, _) = vs_idle(&mut w, &mut cpu, 1200);
    assert!(attacks <= 30, "{attacks} attacks in 20 s");
}

#[test]
fn cpu_is_deterministic() {
    let play = || {
        let (mut w, mut a, mut b) = (world(), Cpu::easy(0), Cpu::easy(1));
        for _ in 0..1800 {
            let inputs = [a.think(&w), b.think(&w)];
            w.step(&inputs);
        }
        w
    };
    assert_eq!(play(), play());
}

#[test]
fn easy_cpu_mashes_out_of_grabs() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    w.fighters[1].x = Fx::int(-32);
    let grab = Input { buttons: Input::GRAB, ..Input::default() };
    let mut held = 0;
    for f in 0..200 {
        let input = cpu.think(&w);
        w.step(&[if f == 0 { grab } else { Input::default() }, input]);
        held += matches!(w.fighters[1].state, State::Held { .. }) as usize;
    }
    assert!(held > 0, "never got grabbed");
    // Sitting still it would take 90 frames.
    assert!(held < 40, "held for {held} frames");
}

#[test]
fn easy_cpu_up_specials_back_without_a_double_jump() {
    for x in [-85, 85] {
        let (mut w, mut cpu) = (world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state, f.air_jumps_left) = (Fx::int(x), Fx::int(-15), None, State::Air, 0);
        let mut used_up_special = false;
        for _ in 0..240 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            used_up_special |= matches!(w.fighters[1].state, State::Attack { mv: MoveId::UpSpecial, .. });
        }
        assert!(used_up_special, "from x={x}");
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x}");
        assert!(w.fighters[1].grounded(), "not back on stage from x={x}");
    }
}

#[test]
fn easy_cpu_grabs_and_throws_sometimes() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    let (mut grabs, mut throws) = (0, 0);
    for _ in 0..60 * 120 {
        let input = cpu.think(&w);
        w.step(&[Input::default(), input]);
        grabs += w.events.iter().filter(|e| matches!(e, Event::Grab { attacker: 1, .. })).count();
        throws += matches!(w.fighters[1].state, State::Attack { mv: MoveId::FThrow, frame: 1, .. }) as usize;
    }
    assert!(grabs > 0 && throws > 0, "{grabs} grabs, {throws} throws in 2 minutes");
}

#[test]
fn easy_cpu_shields_some_attacks() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    w.fighters[1].x = Fx::int(-30);
    let mut shielded = 0;
    for f in 0..60 * 60 {
        // P1 keeps jabbing from where it stands.
        let p1 = Input { buttons: if f % 30 == 0 { Input::ATTACK } else { 0 }, ..Input::default() };
        let input = cpu.think(&w);
        w.step(&[p1, input]);
        shielded += w.events.iter().filter(|e| matches!(e, Event::ShieldHit { defender: 1, .. })).count();
    }
    assert!(shielded > 0, "never shielded");
}

fn pug_cpu_world() -> World {
    World::new(Stage::battlefield(), &[Character::Chef, Character::Pug], 3)
}

#[test]
fn easy_cpu_lands_hits_as_the_pug() {
    let (mut w, mut cpu) = (pug_cpu_world(), Cpu::easy(1));
    let (_, hits) = vs_idle(&mut w, &mut cpu, 600);
    assert!(hits > 0, "never hit an idle opponent in 10 s");
}

#[test]
fn easy_cpu_pug_ear_copters_back_without_air_jumps() {
    for x in [-85, 85] {
        let (mut w, mut cpu) = (pug_cpu_world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state, f.air_jumps_left) = (Fx::int(x), Fx::int(-15), None, State::Air, 0);
        let mut used_ear_copter = false;
        for _ in 0..300 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            used_ear_copter |= matches!(w.fighters[1].state, State::Attack { mv: MoveId::PugEarCopter, .. });
        }
        assert!(used_ear_copter, "from x={x}");
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x}");
        assert!(w.fighters[1].grounded(), "not back on stage from x={x}");
    }
}
