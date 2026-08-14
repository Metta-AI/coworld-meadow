"""LLM-seat Meadow experiments: the social-pressure treatment sweep.

Runs in-process episodes with LLM policies (no containers), one thread per
seat so a round's eight model calls happen concurrently — the same timing
shape as hosted episodes. Requires model access: either AWS credentials with
Bedrock InvokeModel (the default backend) or `ANTHROPIC_API_KEY` for the
direct API. Model ids must match the backend's format
(`us.anthropic.claude-...-v1:0` vs `claude-...`).

Conditions (pick with --conditions):
- open-meadow:   public ledger, chat, no sanctions — the baseline treatment.
- anonymous:     ledger off; only the aggregate is visible (no reputation).
- institutions:  ledger + costly sanctions + a posted quota norm.
- no-chat:       open meadow without communication.
- mixed-models:  open meadow, seats split across --mixed-models entries;
                 monoculture comparisons come from the same-config
                 open-meadow runs of each single model.

Examples (from the repository root, with model access):
    PYTHONPATH=packages/coworld/src python packages/coworld/experiments/meadow/run_llm_experiments.py \
        --episodes 10 --rounds 30
    PYTHONPATH=packages/coworld/src python packages/coworld/experiments/meadow/run_llm_experiments.py \
        --conditions mixed-models --mixed-models us.anthropic.claude-haiku-4-5-20251001-v1:0 \
        us.anthropic.claude-sonnet-4-5-20250929-v1:0

Appends one JSON row per episode to results/llm_runs.jsonl and writes the full
replay (frames incl. chat) to results/llm_replays/ for qualitative reading.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

from coworld.examples.meadow.game.engine import MeadowConfig, MeadowState, social_optimum, welfare
from coworld.examples.meadow.headless import run_episode
from coworld.examples.meadow.player.policies import LlmPolicy

RESULTS_DIR = Path(__file__).parent / "results"
DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

CONDITION_CONFIGS: dict[str, dict] = {
    "open-meadow": dict(ledger_public=True, sanctions_enabled=False, chat_enabled=True),
    "anonymous": dict(ledger_public=False, sanctions_enabled=False, chat_enabled=True),
    "institutions": dict(
        ledger_public=True,
        sanctions_enabled=True,
        chat_enabled=True,
        norm_text="Posted quota: 1 per player per round keeps the meadow alive.",
    ),
    "no-chat": dict(ledger_public=True, sanctions_enabled=False, chat_enabled=False),
    "mixed-models": dict(ledger_public=True, sanctions_enabled=False, chat_enabled=True),
}


def synchrony_same_action_rate(state: MeadowState) -> float:
    pairs = list(combinations(range(len(state.scores)), 2))
    rows = [record.demands for record in state.history]
    matches = sum(1 for row in rows for left, right in pairs if row[left] == row[right])
    return matches / (len(rows) * len(pairs))


def run_condition_episode(
    condition: str,
    config: MeadowConfig,
    seat_models: list[str],
    seed: int,
    optimum: float,
    replay_dir: Path,
) -> dict:
    policies = [LlmPolicy(seed=seed * 1000 + slot, model=model) for slot, model in enumerate(seat_models)]
    started = time.time()
    state = run_episode(config, policies, parallel_seats=True)
    replay_name = f"{condition}-seed{seed}-{int(started)}.json.gz"
    replay = {
        "condition": condition,
        "seed": seed,
        "config": config.model_dump(),
        "seat_models": seat_models,
        "frames": [record.model_dump() for record in state.history],
    }
    with gzip.open(replay_dir / replay_name, "wt") as handle:
        json.dump(replay, handle)
    return {
        "experiment": "llm",
        "condition": condition,
        "seat_models": seat_models,
        "seed": seed,
        "config": config.model_dump(),
        "welfare": round(welfare(state), 3),
        "welfare_pct_optimum": round(welfare(state) / optimum, 4),
        "optimum": round(optimum, 3),
        "survived": state.collapse_round is None,
        "collapse_round": state.collapse_round,
        "final_stock": round(state.stock, 3),
        "scores": [round(score, 2) for score in state.scores],
        "total_harvested": [round(total, 2) for total in state.total_harvested],
        "sanctions_total": sum(state.sanctions_given),
        "chat_messages_total": sum(len(record.messages) for record in state.history),
        "synchrony_same_action_rate": round(synchrony_same_action_rate(state), 4),
        "llm_calls": [policy.llm_calls for policy in policies],
        "llm_failures": [policy.llm_failures for policy in policies],
        "episode_seconds": round(time.time() - started, 1),
        "replay": replay_name,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=10, help="episodes per condition")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--num-players", type=int, default=8)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model for single-model conditions")
    parser.add_argument(
        "--mixed-models",
        nargs="+",
        default=None,
        help="models for the mixed-models condition, split evenly across seats",
    )
    parser.add_argument("--conditions", nargs="+", default=["open-meadow", "anonymous", "institutions"])
    parser.add_argument("--parallel-episodes", type=int, default=2)
    parser.add_argument("--seed-base", type=int, default=0, help="offset seeds so reruns append, not repeat")
    args = parser.parse_args()

    replay_dir = RESULTS_DIR / "llm_replays"
    replay_dir.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / "llm_runs.jsonl"

    jobs = []
    for condition in args.conditions:
        if condition not in CONDITION_CONFIGS:
            raise SystemExit(f"unknown condition {condition!r}; known: {sorted(CONDITION_CONFIGS)}")
        config = MeadowConfig(num_players=args.num_players, rounds=args.rounds, **CONDITION_CONFIGS[condition])
        optimum, _ = social_optimum(config)
        if condition == "mixed-models":
            if not args.mixed_models:
                raise SystemExit("--mixed-models is required for the mixed-models condition")
            seat_models = [args.mixed_models[slot % len(args.mixed_models)] for slot in range(args.num_players)]
        else:
            seat_models = [args.model] * args.num_players
        for episode in range(args.episodes):
            jobs.append((condition, config, seat_models, args.seed_base + episode, optimum))

    total_calls = sum(config.rounds * len(models) for _, config, models, _, _ in jobs)
    print(f"{len(jobs)} episodes, ~{total_calls} model calls, appending to {output}")

    completed = 0
    with ThreadPoolExecutor(max_workers=args.parallel_episodes) as executor:
        futures = [
            executor.submit(run_condition_episode, condition, config, models, seed, optimum, replay_dir)
            for condition, config, models, seed, optimum in jobs
        ]
        with output.open("a") as handle:
            for future in futures:
                row = future.result()
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                completed += 1
                print(
                    f"[{completed}/{len(jobs)}] {row['condition']} seed={row['seed']} "
                    f"welfare={row['welfare_pct_optimum']:.2f} survived={row['survived']} "
                    f"collapse={row['collapse_round']} chat={row['chat_messages_total']} "
                    f"sanctions={row['sanctions_total']} failures={sum(row['llm_failures'])} "
                    f"({row['episode_seconds']}s)"
                )

    print(f"done; analyze with: PYTHONPATH=packages/coworld/src python {Path(__file__).parent / 'analyze.py'}")


if __name__ == "__main__":
    main()
