//! Raw scripted-episode throughput benchmark.
use meadow_rs::engine::MeadowConfig;
use meadow_rs::headless::{build_policies, run_episode};

fn main() {
    let n: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(100_000);
    let config = MeadowConfig::default();
    let started = std::time::Instant::now();
    let mut checksum = 0.0f64;
    for seed in 0..n {
        let mut policies = build_policies(&["random"; 8], seed);
        let state = run_episode(&config, &mut policies);
        checksum += state.stock;
    }
    let dt = started.elapsed().as_secs_f64();
    println!("rust: {n} episodes in {dt:.2}s = {:.0} eps/sec (checksum {checksum:.1})", n as f64 / dt);
}
