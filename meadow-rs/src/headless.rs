//! In-process episodes over scripted policies — the Rust analog of
//! `headless.py` for the scripted (non-LLM) path.

use crate::engine::{new_state, step, MeadowConfig, MeadowState, RoundAction};
use crate::policies::{make_policy, Obs, Policy};
use crate::pyfmt::py_round;

pub fn build_policies(names: &[&str], seed: u64) -> Vec<Policy> {
    names
        .iter()
        .enumerate()
        .map(|(slot, name)| make_policy(name, seed * 1000 + slot as u64))
        .collect()
}

pub fn run_episode(config: &MeadowConfig, policies: &mut [Policy]) -> MeadowState {
    assert_eq!(policies.len(), config.num_players, "one policy per seat");
    let mut state = new_state(config);
    for _ in 0..config.rounds {
        // Round-invariant observation fields, rounded once (matching the
        // per-slot rounding Python applies in engine.observation).
        let stock = py_round(state.stock, 2);
        let last = state.history.last();
        let last_harvests_rounded: Option<Vec<f64>> =
            last.map(|record| record.harvests.iter().map(|&h| py_round(h, 2)).collect());
        let last_total = last.map(|record| py_round(record.harvests.iter().sum(), 2));

        let mut actions = Vec::with_capacity(config.num_players);
        for slot in 0..config.num_players {
            let obs = Obs {
                slot,
                stock,
                max_harvest: config.max_harvest,
                num_players: config.num_players,
                sanctions_enabled: config.sanctions_enabled,
                sanctions_received_last_round: last
                    .map(|record| record.sanctions.iter().filter(|s| s.target == slot).count() as u32)
                    .unwrap_or(0),
                your_last_harvest: last_harvests_rounded.as_ref().map(|h| h[slot]),
                last_round_total_harvest: last_total,
                last_round_harvests: if config.ledger_public {
                    last_harvests_rounded.clone()
                } else {
                    None
                },
            };
            let raw = policies[slot].act(&obs);
            // parse_action clamping: scripted policies already emit in-range
            // harvests; sanctions are validated the same way Python does.
            let harvest = raw.harvest.min(config.max_harvest);
            let sanction = if config.sanctions_enabled {
                raw.sanction.filter(|&t| t != slot && t < config.num_players)
            } else {
                None
            };
            actions.push(RoundAction { harvest, sanction });
        }
        step(&mut state, &actions, config);
    }
    state
}
