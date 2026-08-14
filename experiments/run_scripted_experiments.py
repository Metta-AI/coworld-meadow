"""Scripted-seat Meadow experiments: ecology calibration + institution mechanics.

These sweeps validate that the environment is well-posed before LLM seats run:
collapse boundaries exist, treatment dials have mechanical bite, and every
metric has a computed denominator (the exact planner optimum). Populations are
scripted policies, so deterministic conditions run once and stochastic ones run
30 seeds.

Usage:
    PYTHONPATH=packages/coworld/src python packages/coworld/experiments/meadow/run_scripted_experiments.py

Writes JSONL rows to results/scripted_runs.jsonl (one row per episode).
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from coworld.examples.meadow.game.engine import MeadowConfig, MeadowState, social_optimum, welfare
from coworld.examples.meadow.headless import build_policies, run_episode

RESULTS_DIR = Path(__file__).parent / "results"
BASE = dict(num_players=8, rounds=60)
STOCHASTIC_SEEDS = 30


def synchrony_same_action_rate(state: MeadowState) -> float:
    pairs = list(combinations(range(len(state.scores)), 2))
    rows = [record.demands for record in state.history]
    matches = sum(1 for row in rows for left, right in pairs if row[left] == row[right])
    return matches / (len(rows) * len(pairs))


def harvest_gini(totals: list[float]) -> float | None:
    if sum(totals) == 0:
        return None
    values = sorted(totals)
    n = len(values)
    return sum((2 * index - n - 1) * value for index, value in enumerate(values, start=1)) / (n * sum(values))


def episode_row(
    experiment: str,
    condition: str,
    config: MeadowConfig,
    population: list[str],
    seed: int,
    optimum: float,
) -> dict:
    state = run_episode(config, build_policies(population, seed=seed))
    gini = harvest_gini(state.total_harvested)
    return {
        "experiment": experiment,
        "condition": condition,
        "population": population,
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
        "synchrony_same_action_rate": round(synchrony_same_action_rate(state), 4),
        "harvest_gini": None if gini is None else round(gini, 4),
    }


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    rows: list[dict] = []

    default_config = MeadowConfig(**BASE)
    optimum, schedule = social_optimum(default_config)
    print(f"planner optimum (default config): {optimum:.1f}, first 10 aggregate demands: {schedule[:10]}")

    # A. Greedy gradient: how many defectors does the default meadow tolerate?
    for greedy_count in range(9):
        population = ["greedy"] * greedy_count + ["sustainable"] * (8 - greedy_count)
        rows.append(episode_row("greedy_gradient", f"greedy={greedy_count}", default_config, population, 0, optimum))

    # B. Trigger dynamics: reciprocators punish via the aggregate — conformity cascade.
    for greedy_count in range(9):
        population = ["greedy"] * greedy_count + ["reciprocator"] * (8 - greedy_count)
        rows.append(episode_row("trigger_dynamics", f"greedy={greedy_count}", default_config, population, 0, optimum))

    # C. Random variance: the maximum-diversity population, 30 seeds.
    for seed in range(STOCHASTIC_SEEDS):
        rows.append(episode_row("random_population", "8xrandom", default_config, ["random"] * 8, seed, optimum))

    # D. Institution grid: deterrable defectors + enforcers under ledger x sanctions.
    for ledger_public in (False, True):
        for sanctions_enabled in (False, True):
            config = MeadowConfig(**BASE, ledger_public=ledger_public, sanctions_enabled=sanctions_enabled)
            condition = f"ledger={'on' if ledger_public else 'off'},sanctions={'on' if sanctions_enabled else 'off'}"
            population = ["deterrable"] * 4 + ["enforcer"] * 4
            rows.append(episode_row("institution_grid", condition, config, population, 0, optimum))

    # E. Minimum viable police force: enforcer count vs deterrable defectors.
    institutions = MeadowConfig(**BASE, ledger_public=True, sanctions_enabled=True)
    for enforcer_count in range(9):
        population = ["deterrable"] * (8 - enforcer_count) + ["enforcer"] * enforcer_count
        rows.append(episode_row("police_force", f"enforcers={enforcer_count}", institutions, population, 0, optimum))

    # F. Reference rows.
    rows.append(episode_row("reference", "8xsustainable", default_config, ["sustainable"] * 8, 0, optimum))
    rows.append(episode_row("reference", "8xgreedy", default_config, ["greedy"] * 8, 0, optimum))

    output = RESULTS_DIR / "scripted_runs.jsonl"
    output.write_text("".join(json.dumps(row) + "\n" for row in rows))
    print(f"wrote {len(rows)} episode rows to {output}")


if __name__ == "__main__":
    main()
