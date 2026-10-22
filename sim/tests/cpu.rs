use fight_sim::{Character, Cpu, CpuLevel, DodgeKind, Event, Fighter, Fx, Input, MoveId, Stage, StageId, State, World};

fn world() -> World {
    World::new(Stage::battlefield(), &[Character::Chef; 2], 3)
}

/// Runs P1 idle against an easy CPU as P2. Returns (attacks started, hits landed).
fn vs_idle(w: &mut World, cpu: &mut Cpu, frames: usize) -> (usize, usize) {
    let (mut attacks, mut hits) = (0, 0);
    for _ in 0..frames {
        let was_attacking = matches!(w.fighters[1].state, State::Attack { .. });
        let input = cpu.think(w);
        w.step(&[idle(w), input]);
        attacks += (!was_attacking && matches!(w.fighters[1].state, State::Attack { .. })) as usize;
        hits += w.events.iter().filter(|e| matches!(e, Event::Hit { attacker: 1, .. })).count();
    }
    (attacks, hits)
}

/// Input for the non-attacking dummy: climbs back up if it ends up hanging on a ledge
/// (so it can't stall there forever), otherwise stands still.
fn idle(w: &World) -> Input {
    if matches!(w.fighters[0].state, State::LedgeHang) {
        Input { stick_y: 100, ..Input::default() }
    } else {
        Input::default()
    }
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
    // ~12 units past each main-stage ledge (the same relative depth as before the
    // stage was scaled down), so the test tracks the stage instead of hardcoding.
    let stage = Stage::battlefield();
    let main = &stage.platforms[0];
    for x in [main.left - Fx::int(12), main.right + Fx::int(12)] {
        let (mut w, mut cpu) = (world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state) = (x, Fx::int(-5), None, State::Air);
        vs_idle(&mut w, &mut cpu, 180);
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x:?}");
        assert!(w.fighters[1].grounded(), "not back on stage from x={x:?}");
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
fn cpu_seed_changes_the_game_and_replays_it() {
    let play = |seed| {
        let mut w = world();
        let (mut a, mut b) = (Cpu::with_level(0, 9).with_seed(seed), Cpu::with_level(1, 9).with_seed(seed));
        for _ in 0..1800 {
            let inputs = [a.think(&w), b.think(&w)];
            w.step(&inputs);
        }
        w
    };
    assert_eq!(play(7), play(7), "same seed, same match");
    assert_ne!(play(7), play(8), "another seed plays another match");
}

#[test]
fn easy_cpu_mashes_out_of_grabs() {
    let (mut w, mut cpu) = (world(), Cpu::easy(1));
    // Just in front of P1 (facing right from its spawn), inside its grab range.
    w.fighters[1].x = w.fighters[0].x + Fx::int(1);
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

/// x = ±85, 15 below the stage (about 36 units past each main-stage ledge): deep
/// enough that only the up special gets back. This sits in the band where a
/// full-drift up special used to drop below the top just outside the corner and slip
/// under the stage; the stage's solid sides now stop it at the ledge.
fn up_special_starts() -> [(Fx, i32); 2] {
    [(Fx::int(-85), 1), (Fx::int(85), -1)]
}

#[test]
fn easy_cpu_up_specials_back_without_a_double_jump() {
    for (x, _) in up_special_starts() {
        let (mut w, mut cpu) = (world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state, f.air_jumps_left) = (x, Fx::int(-15), None, State::Air, 0);
        let (mut used_up_special, mut landed) = (false, false);
        for _ in 0..240 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            used_up_special |= matches!(w.fighters[1].state, State::Attack { mv: MoveId::UpSpecial, .. });
            // Once back, it may be mid-hop at the end, so look for any landing.
            landed |= w.fighters[1].grounded();
        }
        assert!(used_up_special, "from x={x:?}");
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x:?}");
        assert!(landed, "not back on stage from x={x:?}");
    }
}

#[test]
fn cpu_facing_away_from_the_stage_reverses_its_up_special_toward_it() {
    for (x, toward) in up_special_starts() {
        let (mut w, mut cpu) = (world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state, f.air_jumps_left, f.facing) = (x, Fx::int(-15), None, State::Air, 0, -toward);
        let (mut up_special_facing, mut landed) = (None, false);
        for _ in 0..240 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            if let State::Attack { mv: MoveId::UpSpecial, frame: 4, .. } = w.fighters[1].state {
                up_special_facing.get_or_insert(w.fighters[1].facing);
            }
            landed |= w.fighters[1].grounded();
        }
        assert_eq!(up_special_facing, Some(toward), "from x={x:?}");
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x:?}");
        assert!(landed, "not back on stage from x={x:?}");
    }
}

#[test]
fn easy_cpu_grabs_and_throws_sometimes() {
    // Plenty of stocks: the CPU takes three off an idle dummy well inside two minutes.
    // Grabs are a small share of an easy CPU's openings, so a few seeds' worth.
    let (mut grabs, mut throws) = (0, 0);
    for seed in 0..3 {
        let (mut w, mut cpu) = (World::new(Stage::battlefield(), &[Character::Chef; 2], 99), Cpu::easy(1).with_seed(seed));
        for _ in 0..60 * 120 {
            let input = cpu.think(&w);
            w.step(&[idle(&w), input]);
            grabs += w.events.iter().filter(|e| matches!(e, Event::Grab { attacker: 1, .. })).count();
            throws += matches!(w.fighters[1].state, State::Attack { mv: MoveId::FThrow | MoveId::BThrow | MoveId::UThrow | MoveId::DThrow, frame: 1, .. }) as usize;
        }
    }
    assert!(grabs > 0 && throws > 0, "{grabs} grabs, {throws} throws in 3 x 2 minutes");
}

#[test]
fn easy_cpu_shields_some_attacks() {
    // An easy CPU reacts 25 frames into an attack, so it can't shield a jab (out on
    // frame 2) on reaction, but it sees a charged smash coming. Every 100 frames P1
    // turns toward it and charges one (held 30 frames) from where it stands. It defends
    // under a fifth of the attacks it sees, and few of them reach it, so ten seeds' worth.
    let mut shielded = 0;
    for seed in 0..10 {
        let (mut w, mut cpu) = (world(), Cpu::easy(1).with_seed(seed));
        w.fighters[1].x = Fx::int(-30);
        for f in 0..60 * 60 {
            let toward = if w.fighters[1].x < w.fighters[0].x { -30 } else { 30 };
            let p1 = match f % 100 {
                0..2 => Input { stick_x: toward, ..Input::default() },
                2..32 => Input { buttons: Input::SMASH, ..Input::default() },
                _ => Input::default(),
            };
            let input = cpu.think(&w);
            w.step(&[p1, input]);
            shielded += w.events.iter().filter(|e| matches!(e, Event::ShieldHit { defender: 1, .. })).count();
        }
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
        let (mut used_ear_copter, mut landed) = (false, false);
        for _ in 0..300 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            used_ear_copter |= matches!(w.fighters[1].state, State::Attack { mv: MoveId::PugEarCopter, .. });
            // Once back, it may be mid-hop at the end, so look for any landing.
            landed |= w.fighters[1].grounded();
        }
        assert!(used_ear_copter, "from x={x}");
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x}");
        assert!(landed, "not back on stage from x={x}");
    }
}

fn samurai_cpu_world() -> World {
    World::new(Stage::battlefield(), &[Character::Chef, Character::Samurai], 3)
}

#[test]
fn easy_cpu_lands_hits_as_the_samurai() {
    let (mut w, mut cpu) = (samurai_cpu_world(), Cpu::easy(1));
    let (_, hits) = vs_idle(&mut w, &mut cpu, 600);
    assert!(hits > 0, "never hit an idle opponent in 10 s");
}

#[test]
fn easy_cpu_samurai_cyclones_back_without_air_jumps() {
    for x in [-85, 85] {
        let (mut w, mut cpu) = (samurai_cpu_world(), Cpu::easy(1));
        let f = &mut w.fighters[1];
        (f.x, f.y, f.grounded_on, f.state, f.air_jumps_left) = (Fx::int(x), Fx::int(-15), None, State::Air, 0);
        let (mut used_cyclone, mut landed) = (false, false);
        for _ in 0..300 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            used_cyclone |= matches!(w.fighters[1].state, State::Attack { mv: MoveId::SamuraiCyclone, .. });
            // Once back, it may be mid-hop at the end, so look for any landing.
            landed |= w.fighters[1].grounded();
        }
        assert!(used_cyclone, "from x={x}");
        assert_eq!(w.fighters[1].stocks, 3, "fell from x={x}");
        assert!(landed, "not back on stage from x={x}");
    }
}

#[test]
fn level_3_is_easy_and_levels_clamp() {
    assert_eq!(CpuLevel::level(3), &CpuLevel::EASY);
    assert_eq!(CpuLevel::level(0), CpuLevel::level(CpuLevel::MIN));
    assert_eq!(CpuLevel::level(42), CpuLevel::level(CpuLevel::MAX));
}

#[test]
fn higher_cpu_levels_attack_more() {
    let attacks = |level| {
        let (mut w, mut cpu) = (world(), Cpu::with_level(1, level));
        vs_idle(&mut w, &mut cpu, 60 * 30).0
    };
    let (low, mid, high) = (attacks(1), attacks(5), attacks(9));
    // Level 1 clearly swings the least. The top two can't be ordered strictly here:
    // the more aggressive CPU knocks its target onto the ledge and re-approaches
    // more often, which paces its swing count down to the less aggressive CPU's level.
    assert!(low < mid && low < high, "attacks in 30 s: level 1 {low}, level 5 {mid}, level 9 {high}");
}

#[test]
fn top_level_cpu_still_finishes_hop_attacks() {
    // Its reaction time is shorter than a hop attack; the plan must not be dropped midway.
    let (mut w, mut cpu) = (world(), Cpu::with_level(1, CpuLevel::MAX));
    let mut aerials = 0;
    for _ in 0..60 * 60 {
        let input = cpu.think(&w);
        w.step(&[idle(&w), input]);
        aerials += matches!(w.fighters[1].state, State::Attack { mv: MoveId::Nair | MoveId::Fair, frame: 1, .. }) as usize;
    }
    assert!(aerials > 0, "no aerials in a minute");
}

#[test]
fn every_cpu_level_keeps_its_stocks_on_every_stage() {
    for character in Character::ALL {
        for id in StageId::ALL {
            for level in CpuLevel::MIN..=CpuLevel::MAX {
                let mut w = World::new(id.stage(), &[Character::Chef, character], 3);
                let mut cpu = Cpu::with_level(1, level);
                vs_idle(&mut w, &mut cpu, 60 * 60);
                assert_eq!(w.fighters[1].stocks, 3, "{character:?} at level {level} on {}", id.name());
            }
        }
    }
}

#[test]
fn cpu_lands_hits_on_every_stage() {
    for id in StageId::ALL {
        let mut w = World::new(id.stage(), &[Character::Chef; 2], 3);
        let mut cpu = Cpu::with_level(1, 5);
        let (_, hits) = vs_idle(&mut w, &mut cpu, 60 * 20);
        assert!(hits > 0, "never hit an idle opponent on {}", id.name());
    }
}

/// Plays two CPUs against each other for `frames`. Returns, per port, how many times
/// it started each moveset slot (`Moveset::slots` order) and the damage it dealt.
fn cpu_vs_cpu(w: &mut World, cpus: &mut [Cpu; 2], frames: usize) -> ([[u32; 24]; 2], [i32; 2]) {
    let (mut slots, mut damage) = ([[0; 24]; 2], [0; 2]);
    for _ in 0..frames {
        let before: Vec<Option<MoveId>> = w.fighters.iter().map(current_move).collect();
        let inputs = [cpus[0].think(w), cpus[1].think(w)];
        w.step(&inputs);
        for (i, f) in w.fighters.iter().enumerate() {
            if let Some(mv) = current_move(f)
                && before[i] != Some(mv)
                && let Some(slot) = f.character.moveset().slot_of(mv)
            {
                slots[i][slot] += 1;
            }
        }
        for e in &w.events {
            if let Event::Hit { attacker, damage: d, .. } = *e {
                damage[attacker] += d;
            }
        }
    }
    (slots, damage)
}

fn current_move(f: &Fighter) -> Option<MoveId> {
    if let State::Attack { mv, .. } = f.state { Some(mv) } else { None }
}

/// Puts fighter `i` standing on the Boardwalk's right side platform at `x`.
fn on_side_platform(w: &mut World, i: usize, x: Fx) {
    let plat = w.stage.platforms[2].clone();
    let f = &mut w.fighters[i];
    (f.x, f.y, f.grounded_on, f.state) = (x, plat.y, Some(2), State::Ground);
}

#[test]
fn two_top_cpus_on_a_side_platform_keep_fighting() {
    // The stalemate the balance harness found: both on one side platform, each
    // jumping after the other whenever it was airborne above, almost never attacking.
    for seed in 0..4 {
        let mut w = World::new(StageId::Boardwalk.stage(), &[Character::Chef; 2], 3);
        let plat = w.stage.platforms[2].clone();
        on_side_platform(&mut w, 0, plat.left + Fx::int(6));
        on_side_platform(&mut w, 1, plat.right - Fx::int(6));
        let mut cpus = [Cpu::with_level(0, 9).with_seed(seed), Cpu::with_level(1, 9).with_seed(seed)];
        let (slots, damage) = cpu_vs_cpu(&mut w, &mut cpus, 60 * 60);
        // (The traced stalemate: about 10 attacks in 8 minutes.)
        let moves: u32 = slots.iter().flatten().sum();
        assert!(moves >= 40, "seed {seed}: {moves} moves started in a minute");
        assert!(damage[0] + damage[1] >= 150, "seed {seed}: {damage:?}% dealt in a minute");
        assert!(w.fighters.iter().any(|f| f.stocks < 3), "seed {seed}: no KO in a minute");
    }
}

#[test]
fn cpu_does_not_climb_after_an_opponent_who_is_only_jumping() {
    // P1 jumps over and over (full hop, then double jump at the top) on a flat stage.
    // The CPU shouldn't chase every jump with a full hop and double jump of its own:
    // it waits under P1, anti-airs it, or jumps once with an aerial.
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 99);
    (w.fighters[0].x, w.fighters[1].x) = (Fx::int(0), Fx::int(20));
    let mut cpu = Cpu::with_level(1, 9);
    let (mut double_jumps, mut hits, mut prev_jumps) = (0, 0, w.fighters[1].air_jumps_left);
    for frame in 0..60 * 30 {
        let p1 = &w.fighters[0];
        let jump = match p1.state {
            State::Ground => frame % 2 == 0,
            State::Air => p1.vy <= Fx::ZERO && p1.air_jumps_left > 0 && frame % 2 == 0,
            _ => false,
        };
        let p1_input = Input { buttons: if jump { Input::JUMP } else { 0 }, ..Input::default() };
        let input = cpu.think(&w);
        w.step(&[p1_input, input]);
        let me = &w.fighters[1];
        double_jumps += (me.state == State::Air && me.air_jumps_left < prev_jumps) as usize;
        prev_jumps = me.air_jumps_left;
        hits += w.events.iter().filter(|e| matches!(e, Event::Hit { attacker: 1, .. })).count();
    }
    assert!(hits >= 3, "{hits} hits on a jumping opponent in 30 s");
    assert!(double_jumps <= 2, "double-jumped after it {double_jumps} times in 30 s");
}

/// P1 starts offstage past the right ledge and recovers like a level-1 CPU (which
/// never edge-guards); P2, at `level`, waits on stage. Returns P2's hits on P1 while P1
/// is offstage or on the ledge, and P2's stocks once P1 is back (or 6 s have passed).
fn edge_guard_trial(level: u8, character: Character, seed: u32) -> (usize, u8) {
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef, character], 3);
    let main = w.stage.platforms[0].clone();
    let f = &mut w.fighters[0];
    (f.x, f.y, f.grounded_on, f.state, f.vx) = (main.right + Fx::int(30), Fx::int(10), None, State::Air, Fx::int(1));
    f.percent = 60;
    w.fighters[1].x = main.right - Fx::int(30);
    let mut cpus = [Cpu::with_level(0, 1).with_seed(seed), Cpu::with_level(1, level).with_seed(seed)];
    let mut offstage_hits = 0;
    for _ in 0..60 * 6 {
        let inputs = [cpus[0].think(&w), cpus[1].think(&w)];
        w.step(&inputs);
        let p1 = &w.fighters[0];
        let off = p1.state == State::LedgeHang || (!p1.grounded() && (!main.contains_x(p1.x) || p1.y < main.y));
        offstage_hits += w.events.iter().filter(|e| off && matches!(e, Event::Hit { attacker: 1, .. })).count();
        if p1.grounded() && main.contains_x(p1.x) {
            break;
        }
    }
    // Let P2 finish whatever it started out there.
    for _ in 0..60 * 4 {
        let inputs = [cpus[0].think(&w), cpus[1].think(&w)];
        w.step(&inputs);
    }
    (offstage_hits, w.fighters[1].stocks)
}

#[test]
fn top_cpus_edge_guard_and_low_cpus_do_not() {
    for character in Character::ALL {
        let (mut top, mut low) = (0, 0);
        for seed in 0..10 {
            let (hits, stocks) = edge_guard_trial(9, character, seed);
            assert_eq!(stocks, 3, "{character:?} lost a stock edge-guarding (seed {seed})");
            top += (hits > 0) as usize;
            low += (edge_guard_trial(1, character, seed).0 > 0) as usize;
        }
        assert!(top >= 4, "{character:?}: a level-9 CPU hit the recovering opponent in {top} of 10 tries");
        assert_eq!(low, 0, "{character:?}: a level-1 CPU edge-guarded");
    }
}

#[test]
fn cpu_reaches_for_a_smash_attack_at_kill_percent() {
    // An idle opponent just in front: at 0% the CPU mostly pokes; at 150% it goes for
    // what its launch estimate says KOs, which is its smash attacks.
    let first_move = |percent: i32, seed: u32| {
        let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 3);
        (w.fighters[0].x, w.fighters[1].x, w.fighters[1].facing) = (Fx::int(0), Fx::int(9), -1);
        w.fighters[0].percent = percent;
        let mut cpu = Cpu::with_level(1, 9).with_seed(seed);
        for _ in 0..120 {
            let input = cpu.think(&w);
            w.step(&[Input::default(), input]);
            if let Some(mv) = current_move(&w.fighters[1]) {
                return Some(mv);
            }
        }
        None
    };
    let smash = |mv: Option<MoveId>| matches!(mv, Some(MoveId::FSmash | MoveId::USmash | MoveId::DSmash));
    let (mut low, mut high) = (0, 0);
    for seed in 0..20 {
        low += smash(first_move(0, seed)) as usize;
        high += smash(first_move(150, seed)) as usize;
    }
    assert!(high >= 16, "smash attacks on an opponent at 150%: {high} of 20");
    assert!(low <= 12, "smash attacks on an opponent at 0%: {low} of 20");

    // And the KO lands.
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 3);
    (w.fighters[0].x, w.fighters[1].x, w.fighters[1].facing, w.fighters[0].percent) = (Fx::int(0), Fx::int(9), -1, 150);
    let mut cpu = Cpu::with_level(1, 9);
    for _ in 0..240 {
        let input = cpu.think(&w);
        w.step(&[Input::default(), input]);
    }
    assert!(w.fighters[0].stocks < 3, "no KO at 150% in 4 s");
}

#[test]
fn cpus_use_their_projectiles_at_range() {
    // An idle opponent across the stage: anyone with a projectile special that
    // reaches that far (not the pug's short sneeze cloud) uses it.
    for character in Character::ALL {
        let moves = character.moveset();
        let reaches = |mv: &MoveId| mv.data().projectile.as_ref().is_some_and(|p| p.gravity > Fx::ZERO || p.speed * Fx::int(p.lifetime as i32) > Fx::int(60));
        let shots: Vec<MoveId> = [moves.neutral_special, moves.side_special].into_iter().filter(reaches).collect();
        if shots.is_empty() {
            continue;
        }
        let mut fired = false;
        for seed in 0..10 {
            let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef, character], 3);
            (w.fighters[0].x, w.fighters[1].x, w.fighters[1].facing) = (Fx::int(-28), Fx::int(27), -1);
            let mut cpu = Cpu::with_level(1, 9).with_seed(seed);
            for _ in 0..120 {
                let input = cpu.think(&w);
                w.step(&[Input::default(), input]);
                fired |= current_move(&w.fighters[1]).is_some_and(|mv| shots.contains(&mv));
            }
        }
        assert!(fired, "{character:?} never used {shots:?} from range");
    }
}

#[test]
fn cpu_throws_toward_the_nearest_ledge() {
    // Grabbing an opponent at 100% near the right ledge: facing the ledge it throws
    // forward, with its back to the ledge it throws back.
    for (facing, expected) in [(1, MoveId::FThrow), (-1, MoveId::BThrow)] {
        let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 3);
        let right = w.stage.platforms[0].right;
        let me_x = right - Fx::int(14);
        (w.fighters[1].x, w.fighters[1].facing) = (me_x, facing);
        (w.fighters[0].x, w.fighters[0].percent) = (me_x + Fx::int(6 * facing), 100);
        let mut cpu = Cpu::with_level(1, 9);
        let mut throw = None;
        for f in 0..90 {
            let input = if f == 0 { Input { buttons: Input::GRAB, ..Input::default() } } else { cpu.think(&w) };
            w.step(&[Input::default(), input]);
            let thrown = current_move(&w.fighters[1]).filter(|mv| matches!(mv, MoveId::FThrow | MoveId::BThrow | MoveId::UThrow | MoveId::DThrow));
            if let Some(mv) = thrown {
                throw.get_or_insert(mv);
            }
        }
        assert_eq!(throw, Some(expected), "facing {facing}");
    }
}

#[test]
fn every_characters_cpu_uses_a_wide_part_of_its_moveset() {
    for character in Character::ALL {
        let mut used = [0u32; 24];
        for (i, opponent) in [Character::Chef, Character::Samurai, Character::Hobo].into_iter().enumerate() {
            let mut w = World::new(StageId::ALL[i].stage(), &[character, opponent], 3);
            let mut cpus = [Cpu::with_level(0, 9).with_seed(i as u32), Cpu::with_level(1, 9).with_seed(i as u32)];
            let (slots, _) = cpu_vs_cpu(&mut w, &mut cpus, 60 * 120);
            for (u, n) in used.iter_mut().zip(slots[0]) {
                *u += n;
            }
        }
        let distinct = used.iter().filter(|&&n| n > 0).count();
        assert!(distinct >= 14, "{character:?} used {distinct} of its 24 move slots: {used:?}");
    }
}

// --- Defense: guarding, punishing, DI, air dodges ----------------------------

/// What a CPU at `level` did against P1's forward smash, charged `charge` frames: P1 at
/// x 0 facing right, the CPU standing `gap` in front of it, stuck in `lag` frames of
/// landing lag (so it can't just hit P1 first).
#[derive(Default, Debug)]
struct SmashTrial {
    /// The smash hit it.
    hit: bool,
    /// It shielded the smash or dodged.
    guarded: bool,
    /// It hit P1 before P1 could act again after the smash.
    punished: bool,
}

fn smash_trial(level: u8, seed: u32, gap: i32, charge: u32, lag: u8) -> SmashTrial {
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 3);
    (w.fighters[0].x, w.fighters[0].facing) = (Fx::int(0), 1);
    (w.fighters[1].x, w.fighters[1].facing) = (Fx::int(gap), -1);
    if lag > 0 {
        w.fighters[1].state = State::Landing { frames_left: lag };
    }
    let mut cpu = Cpu::with_level(1, level).with_seed(seed);
    let mut t = SmashTrial::default();
    let mut smash_over = false;
    for f in 0..120 {
        let p1 = if f <= charge { Input { buttons: Input::SMASH, ..Input::default() } } else { Input::default() };
        let input = cpu.think(&w);
        w.step(&[p1, input]);
        let smashing = matches!(w.fighters[0].state, State::Attack { mv: MoveId::FSmash, .. });
        for e in &w.events {
            match e {
                Event::Hit { attacker: 0, defender: 1, .. } => t.hit = true,
                Event::ShieldHit { defender: 1, .. } => t.guarded = true,
                Event::Hit { attacker: 1, defender: 0, .. } if !smash_over => t.punished = true,
                _ => {}
            }
        }
        t.guarded |= matches!(w.fighters[1].state, State::Dodge { .. });
        smash_over |= f > 2 && !smashing;
    }
    t
}

#[test]
fn top_cpu_shields_or_dodges_a_telegraphed_smash_attack() {
    // Free 2 frames before an uncharged smash hits (it sees it from frame 10), or as a
    // charged one is still being held.
    let trials: Vec<SmashTrial> =
        (0..10).map(|seed| smash_trial(9, seed, 9, 0, 12)).chain((0..10).map(|seed| smash_trial(9, seed, 9, 30, 20))).collect();
    let safe = trials.iter().filter(|t| !t.hit).count();
    let guarded = trials.iter().filter(|t| t.guarded).count();
    assert!(safe >= 16, "a level-9 CPU took the smash in {} of 20 tries: {trials:?}", 20 - safe);
    assert!(guarded >= 14, "it shielded or dodged in {guarded} of 20: {trials:?}");
}

#[test]
fn top_cpu_punishes_a_whiffed_smash_attack() {
    // P1 swings an uncharged smash at nothing, just out of its reach: the CPU hits it
    // in the end lag (the smash has 48 frames, hitting on 14-16).
    let trials: Vec<SmashTrial> = (0..10).map(|seed| smash_trial(9, seed, 24, 0, 0)).collect();
    let punished = trials.iter().filter(|t| t.punished && !t.hit).count();
    assert!(punished >= 7, "a level-9 CPU punished a whiffed smash in {punished} of 10: {trials:?}");
}

/// The chef's forward smash from near the right ledge on P2 at `percent`, P2 holding
/// nothing until the hit lands; from then on `cpu` (if any) drives P2. Whether P2
/// was KO'd.
fn launched(percent: i32, mut cpu: Option<Cpu>) -> bool {
    let mut w = World::new(Stage::battlefield(), &[Character::Chef; 2], 3);
    (w.fighters[0].x, w.fighters[0].facing) = (Fx::int(30), 1);
    (w.fighters[1].x, w.fighters[1].percent) = (Fx::int(38), percent);
    let mut hit = false;
    for f in 0..300 {
        let p1 = if f == 0 { Input { stick_x: 60, buttons: Input::SMASH, ..Input::default() } } else { Input::default() };
        let p2 = match cpu.as_mut() {
            Some(c) if hit => c.think(&w),
            _ => Input::default(),
        };
        w.step(&[p1, p2]);
        hit |= w.events.iter().any(|e| matches!(e, Event::Hit { defender: 1, .. }));
        if w.events.contains(&Event::Ko { fighter: 1 }) {
            return true;
        }
    }
    assert!(hit, "the smash never hit");
    false
}

#[test]
fn top_cpu_dis_to_survive_a_hit_that_would_ko_without_di() {
    // At 75% the smash from there KOs with no DI (see `survival_di_lives_to_a_higher_percent`).
    assert!(launched(75, None), "no DI: should KO");
    let survived = (0..10).filter(|&seed| !launched(75, Some(Cpu::with_level(1, 9).with_seed(seed)))).count();
    assert!(survived >= 8, "a level-9 CPU survived {survived} of 10");
}

/// P2 drifting back in from just past the right ledge, a little above it, as P1 swings
/// a forward smash off the ledge where P2's fall takes it (frames 14-16). Returns (air
/// dodged, hit, stocks lost).
fn edge_guard_dodge_trial(level: u8, seed: u32) -> (bool, bool, bool) {
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 3);
    let right = w.stage.platforms[0].right;
    (w.fighters[0].x, w.fighters[0].facing) = (right - Fx::int(4), 1);
    let f = &mut w.fighters[1];
    (f.x, f.y, f.grounded_on, f.state, f.vx) = (right + Fx::int(18), Fx::int(12), None, State::Air, Fx::ratio(-8, 10));
    let mut cpu = Cpu::with_level(1, level).with_seed(seed);
    let (mut dodged, mut hit) = (false, false);
    for frame in 0..300 {
        let p1 = if frame == 0 { Input { buttons: Input::SMASH, ..Input::default() } } else { Input::default() };
        let input = cpu.think(&w);
        w.step(&[p1, input]);
        dodged |= matches!(w.fighters[1].state, State::Dodge { kind: DodgeKind::Air | DodgeKind::AirDirectional, .. });
        hit |= w.events.iter().any(|e| matches!(e, Event::Hit { defender: 1, .. }));
    }
    (dodged, hit, w.fighters[1].stocks < 3)
}

#[test]
fn top_cpu_air_dodges_through_an_edge_guard() {
    // Without a dodge the smash meets it on its way in; the low CPU shows that.
    let low_hits = (0..10).filter(|&seed| edge_guard_dodge_trial(1, seed).1).count();
    assert!(low_hits >= 8, "the edge-guard should land on a CPU that doesn't dodge: {low_hits} of 10");
    let trials: Vec<_> = (0..10).map(|seed| edge_guard_dodge_trial(9, seed)).collect();
    let through = trials.iter().filter(|&&(dodged, hit, lost)| dodged && !hit && !lost).count();
    assert!(through >= 7, "a level-9 CPU air-dodged through it and made it back in {through} of 10: {trials:?}");
}

#[test]
fn level_1_cpu_rarely_defends_dis_or_air_dodges() {
    let guarded = (0..20).filter(|&seed| smash_trial(1, seed, 9, 0, 12).guarded || smash_trial(1, seed, 9, 30, 20).guarded).count();
    assert!(guarded <= 2, "a level-1 CPU guarded a smash in {guarded} of 20 pairs of tries");
    let survived = (0..10).filter(|&seed| !launched(75, Some(Cpu::with_level(1, 1).with_seed(seed)))).count();
    assert_eq!(survived, 0, "a level-1 CPU DI'd out of a KO");
    let dodged = (0..10).filter(|&seed| edge_guard_dodge_trial(1, seed).0).count();
    assert!(dodged <= 1, "a level-1 CPU air-dodged an edge-guard {dodged} times in 10");
}

/// The soldier (the shortest recovery) starting `dx` past the right ledge at stage
/// height, falling, recovering at `level`. Returns (made it, air-dodged, hung from the ledge).
fn far_recovery(level: u8, seed: u32, dx: i32) -> (bool, bool, bool) {
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef, Character::Soldier], 3);
    let right = w.stage.platforms[0].right;
    let f = &mut w.fighters[1];
    (f.x, f.y, f.grounded_on, f.state) = (right + Fx::int(dx), Fx::int(0), None, State::Air);
    let mut cpu = Cpu::with_level(1, level).with_seed(seed);
    let (mut dodged, mut hung) = (false, false);
    for _ in 0..300 {
        let input = cpu.think(&w);
        w.step(&[Input::default(), input]);
        dodged |= matches!(w.fighters[1].state, State::Dodge { kind: DodgeKind::AirDirectional, .. });
        hung |= w.fighters[1].state == State::LedgeHang;
    }
    (w.fighters[1].stocks == 3, dodged, hung)
}

#[test]
fn top_cpu_air_dodges_in_to_recover_from_farther_out() {
    // 90 units out is past the soldier's jump-and-up-special reach (the plain recovery a
    // level-1 CPU uses), but an air dodge toward the stage first covers the rest.
    for seed in 0..5 {
        assert!(!far_recovery(1, seed, 90).0, "level 1 made it back from 90 out (seed {seed}): the test is too easy");
        let (made_it, dodged, _) = far_recovery(9, seed, 90);
        assert!(made_it && dodged, "level 9 didn't air-dodge back (seed {seed}): made it {made_it}, dodged {dodged}");
    }
}

#[test]
fn top_cpu_mixes_up_its_recovery() {
    // From a comfortable 30 units out the plain recovery always works; level 9 still
    // varies it (air dodge in, ledge hang, high or low), level 1 never does.
    let paths = |level| {
        let mut seen: Vec<(bool, bool)> = Vec::new();
        for seed in 0..20 {
            let (made_it, dodged, hung) = far_recovery(level, seed, 30);
            assert!(made_it, "level {level} fell from 30 out (seed {seed})");
            if !seen.contains(&(dodged, hung)) {
                seen.push((dodged, hung));
            }
        }
        seen.len()
    };
    assert_eq!(paths(1), 1, "level 1 recovers one way");
    assert!(paths(9) >= 2, "level 9 recovered only one way");
}

/// P2 at `level` up-tilts P1 (at `percent`) into the air, then plays on: whether it
/// lands another hit while P1 is still airborne from that launch.
fn follow_up(level: u8, seed: u32, percent: i32) -> bool {
    let mut w = World::new(StageId::Sandbar.stage(), &[Character::Chef; 2], 3);
    (w.fighters[0].x, w.fighters[0].percent) = (Fx::int(0), percent);
    (w.fighters[1].x, w.fighters[1].facing) = (Fx::int(6), -1);
    let mut cpu = Cpu::with_level(1, level).with_seed(seed);
    let mut launched = false;
    for f in 0..120 {
        let input = if launched { cpu.think(&w) } else if f == 0 { Input { stick_y: 60, buttons: Input::ATTACK, ..Input::default() } } else { Input::default() };
        w.step(&[Input::default(), input]);
        let hit = w.events.iter().any(|e| matches!(e, Event::Hit { attacker: 1, .. }));
        if launched && hit {
            return true;
        }
        launched |= hit;
        if launched && w.fighters[0].grounded() && !matches!(w.fighters[0].state, State::Hitstun { .. }) {
            return false;
        }
    }
    false
}

#[test]
fn top_cpu_chases_a_launched_opponent_with_a_follow_up() {
    let top = (0..10).filter(|&seed| follow_up(9, seed, 40)).count();
    let low = (0..10).filter(|&seed| follow_up(1, seed, 40)).count();
    assert!(top >= 6, "level 9 followed up {top} of 10 times");
    assert!(top > low + 3, "level 9 followed up {top} of 10, level 1 {low}");
}
