//! Rust analog of `experiments/run_scripted_experiments.py`: writes the same
//! JSONL rows. Usage: `cargo run --release --bin scripted_experiments [out.jsonl]`

use meadow_rs::scripted::run_suite;

fn main() {
    let out_path = std::env::args().nth(1).unwrap_or_else(|| "scripted_runs.jsonl".into());
    let started = std::time::Instant::now();
    let (rows, optimum, schedule) = run_suite();
    let elapsed = started.elapsed();
    println!(
        "planner optimum (default config): {optimum:.1}, first 10 aggregate demands: {schedule:?}"
    );
    let body: String = rows.iter().map(|row| row.dumps() + "\n").collect();
    std::fs::write(&out_path, body).expect("write output");
    println!("wrote {} episode rows to {out_path} in {elapsed:.2?}", rows.len());
}
