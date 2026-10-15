use fight_sim::{Cpu, Event, Fx, Input, Stage, State, World};

fn world() -> World {
    World::new(Stage::battlefield(), 2, 3)
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
