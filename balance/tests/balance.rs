//! Small, fast checks of the harness. Real runs go through the `balance` binary.

use fight_balance::report::{render, to_csv, to_json, tuning_diff};
use fight_balance::{Knobs, MatchConfig, TournamentConfig, TunerConfig, Tuning, Verdict, run_match, run_tournament, tune};
use fight_sim::{Character, StageId};

fn config(characters: [Character; 2], seed: u64) -> MatchConfig {
    MatchConfig { characters, stage: StageId::Boardwalk, levels: [9, 9], stocks: 3, seed, frame_cap: 8 * 60 * 60 }
}

#[test]
fn a_match_replays_identically_for_a_seed_and_differs_across_seeds() {
    let c = config([Character::Chef, Character::Samurai], 3);
    assert_eq!(run_match(&c, &Tuning::default()), run_match(&c, &Tuning::default()));
    let results: Vec<_> = (0..4).map(|seed| run_match(&config([Character::Chef, Character::Samurai], seed), &Tuning::default())).collect();
    assert!(results.windows(2).any(|w| w[0] != w[1]), "four seeds, one match: {results:?}");
}

#[test]
fn a_match_ends_with_a_winner_out_of_stocks() {
    let r = run_match(&config([Character::Chef, Character::Pug], 1), &Tuning::default());
    assert!(!r.timed_out && r.frames < 8 * 60 * 60, "{r:?}");
    let winner = r.winner.expect("a winner");
    assert_eq!(r.stocks[1 - winner], 0);
    assert!(r.stocks[winner] > 0);
    assert!(r.damage_dealt[winner] > 0 && r.hits[winner] > 0 && r.attacks[winner] >= r.hits[winner] / 4);
}

#[test]
fn a_match_stops_at_the_frame_cap_and_is_decided_on_stocks_then_percent() {
    let r = run_match(&MatchConfig { frame_cap: 1200, ..config([Character::Chef, Character::Hobo], 5) }, &Tuning::default());
    assert!(r.timed_out);
    assert_eq!(r.frames, 1200);
    let expected = match r.stocks[0].cmp(&r.stocks[1]).then(r.percent[1].cmp(&r.percent[0])) {
        std::cmp::Ordering::Greater => Some(0),
        std::cmp::Ordering::Less => Some(1),
        std::cmp::Ordering::Equal => None,
    };
    assert_eq!(r.winner, expected, "{r:?}");
}

#[test]
fn no_knobs_plays_the_shipped_tuning() {
    let t = Tuning::default();
    for c in Character::ALL {
        assert!(std::ptr::eq(t.params(c), c.params()));
    }
    let mut t = Tuning::new(&[(Character::Pug, Knobs { damage: 5, weight: -3, ..Knobs::default() })]);
    assert_eq!(t.params(Character::Pug).damage_scale, Character::Pug.params().damage_scale + 5);
    assert_eq!(t.params(Character::Pug).weight, Character::Pug.params().weight - 3);
    assert_eq!(t.params(Character::Pug).gravity, Character::Pug.params().gravity);
    assert!(std::ptr::eq(t.params(Character::Chef), Character::Chef.params()));
    t.set(Character::Pug, Knobs::default());
    assert!(std::ptr::eq(t.params(Character::Pug), Character::Pug.params()), "zero knobs drop the override");
}

#[test]
fn knobs_parse_from_the_command_line_form() {
    assert_eq!(Knobs::parse("damage=+4,weight=-3").unwrap(), Knobs { damage: 4, weight: -3, ..Knobs::default() });
    assert_eq!(Knobs::parse("knockback=2,speed=-5").unwrap(), Knobs { knockback: 2, speed: -5, ..Knobs::default() });
    assert!(Knobs::parse("height=3").is_err());
    assert!(Knobs::parse("damage").is_err());
}

#[test]
fn knobs_change_the_outcome() {
    let c = config([Character::Chef, Character::Chef], 11);
    let buffed = Tuning::new(&[(Character::Chef, Knobs { damage: 20, ..Knobs::default() })]);
    assert_ne!(run_match(&c, &Tuning::default()), run_match(&c, &buffed));
}

#[test]
fn tournaments_are_deterministic_whatever_the_thread_count() {
    let t = TournamentConfig {
        characters: vec![Character::Chef, Character::Ninja],
        stages: vec![StageId::Driftwood],
        games: 2,
        ..TournamentConfig::default()
    };
    let one = run_tournament(&TournamentConfig { threads: 1, ..t.clone() }, &Tuning::default());
    let many = run_tournament(&TournamentConfig { threads: 4, ..t.clone() }, &Tuning::default());
    assert_eq!(one.len(), 2 * 2 * 2, "every ordered pair, mirrors included, twice");
    assert_eq!(one, many);
}

#[test]
fn a_narrower_roster_replays_the_same_games() {
    let all = TournamentConfig { stages: vec![StageId::Sandbar], games: 1, ..TournamentConfig::default() };
    let some = TournamentConfig { characters: vec![Character::Pug, Character::Hobo], ..all.clone() };
    let pug_hobo = |t: &TournamentConfig| t.schedule().into_iter().find(|(c, _)| c.characters == [Character::Pug, Character::Hobo]).unwrap().0.seed;
    assert_eq!(pug_hobo(&all), pug_hobo(&some));
}

#[test]
fn mirror_matches_are_roughly_even() {
    let t = TournamentConfig { characters: vec![Character::Chef], stages: vec![StageId::Sandbar], games: 80, ..TournamentConfig::default() };
    let rounds = tune(&t, &Tuning::default(), &TunerConfig { rounds: 0, ..TunerConfig::default() }, |_| {});
    let p1 = rounds[0].summary.port_bias;
    assert_eq!(p1.games, 80);
    // Three standard errors: a fixed seed set, so this can't flake, but a real port
    // bias (or a runner that favours one side) would land outside it.
    assert!((p1.rate() - 0.5).abs() < 3.0 * p1.stderr(), "P1 wins {:.1}% of chef mirrors", p1.rate() * 100.0);
}

#[test]
fn the_loop_buffs_the_loser_and_only_proposes() {
    let t = TournamentConfig {
        characters: vec![Character::Samurai, Character::Ninja],
        stages: vec![StageId::Sandbar],
        games: 12,
        ..TournamentConfig::default()
    };
    let tuner = TunerConfig { rounds: 1, sigmas: 1.0, ..TunerConfig::default() };
    let rounds = tune(&t, &Tuning::default(), &tuner, |_| {});
    assert_eq!(rounds.len(), 2, "baseline plus one round");
    let base = &rounds[0].summary;
    let ninja = base.index(Character::Ninja).unwrap();
    assert!(base.overall[ninja].rate() < 0.45, "the ninja loses this matchup under CPU play");
    assert!(matches!(rounds[0].verdicts[ninja], Verdict::Adjust(step) if step > 0), "{:?}", rounds[0].verdicts);
    let knobs = rounds[1].tuning.knobs(Character::Ninja);
    assert!(knobs.damage > 0 && knobs.weight > 0, "{knobs:?}");
    // The report shows it as a reviewable diff; the source is never touched.
    assert!(tuning_diff(&rounds[1].tuning).contains("FighterParams::NINJA"));
    let text = render(&rounds);
    assert!(text.contains("## Suggestion") && text.contains("Caveat"));
    assert!(to_json(&rounds).starts_with("{\"best_round\":"));
    assert_eq!(to_csv(&rounds).lines().count(), 1 + 2 * 4);
}
