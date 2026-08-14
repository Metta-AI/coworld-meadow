# meadow-rs

Zero-dependency Rust port of the Meadow simulation core: the rules engine, the
scripted policies, the exact-planner DP, and the scripted experiment suite.
`std` only — no serde, no tokio, no crates at all.

**Parity is the contract.** The suite output is byte-identical to the Python
implementation's committed `experiments/results/scripted_runs.jsonl` — every
float, every stochastic episode, every JSON separator. That takes three pieces
of deliberate compatibility, all tested:

- `mt19937.rs` — CPython's `random.Random` (MT19937 with `init_by_array`
  seeding and the `getrandbits` rejection-sampling `randint`), bit-for-bit.
- `pyfmt.rs` — CPython's `round(x, n)` (correctly-rounded decimal, ties to
  even) and `repr(float)` (shortest round-trip, integral floats keep `.0`).
- `json.rs` — `json.dumps` default formatting.

What stays in Python, on purpose: the LLM seat and experiment runner (episode
wall-clock is Bedrock inference latency — a Rust rewrite would not move it),
the websocket game server in the certified container, and `analyze.py`
(matplotlib).

## Use

```bash
cargo test --release                                   # parity + unit tests
cargo run --release --bin scripted_experiments out.jsonl
cargo run --release --bin bench 100000                 # episode throughput
```

Measured on an M-series laptop: the 63-episode calibration suite runs in
~13ms vs ~1.8s for Python (~135x), and raw scripted-episode throughput is
~10,500 episodes/sec vs ~200/sec (~53x single-threaded; seeds shard across
cores with `std::thread` for more).

Verify parity against the committed Python output any time:

```bash
cargo run --release --bin scripted_experiments /tmp/rust.jsonl
diff /tmp/rust.jsonl ../experiments/results/scripted_runs.jsonl && echo identical
```
