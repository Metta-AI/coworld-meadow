"""In-process Meadow episodes, no containers or websockets.

The experiment driver and the engine tests run episodes through this module,
so lab results exercise exactly the rules and policies that hosted episodes
use. Timing is the only thing missing: headless rounds settle as soon as every
policy has answered.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    MeadowState,
    new_state,
    observation,
    step,
)
from coworld.examples.meadow.player.policies import Policy, make_policy, policy_decision
from coworld.examples.meadow.shared.decision import PlayerDecision, executed_action
from coworld.examples.meadow.shared.trajectory import Trajectory


def default_player_names(count: int) -> list[str]:
    return [f"P{slot}" for slot in range(count)]


def build_policies(names: list[str], seed: int = 0) -> list[Policy]:
    """One policy per seat; seeded policies get distinct per-slot seeds."""
    return [make_policy(name, seed=seed * 1000 + slot) for slot, name in enumerate(names)]


def run_episode(
    config: MeadowConfig,
    policies: Sequence[Policy],
    player_names: list[str] | None = None,
    parallel_seats: bool = False,
    trajectory: Trajectory | None = None,
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

    def decide(slot: int) -> PlayerDecision:
        obs = observation(state, config, slot, names, round_seconds=60.0)
        return policy_decision(policies[slot], obs)

    slots = range(config.num_players)
    with ThreadPoolExecutor(max_workers=config.num_players) as executor:
        for _ in range(config.rounds):
            views = [observation(state, config, slot, names, round_seconds=60.0) for slot in slots]
            decisions = list(executor.map(decide, slots)) if parallel_seats else [decide(slot) for slot in slots]
            actions = [decision.action for decision in decisions]
            record = step(state, actions, config)
            if trajectory is not None:
                for slot, decision in enumerate(decisions):
                    selected = next((attempt for attempt in decision.attempts
                        if attempt.attempt_id == decision.selected_attempt_id), None)
                    trajectory.record(decision_id=f"round-{record.round}-seat-{slot}", seat=slot,
                        observation=views[slot], prompt=selected.prompt if selected else None,
                        attempts=decision.attempts, executed_action=executed_action(record, slot).model_dump(),
                        fallback_origin=decision.fallback_origin, terminal=state.round == config.rounds)
    if trajectory is not None:
        trajectory.finish(outcome={"scores": [round(score, 3) for score in state.scores],
            "total_harvested": [round(total, 3) for total in state.total_harvested],
            "final_stock": round(state.stock, 3), "collapse_round": state.collapse_round, "rounds": state.round},
            participant_outcomes={str(slot): {"score": round(score, 3)} for slot, score in enumerate(state.scores)},
            completed=state.round == config.rounds)
    return state
