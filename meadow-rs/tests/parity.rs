//! Golden parity checks against values computed by the Python implementation
//! (committed in `experiments/results/scripted_runs.jsonl`). The full-file
//! comparison lives in `experiments/compare_scripted.py`; these tests pin the
//! headline numbers so `cargo test` alone catches drift.

use meadow_rs::engine::MeadowConfig;
use meadow_rs::planner::social_optimum;
use meadow_rs::scripted::run_suite;

#[test]
fn planner_optimum_matches_python() {
    let (optimum, schedule) = social_optimum(&MeadowConfig::default());
    assert!((optimum - 584.9807091662144).abs() < 1e-9, "optimum {optimum}");
    assert_eq!(schedule[..10], [10, 9, 8, 9, 9, 9, 8, 9, 9, 9]);
}

#[test]
fn suite_shape_and_reference_rows() {
    let (rows, _, _) = run_suite();
    assert_eq!(rows.len(), 63);
    let dump_last = rows[62].dumps();
    // 8xgreedy reference: welfare 73.677, 12.6% of optimum, collapse round 2.
    assert!(dump_last.contains("\"condition\": \"8xgreedy\""), "{dump_last}");
    assert!(dump_last.contains("\"welfare\": 73.677"), "{dump_last}");
    assert!(dump_last.contains("\"welfare_pct_optimum\": 0.1259"), "{dump_last}");
    assert!(dump_last.contains("\"collapse_round\": 2"), "{dump_last}");
    let dump_sustainable = rows[61].dumps();
    assert!(dump_sustainable.contains("\"welfare_pct_optimum\": 0.9447"), "{dump_sustainable}");
    assert!(dump_sustainable.contains("\"survived\": true"), "{dump_sustainable}");
}
