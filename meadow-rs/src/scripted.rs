//! The scripted-experiment suite — a port of `run_scripted_experiments.py`
//! producing JSONL rows that match the Python output.

use crate::engine::{welfare, MeadowConfig, MeadowState};
use crate::headless::{build_policies, run_episode};
use crate::json::Json;
use crate::planner::social_optimum;
use crate::pyfmt::py_round;

pub const STOCHASTIC_SEEDS: u64 = 30;

fn synchrony_same_action_rate(state: &MeadowState) -> f64 {
    let n = state.scores.len();
    let n_pairs = n * (n - 1) / 2;
    let mut matches = 0usize;
    for record in &state.history {
        for left in 0..n {
            for right in (left + 1)..n {
                if record.demands[left] == record.demands[right] {
                    matches += 1;
                }
            }
        }
    }
    matches as f64 / (state.history.len() * n_pairs) as f64
}

fn harvest_gini(totals: &[f64]) -> Option<f64> {
    if totals.iter().sum::<f64>() == 0.0 {
        return None;
    }
    let mut values = totals.to_vec();
    values.sort_by(|a, b| a.partial_cmp(b).expect("finite totals"));
    let n = values.len();
    let numerator: f64 = values
        .iter()
        .enumerate()
        .map(|(i, &v)| ((2 * (i + 1)) as i64 - n as i64 - 1) as f64 * v)
        .sum();
    let denominator = n as f64 * values.iter().sum::<f64>();
    Some(numerator / denominator)
}

fn config_json(config: &MeadowConfig) -> Json {
    Json::Object(vec![
        ("num_players".into(), Json::Int(config.num_players as i64)),
        ("rounds".into(), Json::Int(config.rounds as i64)),
        ("stock_start".into(), Json::Float(config.stock_start)),
        ("stock_capacity".into(), Json::Float(config.stock_capacity)),
        ("regrowth_rate".into(), Json::Float(config.regrowth_rate)),
        ("collapse_threshold".into(), Json::Float(config.collapse_threshold)),
        ("max_harvest".into(), Json::Int(config.max_harvest as i64)),
        ("ledger_public".into(), Json::Bool(config.ledger_public)),
        ("sanctions_enabled".into(), Json::Bool(config.sanctions_enabled)),
        ("sanction_cost".into(), Json::Float(config.sanction_cost)),
        ("sanction_burn".into(), Json::Float(config.sanction_burn)),
        ("chat_enabled".into(), Json::Bool(config.chat_enabled)),
        ("chat_max_chars".into(), Json::Int(config.chat_max_chars as i64)),
        ("norm_text".into(), Json::Str(config.norm_text.clone())),
    ])
}

pub fn episode_row(
    experiment: &str,
    condition: &str,
    config: &MeadowConfig,
    population: &[&str],
    seed: u64,
    optimum: f64,
) -> Json {
    let mut policies = build_policies(population, seed);
    let state = run_episode(config, &mut policies);
    let gini = harvest_gini(&state.total_harvested);
    Json::Object(vec![
        ("experiment".into(), Json::Str(experiment.into())),
        ("condition".into(), Json::Str(condition.into())),
        (
            "population".into(),
            Json::Array(population.iter().map(|p| Json::Str((*p).into())).collect()),
        ),
        ("seed".into(), Json::Int(seed as i64)),
        ("config".into(), config_json(config)),
        ("welfare".into(), Json::Float(py_round(welfare(&state), 3))),
        ("welfare_pct_optimum".into(), Json::Float(py_round(welfare(&state) / optimum, 4))),
        ("optimum".into(), Json::Float(py_round(optimum, 3))),
        ("survived".into(), Json::Bool(state.collapse_round.is_none())),
        (
            "collapse_round".into(),
            state.collapse_round.map_or(Json::Null, |r| Json::Int(r as i64)),
        ),
        ("final_stock".into(), Json::Float(py_round(state.stock, 3))),
        (
            "scores".into(),
            Json::Array(state.scores.iter().map(|&s| Json::Float(py_round(s, 2))).collect()),
        ),
        (
            "total_harvested".into(),
            Json::Array(state.total_harvested.iter().map(|&t| Json::Float(py_round(t, 2))).collect()),
        ),
        (
            "sanctions_total".into(),
            Json::Int(state.sanctions_given.iter().map(|&g| g as i64).sum()),
        ),
        (
            "synchrony_same_action_rate".into(),
            Json::Float(py_round(synchrony_same_action_rate(&state), 4)),
        ),
        (
            "harvest_gini".into(),
            gini.map_or(Json::Null, |g| Json::Float(py_round(g, 4))),
        ),
    ])
}

/// Run the full calibration suite; returns (rows, optimum, first-10 schedule).
pub fn run_suite() -> (Vec<Json>, f64, Vec<u32>) {
    let default_config = MeadowConfig::default();
    let (optimum, schedule) = social_optimum(&default_config);
    let mut rows = Vec::new();

    // A. Greedy gradient.
    for greedy_count in 0..=8usize {
        let population: Vec<&str> = std::iter::repeat_n("greedy", greedy_count)
            .chain(std::iter::repeat_n("sustainable", 8 - greedy_count))
            .collect();
        rows.push(episode_row(
            "greedy_gradient",
            &format!("greedy={greedy_count}"),
            &default_config,
            &population,
            0,
            optimum,
        ));
    }

    // B. Trigger dynamics.
    for greedy_count in 0..=8usize {
        let population: Vec<&str> = std::iter::repeat_n("greedy", greedy_count)
            .chain(std::iter::repeat_n("reciprocator", 8 - greedy_count))
            .collect();
        rows.push(episode_row(
            "trigger_dynamics",
            &format!("greedy={greedy_count}"),
            &default_config,
            &population,
            0,
            optimum,
        ));
    }

    // C. Random variance.
    for seed in 0..STOCHASTIC_SEEDS {
        rows.push(episode_row(
            "random_population",
            "8xrandom",
            &default_config,
            &["random"; 8],
            seed,
            optimum,
        ));
    }

    // D. Institution grid.
    for ledger_public in [false, true] {
        for sanctions_enabled in [false, true] {
            let config = MeadowConfig { ledger_public, sanctions_enabled, ..MeadowConfig::default() };
            let condition = format!(
                "ledger={},sanctions={}",
                if ledger_public { "on" } else { "off" },
                if sanctions_enabled { "on" } else { "off" }
            );
            let population = ["deterrable", "deterrable", "deterrable", "deterrable", "enforcer", "enforcer", "enforcer", "enforcer"];
            rows.push(episode_row("institution_grid", &condition, &config, &population, 0, optimum));
        }
    }

    // E. Minimum viable police force.
    let institutions = MeadowConfig { ledger_public: true, sanctions_enabled: true, ..MeadowConfig::default() };
    for enforcer_count in 0..=8usize {
        let population: Vec<&str> = std::iter::repeat_n("deterrable", 8 - enforcer_count)
            .chain(std::iter::repeat_n("enforcer", enforcer_count))
            .collect();
        rows.push(episode_row(
            "police_force",
            &format!("enforcers={enforcer_count}"),
            &institutions,
            &population,
            0,
            optimum,
        ));
    }

    // F. Reference rows.
    rows.push(episode_row("reference", "8xsustainable", &default_config, &["sustainable"; 8], 0, optimum));
    rows.push(episode_row("reference", "8xgreedy", &default_config, &["greedy"; 8], 0, optimum));

    (rows, optimum, schedule.into_iter().take(10).collect())
}
