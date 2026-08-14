//! Scripted Meadow policies — ports of `player/policies.py` (LLM seat
//! excluded; that path is network-bound and stays in Python).
//!
//! Policies consume the same observation the Python policies read, including
//! its 2-decimal rounding, so threshold comparisons land identically.

use crate::mt19937::PyRandom;

pub const DEFAULT_QUOTA: u32 = 1;
pub const DEFAULT_STOCK_FLOOR: f64 = 30.0;

/// The observation fields scripted policies read, pre-rounded like
/// `engine.observation` rounds them.
pub struct Obs {
    pub slot: usize,
    pub stock: f64,
    pub max_harvest: u32,
    pub num_players: usize,
    pub sanctions_enabled: bool,
    pub sanctions_received_last_round: u32,
    pub your_last_harvest: Option<f64>,
    pub last_round_total_harvest: Option<f64>,
    /// Present only when the ledger is public, like Python's obs key.
    pub last_round_harvests: Option<Vec<f64>>,
}

pub struct RawAction {
    pub harvest: u32,
    pub sanction: Option<usize>,
}

pub enum Policy {
    Sustainable { quota: u32, stock_floor: f64 },
    Greedy,
    Random { rng: PyRandom },
    Reciprocator { quota: u32, stock_floor: f64 },
    Deterrable { quota: u32, cooldown: u32, contrite_rounds: u32 },
    Enforcer { quota: u32, stock_floor: f64 },
}

impl Policy {
    pub fn act(&mut self, obs: &Obs) -> RawAction {
        match self {
            Policy::Sustainable { quota, stock_floor } => RawAction {
                harvest: if obs.stock >= *stock_floor { *quota } else { 0 },
                sanction: None,
            },
            Policy::Greedy => RawAction { harvest: obs.max_harvest, sanction: None },
            Policy::Random { rng } => RawAction { harvest: rng.randint(0, obs.max_harvest), sanction: None },
            Policy::Reciprocator { quota, stock_floor } => {
                if let Some(total_last) = obs.last_round_total_harvest {
                    let yours = obs.your_last_harvest.unwrap_or(0.0);
                    let others_mean = (total_last - yours) / (obs.num_players - 1) as f64;
                    if others_mean > f64::from(*quota) + 0.5 {
                        return RawAction { harvest: obs.max_harvest, sanction: None };
                    }
                }
                RawAction {
                    harvest: if obs.stock >= *stock_floor { *quota } else { 0 },
                    sanction: None,
                }
            }
            Policy::Deterrable { quota, cooldown, contrite_rounds } => {
                if obs.sanctions_received_last_round > 0 {
                    *contrite_rounds = *cooldown;
                }
                if *contrite_rounds > 0 {
                    *contrite_rounds -= 1;
                    return RawAction { harvest: *quota, sanction: None };
                }
                RawAction { harvest: obs.max_harvest, sanction: None }
            }
            Policy::Enforcer { quota, stock_floor } => {
                let mut action = RawAction {
                    harvest: if obs.stock >= *stock_floor { *quota } else { 0 },
                    sanction: None,
                };
                if obs.sanctions_enabled {
                    if let Some(last_harvests) = &obs.last_round_harvests {
                        if !last_harvests.is_empty() {
                            // Worst offender: max harvest, ties to the lowest slot,
                            // matching Python's max(key=(harvest, -slot)).
                            let mut worst: Option<(f64, usize)> = None;
                            for (slot, &harvest) in last_harvests.iter().enumerate() {
                                if slot != obs.slot && harvest > f64::from(*quota) {
                                    let better = match worst {
                                        None => true,
                                        Some((wh, ws)) => harvest > wh || (harvest == wh && slot < ws),
                                    };
                                    if better {
                                        worst = Some((harvest, slot));
                                    }
                                }
                            }
                            if let Some((_, slot)) = worst {
                                action.sanction = Some(slot);
                            }
                        }
                    }
                }
                action
            }
        }
    }
}

pub fn make_policy(name: &str, seed: u64) -> Policy {
    match name {
        "sustainable" => Policy::Sustainable { quota: DEFAULT_QUOTA, stock_floor: DEFAULT_STOCK_FLOOR },
        "greedy" => Policy::Greedy,
        "random" => Policy::Random { rng: PyRandom::new(seed) },
        "reciprocator" => Policy::Reciprocator { quota: DEFAULT_QUOTA, stock_floor: DEFAULT_STOCK_FLOOR },
        "deterrable" => Policy::Deterrable { quota: DEFAULT_QUOTA, cooldown: 5, contrite_rounds: 0 },
        "enforcer" => Policy::Enforcer { quota: DEFAULT_QUOTA, stock_floor: DEFAULT_STOCK_FLOOR },
        other => panic!("unknown policy: {other}"),
    }
}
