//! Readable tables, a source diff of the suggested tuning, and JSON / CSV dumps.

use std::fmt::Write;

use fight_sim::{Character, Fx};

use crate::summary::{Score, TIMEOUT_FLAG};
use crate::tuner::{Round, Verdict};
use crate::tuning::Tuning;

/// The moves the CPU actually uses, so readers know what the numbers measure.
pub const AI_CAVEAT: &str = "\
CPU-vs-CPU results measure each character *as the CPU plays it*, not the character's
ceiling. The CPU (sim/src/cpu.rs) walks, jabs, forward/up tilts, short-hops into an
aerial, grabs and forward-throws, shields, and recovers with double jump then up
special. It never uses smash attacks, neutral/side/down specials, other aerials or
throws, dodges or edge-guards, and it spaces every character with the same attack
range. Characters whose strength is in moves the CPU ignores will look weaker than
they are. Nobody edge-guards, so most KOs are failed recoveries (bottom%): recovery
reach weighs more here than in human play. Flagged characters' rates say more about
the AI (or a ledge/recovery bug) than the character: fix those before tuning.";

fn pct(x: f64) -> String {
    if x.is_nan() { "-".into() } else { format!("{:.1}", x * 100.0) }
}

fn verdict_text(v: &Verdict) -> String {
    match v {
        Verdict::InBand => "ok".into(),
        Verdict::Noisy => "noisy: more games".into(),
        Verdict::HeldForAi(_) => "held: AI issue".into(),
        Verdict::AtLimit => "at tuning limit".into(),
        Verdict::Adjust(s) if *s > 0 => format!("buff +{s}"),
        Verdict::Adjust(s) => format!("nerf {s}"),
        Verdict::Later(s) if *s > 0 => format!("later: buff +{s}"),
        Verdict::Later(s) => format!("later: nerf {s}"),
    }
}

/// The round whose overall rates sit closest to 50% (root mean square).
pub fn best_round(rounds: &[Round]) -> usize {
    let spread = |r: &Round| {
        let o = &r.summary.overall;
        o.iter().map(|s| (s.rate() - 0.5).powi(2)).sum::<f64>() / o.len().max(1) as f64
    };
    (0..rounds.len()).min_by(|&a, &b| spread(&rounds[a]).total_cmp(&spread(&rounds[b]))).unwrap_or(0)
}

/// One round's tables: the matchup matrix, overall rates and the AI check.
pub fn round_tables(round: &Round) -> String {
    let s = &round.summary;
    let mut out = String::new();
    let names: Vec<&str> = s.characters.iter().map(|c| c.name()).collect();
    let cell_games = s.games_per_pair * 2 * s.stages.len() as u32;
    let typical_se = Score { games: cell_games, wins: cell_games / 2, draws: 0 }.stderr();
    let stage_names: Vec<&str> = s.stages.iter().map(|st| st.name()).collect();
    let _ = writeln!(
        out,
        "Win rate %, row vs column: {} games per cell (both ports, {}), level {} CPUs, {} stocks. \
         Diagonal = P1's rate in the mirror. A cell's standard error is about ±{:.1}.",
        cell_games,
        stage_names.join(", "),
        s.level,
        s.stocks,
        typical_se * 100.0
    );
    let _ = write!(out, "{:<10}", "");
    for n in &names {
        let _ = write!(out, "{n:>9}");
    }
    out.push('\n');
    for (r, n) in names.iter().enumerate() {
        let _ = write!(out, "{n:<10}");
        for c in 0..names.len() {
            let cell = s.matrix[r][c];
            let text = if r == c { format!("({})", pct(cell.rate())) } else { pct(cell.rate()) };
            let _ = write!(out, "{text:>9}");
        }
        out.push('\n');
    }
    let pb = s.port_bias;
    let _ = writeln!(out, "Port bias: P1 wins {}% ± {:.1} of {} mirror games.", pct(pb.rate()), pb.stderr() * 100.0, pb.games);
    let _ = writeln!(
        out,
        "Timeouts: {}% of games hit the frame cap (decided on stocks, then percent){}.\n",
        pct(s.timeout_rate()),
        if s.timeout_rate() > TIMEOUT_FLAG { ": cast-wide, so most likely a CPU stalemate, not a character" } else { "" }
    );

    let _ = write!(out, "{:<10}{:>7}{:>6}{:>7}", "Overall", "win%", "±SE", "games");
    for st in &stage_names {
        let _ = write!(out, "{:>10}", st);
    }
    let _ = writeln!(out, "  verdict   (knobs this round)");
    for (i, n) in names.iter().enumerate() {
        let o = s.overall[i];
        let _ = write!(out, "{n:<10}{:>7}{:>6.1}{:>7}", pct(o.rate()), o.stderr() * 100.0, o.games);
        for st in &s.by_stage[i] {
            let _ = write!(out, "{:>10}", pct(st.rate()));
        }
        let _ = writeln!(out, "  {:<18}({})", verdict_text(&round.verdicts[i]), round.tuning.knobs(s.characters[i]));
    }
    out.push('\n');

    let _ = writeln!(
        out,
        "{:<10}{:>8}{:>10}{:>7}{:>7}{:>9}{:>10}  AI flags",
        "AI check", "SD/KO%", "bottom%", "reach", "hit%", "dmg/min", "timeout%"
    );
    for (i, n) in names.iter().enumerate() {
        let p = &s.play[i];
        let flags: Vec<String> = s.flags(i).iter().map(ToString::to_string).collect();
        let _ = writeln!(
            out,
            "{n:<10}{:>8}{:>10}{:>7}{:>7}{:>9.1}{:>10}  {}",
            pct(p.self_destruct_rate()),
            pct(p.bottom_ko_rate()),
            s.recovery[i].reach,
            pct(p.accuracy()),
            p.damage_per_minute(),
            pct(p.timeout_rate()),
            if flags.is_empty() { "-".into() } else { flags.join("; ") }
        );
    }
    let _ = writeln!(
        out,
        "SD/KO%: stocks lost with no hit in the last 5 s. bottom%: stocks lost off the bottom \
         (failed recoveries). reach: how far past the ledge the CPU recovers from, in units."
    );
    out
}

/// Fx as a source literal: `Fx::ratio(n, 1000)`.
fn fx_literal(v: Fx) -> String {
    let thousandths = (v.raw() as i64 * 1000 + (1 << 15)) >> 16;
    format!("Fx::ratio({thousandths}, 1000)")
}

/// The source lines `tuning` changes, as a diff against `sim/src/fighter.rs`.
pub fn tuning_diff(tuning: &Tuning) -> String {
    let mut out = String::new();
    for (c, _) in tuning.changed() {
        let (old, new) = (c.params(), tuning.params(c));
        let _ = writeln!(out, "--- sim/src/fighter.rs  FighterParams::{}", c.name().to_uppercase());
        let int_fields = [
            ("weight", old.weight, new.weight),
            ("damage_scale", old.damage_scale, new.damage_scale),
            ("knockback_scale", old.knockback_scale, new.knockback_scale),
        ];
        for (field, a, b) in int_fields {
            if a != b {
                let _ = writeln!(out, "-        {field}: {a},\n+        {field}: {b},");
            }
        }
        let fx_fields = [
            ("walk_speed", old.walk_speed, new.walk_speed),
            ("run_speed", old.run_speed, new.run_speed),
            ("air_speed", old.air_speed, new.air_speed),
            ("jump_h_speed", old.jump_h_speed, new.jump_h_speed),
        ];
        for (field, a, b) in fx_fields {
            if a != b {
                let _ = writeln!(out, "-        {field}: {} (≈{:.3}),\n+        {field}: {},", fx_literal(a), a.to_f32(), fx_literal(b));
            }
        }
    }
    out
}

/// The full report: every round's tables, then the suggestion. Plain text that also
/// reads as Markdown.
pub fn render(rounds: &[Round]) -> String {
    let mut out = String::new();
    let tuned = rounds.len() > 1;
    for (r, round) in rounds.iter().enumerate() {
        let title = if r == 0 { "Baseline".to_string() } else { format!("Round {r}") };
        let _ = writeln!(out, "## {title}: {} games, seed {}\n\n```", round.summary.total_games, round.summary.seed);
        out.push_str(&round_tables(round));
        out.push_str("```\n\n");
    }

    let best = best_round(rounds);
    let first = &rounds[0];
    let chosen = &rounds[best];
    let _ = writeln!(out, "## Suggestion\n");
    if tuned {
        let _ = writeln!(out, "Closest to even: {}.", if best == 0 { "the baseline".to_string() } else { format!("round {best}") });
    }
    let changes: Vec<(Character, String)> = chosen
        .tuning
        .changed()
        .into_iter()
        .filter(|(c, k)| first.tuning.knobs(*c) != *k)
        .map(|(c, k)| {
            let (i0, i1) = (first.summary.index(c), chosen.summary.index(c));
            let before = i0.map_or("-".into(), |i| format!("{}% ± {:.1}", pct(first.summary.overall[i].rate()), first.summary.overall[i].stderr() * 100.0));
            let after = i1.map_or("-".into(), |i| format!("{}% ± {:.1}", pct(chosen.summary.overall[i].rate()), chosen.summary.overall[i].stderr() * 100.0));
            (c, format!("{}: {k}   (win rate {before} -> {after})", c.name()))
        })
        .collect();
    if changes.is_empty() {
        if tuned {
            let _ = writeln!(out, "No change: the tuning that played closest to even is the one you started with.");
        } else {
            let wants: Vec<String> = first
                .summary
                .characters
                .iter()
                .zip(&first.verdicts)
                .filter(|&(_, v)| matches!(v, Verdict::Adjust(_) | Verdict::Later(_)))
                .map(|(c, v)| format!("{} ({})", c.name(), verdict_text(v)))
                .collect();
            if wants.is_empty() {
                let _ = writeln!(out, "Nobody is clearly out of line.");
            } else {
                let _ = writeln!(out, "Out of line: {}. Run with --tune to try changes.", wants.join(", "));
            }
        }
    } else {
        let _ = writeln!(out, "Proposed knobs (relative to sim/src/fighter.rs). Nothing was written to the source:\n");
        for (_, line) in &changes {
            let _ = writeln!(out, "- {line}");
        }
        let _ = writeln!(out, "\n```diff\n{}```", tuning_diff(&chosen.tuning));
        let _ = writeln!(out, "\nRe-check on fresh seeds before applying (e.g. --seed 100), and re-run after any CPU change.");
    }
    let held: Vec<String> = first
        .summary
        .characters
        .iter()
        .zip(&first.verdicts)
        .filter_map(|(c, v)| match v {
            Verdict::HeldForAi(flags) => Some(format!("{}: {}", c.name(), flags.iter().map(ToString::to_string).collect::<Vec<_>>().join("; "))),
            _ => None,
        })
        .collect();
    if !held.is_empty() {
        let _ = writeln!(out, "\nNot tuned, fix the CPU first:");
        for h in held {
            let _ = writeln!(out, "- {h}");
        }
    }
    let _ = writeln!(out, "\n## Caveat\n\n{AI_CAVEAT}");
    out
}

fn json_str(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

fn json_num(x: f64) -> String {
    if x.is_finite() { format!("{x:.4}") } else { "null".into() }
}

fn score_json(s: &Score) -> String {
    format!(
        "{{\"games\":{},\"wins\":{},\"draws\":{},\"losses\":{},\"rate\":{},\"stderr\":{}}}",
        s.games,
        s.wins,
        s.draws,
        s.losses(),
        json_num(s.rate()),
        json_num(s.stderr())
    )
}

/// Every round as JSON: config, knobs, matrix, overall rates, play stats, flags, verdicts.
pub fn to_json(rounds: &[Round]) -> String {
    let mut rs = Vec::new();
    for round in rounds {
        let s = &round.summary;
        let characters: Vec<String> = s
            .characters
            .iter()
            .enumerate()
            .map(|(i, &c)| {
                let k = round.tuning.knobs(c);
                let p = &s.play[i];
                let flags: Vec<String> = s.flags(i).iter().map(|f| json_str(&f.to_string())).collect();
                let by_stage: Vec<String> =
                    s.stages.iter().zip(&s.by_stage[i]).map(|(st, sc)| format!("{}:{}", json_str(st.name()), score_json(sc))).collect();
                format!(
                    "{{\"name\":{},\"knobs\":{{\"damage\":{},\"knockback\":{},\"weight\":{},\"speed\":{}}},\"overall\":{},\"by_stage\":{{{}}},\
                     \"play\":{{\"games\":{},\"self_destruct_rate\":{},\"bottom_ko_rate\":{},\"recovery_reach\":{},\"accuracy\":{},\"damage_per_minute\":{},\"timeout_rate\":{}}},\
                     \"ai_flags\":[{}],\"verdict\":{}}}",
                    json_str(c.name()),
                    k.damage,
                    k.knockback,
                    k.weight,
                    k.speed,
                    score_json(&s.overall[i]),
                    by_stage.join(","),
                    p.games,
                    json_num(p.self_destruct_rate()), json_num(p.bottom_ko_rate()), s.recovery[i].reach,
                    json_num(p.accuracy()),
                    json_num(p.damage_per_minute()),
                    json_num(p.timeout_rate()),
                    flags.join(","),
                    json_str(&verdict_text(&round.verdicts[i]))
                )
            })
            .collect();
        let matrix: Vec<String> = s.matrix.iter().map(|row| format!("[{}]", row.iter().map(score_json).collect::<Vec<_>>().join(","))).collect();
        rs.push(format!(
            "{{\"seed\":{},\"level\":{},\"stocks\":{},\"games_per_pair\":{},\"stages\":[{}],\"total_games\":{},\"port_bias\":{},\
             \"characters\":[{}],\"matrix\":[{}]}}",
            s.seed,
            s.level,
            s.stocks,
            s.games_per_pair,
            s.stages.iter().map(|st| json_str(st.name())).collect::<Vec<_>>().join(","),
            s.total_games,
            score_json(&s.port_bias),
            characters.join(","),
            matrix.join(",")
        ));
    }
    format!("{{\"best_round\":{},\"rounds\":[{}]}}\n", best_round(rounds), rs.join(","))
}

/// One row per round and matchup cell.
pub fn to_csv(rounds: &[Round]) -> String {
    let mut out = String::from("round,character,opponent,games,wins,draws,losses,win_rate,stderr\n");
    for (r, round) in rounds.iter().enumerate() {
        let s = &round.summary;
        for (i, a) in s.characters.iter().enumerate() {
            for (j, b) in s.characters.iter().enumerate() {
                let c = s.matrix[i][j];
                let _ = writeln!(
                    out,
                    "{r},{},{},{},{},{},{},{:.4},{:.4}",
                    a.name(),
                    b.name(),
                    c.games,
                    c.wins,
                    c.draws,
                    c.losses(),
                    c.rate(),
                    c.stderr()
                );
            }
        }
    }
    out
}
