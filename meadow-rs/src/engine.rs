//! Meadow rules engine — a line-for-line port of the Python engine
//! (`game/engine.py`). Same f64 arithmetic in the same order, so states and
//! scores match the Python implementation bit-for-bit.

#[derive(Clone, Debug)]
pub struct MeadowConfig {
    pub num_players: usize,
    pub rounds: usize,
    pub stock_start: f64,
    pub stock_capacity: f64,
    pub regrowth_rate: f64,
    pub collapse_threshold: f64,
    pub max_harvest: u32,
    pub ledger_public: bool,
    pub sanctions_enabled: bool,
    pub sanction_cost: f64,
    pub sanction_burn: f64,
    pub chat_enabled: bool,
    pub chat_max_chars: usize,
    pub norm_text: String,
}

impl Default for MeadowConfig {
    fn default() -> Self {
        MeadowConfig {
            num_players: 8,
            rounds: 60,
            stock_start: 60.0,
            stock_capacity: 100.0,
            regrowth_rate: 0.35,
            collapse_threshold: 10.0,
            max_harvest: 3,
            ledger_public: true,
            sanctions_enabled: false,
            sanction_cost: 1.0,
            sanction_burn: 3.0,
            chat_enabled: true,
            chat_max_chars: 140,
            norm_text: String::new(),
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct RoundAction {
    pub harvest: u32,
    pub sanction: Option<usize>,
}

#[derive(Clone, Debug)]
pub struct SanctionRecord {
    pub by: usize,
    pub target: usize,
}

#[derive(Clone, Debug)]
pub struct RoundRecord {
    pub round: usize,
    pub stock_before: f64,
    pub demands: Vec<u32>,
    pub harvests: Vec<f64>,
    pub stock_after_harvest: f64,
    pub stock_after_regrowth: f64,
    pub sanctions: Vec<SanctionRecord>,
    pub scores: Vec<f64>,
    pub collapsed: bool,
}

#[derive(Clone, Debug)]
pub struct MeadowState {
    pub stock: f64,
    pub round: usize,
    pub collapsed: bool,
    pub collapse_round: Option<usize>,
    pub scores: Vec<f64>,
    pub total_harvested: Vec<f64>,
    pub sanctions_given: Vec<u32>,
    pub sanctions_received: Vec<u32>,
    pub history: Vec<RoundRecord>,
}

pub fn new_state(config: &MeadowConfig) -> MeadowState {
    let n = config.num_players;
    let collapsed = config.stock_start < config.collapse_threshold;
    MeadowState {
        stock: config.stock_start,
        round: 0,
        collapsed,
        collapse_round: if collapsed { Some(0) } else { None },
        scores: vec![0.0; n],
        total_harvested: vec![0.0; n],
        sanctions_given: vec![0; n],
        sanctions_received: vec![0; n],
        history: Vec::new(),
    }
}

pub fn regrow(stock: f64, config: &MeadowConfig) -> f64 {
    let grown = stock + config.regrowth_rate * stock * (1.0 - stock / config.stock_capacity);
    grown.min(config.stock_capacity)
}

pub fn step<'a>(state: &'a mut MeadowState, actions: &[RoundAction], config: &MeadowConfig) -> &'a RoundRecord {
    assert_eq!(actions.len(), config.num_players, "one action per player");

    let stock_before = state.stock;
    let demands: Vec<u32> = actions.iter().map(|a| a.harvest).collect();
    let demand_total: u32 = demands.iter().sum();
    let harvests: Vec<f64> = if f64::from(demand_total) <= state.stock {
        demands.iter().map(|&d| f64::from(d)).collect()
    } else {
        let scale = state.stock / f64::from(demand_total);
        demands.iter().map(|&d| f64::from(d) * scale).collect()
    };
    let harvest_total: f64 = harvests.iter().sum();
    state.stock = (state.stock - harvest_total).max(0.0);
    let stock_after_harvest = state.stock;

    let mut sanctions = Vec::new();
    if config.sanctions_enabled {
        for (slot, action) in actions.iter().enumerate() {
            if let Some(target) = action.sanction {
                sanctions.push(SanctionRecord { by: slot, target });
                state.scores[slot] -= config.sanction_cost;
                state.scores[target] -= config.sanction_burn;
                state.sanctions_given[slot] += 1;
                state.sanctions_received[target] += 1;
            }
        }
    }

    for (slot, &harvest) in harvests.iter().enumerate() {
        state.scores[slot] += harvest;
        state.total_harvested[slot] += harvest;
    }

    if !state.collapsed && state.stock < config.collapse_threshold {
        state.collapsed = true;
        state.collapse_round = Some(state.round);
    }
    if !state.collapsed {
        state.stock = regrow(state.stock, config);
    }

    let record = RoundRecord {
        round: state.round,
        stock_before,
        demands,
        harvests,
        stock_after_harvest,
        stock_after_regrowth: state.stock,
        sanctions,
        scores: state.scores.clone(),
        collapsed: state.collapsed,
    };
    state.history.push(record);
    state.round += 1;
    state.history.last().expect("just pushed")
}

pub fn welfare(state: &MeadowState) -> f64 {
    state.scores.iter().sum::<f64>() + state.stock
}
