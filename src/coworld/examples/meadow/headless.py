"""In-process Meadow episodes, no containers or websockets.

The experiment driver and the engine tests run episodes through this module,
so lab results exercise exactly the rules and policies that hosted episodes
use. Timing is the only thing missing: headless rounds settle as soon as every
policy has answered.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    MeadowState,
    new_state,
    observation,
    parse_action,
    step,
)
from coworld.examples.meadow.player.policies import make_policy


def default_player_names(count: int) -> list[str]:
    return [f"P{slot}" for slot in range(count)]


def build_policies(names: list[str], seed: int = 0) -> list[object]:
    """One policy per seat; seeded policies get distinct per-slot seeds."""
    return [make_policy(name, seed=seed * 1000 + slot) for slot, name in enumerate(names)]


def run_episode(
    config: MeadowConfig,
    policies: list[object],
    player_names: list[str] | None = None,
    parallel_seats: bool = False,
) -> MeadowState:
    """Run one full episode; with `parallel_seats`, seats act concurrently.

    Parallel seats matter for LLM policies, where a round is network-bound:
    hosted episodes run every player container concurrently, and the threaded
    round mirrors that timing.
    """
    if len(policies) != config.num_players:
        raise ValueError(f"expected {config.num_players} policies, got {len(policies)}")
    names = player_names or default_player_names(config.num_players)
    state = new_state(config)

    def decide(slot: int) -> object:
        obs = observation(state, config, slot, names, round_seconds=0.0)
        return policies[slot].act(obs)

    slots = range(config.num_players)
    with ThreadPoolExecutor(max_workers=config.num_players) as executor:
        for _ in range(config.rounds):
            raw_actions = list(executor.map(decide, slots)) if parallel_seats else [decide(slot) for slot in slots]
            actions = [parse_action(raw, slot, config) for slot, raw in enumerate(raw_actions)]
            step(state, actions, config)
    return state
