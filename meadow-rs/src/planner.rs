//! Exact planner optimum by dynamic programming — a port of
//! `engine.social_optimum` (numpy expressed as loops). Grid, interpolation,
//! and first-max argmax semantics match numpy's.

use crate::engine::MeadowConfig;

const STEP: f64 = 0.05;

fn interp(grid: &[f64], values: &[f64], x: f64) -> f64 {
    let last = grid.len() - 1;
    if x <= grid[0] {
        return values[0];
    }
    if x >= grid[last] {
        return values[last];
    }
    // grid is uniform i*STEP; find j with grid[j] <= x < grid[j+1]
    let mut j = (x / STEP) as usize;
    if j >= last {
        j = last - 1;
    }
    while grid[j] > x {
        j -= 1;
    }
    while grid[j + 1] <= x {
        j += 1;
    }
    let slope = (values[j + 1] - values[j]) / (grid[j + 1] - grid[j]);
    slope * (x - grid[j]) + values[j]
}

pub fn social_optimum(config: &MeadowConfig) -> (f64, Vec<u32>) {
    let n_points = ((config.stock_capacity + STEP) / STEP).ceil() as usize;
    let grid: Vec<f64> = (0..n_points).map(|i| i as f64 * STEP).collect();
    let max_demand = config.num_players as u32 * config.max_harvest;

    let mut value: Vec<f64> = grid.clone();
    let mut best_demand: Vec<Vec<u32>> = vec![vec![0; grid.len()]; config.rounds];

    for round_index in (0..config.rounds).rev() {
        let mut next_value = vec![f64::NEG_INFINITY; grid.len()];
        for (gi, &stock) in grid.iter().enumerate() {
            let mut best = f64::NEG_INFINITY;
            let mut best_d = 0u32;
            for demand in 0..=max_demand {
                let harvest = f64::from(demand).min(stock);
                let remaining = stock - harvest;
                let live = remaining >= config.collapse_threshold;
                let future = if live {
                    let regrown = (remaining
                        + config.regrowth_rate * remaining * (1.0 - remaining / config.stock_capacity))
                        .min(config.stock_capacity);
                    interp(&grid, &value, regrown)
                } else {
                    remaining
                };
                let total = harvest + future;
                if total > best {
                    best = total;
                    best_d = demand;
                }
            }
            next_value[gi] = best;
            best_demand[round_index][gi] = best_d;
        }
        value = next_value;
    }

    let mut schedule = Vec::with_capacity(config.rounds);
    let mut stock = config.stock_start;
    for round_index in 0..config.rounds {
        // Python's round() is ties-to-even, unlike Rust's default round().
        let mut index = (stock / STEP).round_ties_even() as isize;
        index = index.clamp(0, grid.len() as isize - 1);
        let demand = best_demand[round_index][index as usize];
        schedule.push(demand);
        let harvest = f64::from(demand).min(stock);
        stock -= harvest;
        if stock >= config.collapse_threshold {
            stock = (stock + config.regrowth_rate * stock * (1.0 - stock / config.stock_capacity))
                .min(config.stock_capacity);
        }
    }
    let optimum = interp(&grid, &value, config.stock_start);
    (optimum, schedule)
}
