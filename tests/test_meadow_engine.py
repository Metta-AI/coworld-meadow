from __future__ import annotations

import pytest

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    RoundAction,
    new_state,
    observation,
    parse_action,
    social_optimum,
    step,
    welfare,
)
from coworld.examples.meadow.headless import build_policies, default_player_names, run_episode
from coworld.examples.meadow.player.policies import EnforcerPolicy, LlmPolicy, make_policy


def config(**overrides) -> MeadowConfig:
    return MeadowConfig(num_players=8, **overrides)


def test_step_conserves_stock_and_scores() -> None:
    cfg = config()
    state = new_state(cfg)
    record = step(state, [RoundAction(harvest=2)] * 8, cfg)
    assert record.stock_before == pytest.approx(60.0)
    assert sum(record.harvests) == pytest.approx(16.0)
    assert record.stock_after_harvest == pytest.approx(60.0 - 16.0)
    assert state.scores == [pytest.approx(2.0)] * 8
    # logistic regrowth applied to the post-harvest stock
    assert record.stock_after_regrowth == pytest.approx(44.0 + 0.35 * 44.0 * (1 - 44.0 / 100.0))


def test_over_demand_splits_pro_rata_and_collapse_latches() -> None:
    cfg = config(stock_start=12.0)
    state = new_state(cfg)
    record = step(state, [RoundAction(harvest=3)] * 8, cfg)  # demand 24 > stock 12
    assert record.harvests == [pytest.approx(1.5)] * 8
    assert state.stock == pytest.approx(0.0)
    assert state.collapsed and state.collapse_round == 0
    # dead meadows never regrow
    step(state, [RoundAction(harvest=0)] * 8, cfg)
    assert state.stock == pytest.approx(0.0)
    assert state.collapse_round == 0


def test_sanctions_apply_cost_and_burn() -> None:
    cfg = config(sanctions_enabled=True)
    state = new_state(cfg)
    actions = [RoundAction(harvest=0, sanction=3)] + [RoundAction(harvest=0)] * 7
    record = step(state, actions, cfg)
    assert state.scores[0] == pytest.approx(-1.0)
    assert state.scores[3] == pytest.approx(-3.0)
    assert state.sanctions_given[0] == 1 and state.sanctions_received[3] == 1
    assert record.sanctions[0].by == 0 and record.sanctions[0].target == 3
    # punishment is welfare-negative: cost + burn are destroyed
    assert welfare(state) == pytest.approx(cfg.stock_start + 0.35 * 60 * (1 - 0.6) - 4.0)


def test_parse_action_degrades_invalid_input_to_a_pass() -> None:
    cfg = config(sanctions_enabled=True)
    assert parse_action("not a dict", 0, cfg) == RoundAction()
    assert parse_action({"harvest": "three"}, 0, cfg).harvest == 0
    assert parse_action({"harvest": True}, 0, cfg).harvest == 0
    assert parse_action({"harvest": 99}, 0, cfg).harvest == cfg.max_harvest
    assert parse_action({"harvest": -2}, 0, cfg).harvest == 0
    assert parse_action({"harvest": 1, "sanction": 0}, 0, cfg).sanction is None  # no self-sanction
    assert parse_action({"harvest": 1, "sanction": 2}, 0, cfg).sanction == 2
    long_message = "x" * 500
    assert len(parse_action({"harvest": 1, "message": long_message}, 0, cfg).message) == cfg.chat_max_chars

    quiet = config(chat_enabled=False)
    assert parse_action({"harvest": 1, "message": "hello"}, 0, quiet).message is None
    unarmed = config(sanctions_enabled=False)
    assert parse_action({"harvest": 1, "sanction": 2}, 0, unarmed).sanction is None


def test_anonymous_treatment_hides_the_ledger() -> None:
    cfg = config(ledger_public=False)
    state = new_state(cfg)
    step(state, [RoundAction(harvest=1)] * 8, cfg)
    obs = observation(state, cfg, 0, default_player_names(8), round_seconds=10.0)
    assert "ledger" not in obs and "last_round_harvests" not in obs
    assert obs["last_round_total_harvest"] == pytest.approx(8.0)  # aggregate stays visible

    public = config()
    state = new_state(public)
    step(state, [RoundAction(harvest=1)] * 8, public)
    obs = observation(state, public, 0, default_player_names(8), round_seconds=10.0)
    assert [entry["total_harvested"] for entry in obs["ledger"]] == [pytest.approx(1.0)] * 8
    assert obs["last_round_harvests"] == [pytest.approx(1.0)] * 8


def test_sustainable_population_survives_and_greedy_collapses() -> None:
    cfg = config()
    sustainable = run_episode(cfg, build_policies(["sustainable"] * 8))
    assert not sustainable.collapsed
    assert sustainable.stock > cfg.collapse_threshold

    greedy = run_episode(cfg, build_policies(["greedy"] * 8))
    assert greedy.collapsed
    assert greedy.collapse_round is not None and greedy.collapse_round < 5
    assert welfare(sustainable) > welfare(greedy)


def test_social_optimum_bounds_every_population() -> None:
    cfg = config()
    optimum, schedule = social_optimum(cfg)
    assert len(schedule) == cfg.rounds
    assert optimum > 400  # sustained regrowth dwarfs the standing stock
    for names in (["greedy"] * 8, ["sustainable"] * 8, ["reciprocator"] * 8, ["random"] * 8):
        state = run_episode(cfg, build_policies(names, seed=7))
        assert welfare(state) <= optimum + 1e-6, names


def test_episodes_are_deterministic_given_seeds() -> None:
    cfg = config(rounds=20)
    first = run_episode(cfg, build_policies(["random"] * 8, seed=11))
    second = run_episode(cfg, build_policies(["random"] * 8, seed=11))
    assert first.history == second.history
    third = run_episode(cfg, build_policies(["random"] * 8, seed=12))
    assert first.history != third.history


def test_enforcer_targets_the_worst_offender_only_with_ledger() -> None:
    cfg = config(sanctions_enabled=True)
    state = new_state(cfg)
    demands = [3, 2, 1, 1, 1, 1, 1, 1]
    step(state, [RoundAction(harvest=demand) for demand in demands], cfg)
    obs = observation(state, cfg, 7, default_player_names(8), round_seconds=10.0)
    assert EnforcerPolicy().act(obs)["sanction"] == 0

    hidden = config(sanctions_enabled=True, ledger_public=False)
    state = new_state(hidden)
    step(state, [RoundAction(harvest=demand) for demand in demands], hidden)
    obs = observation(state, hidden, 7, default_player_names(8), round_seconds=10.0)
    assert "sanction" not in EnforcerPolicy().act(obs)


def test_deterrable_greedy_responds_to_sanctions() -> None:
    policy = make_policy("deterrable")
    base_obs = {"max_harvest": 3, "sanctions_received_last_round": 0}
    assert policy.act(base_obs)["harvest"] == 3
    assert policy.act({**base_obs, "sanctions_received_last_round": 1})["harvest"] == 1
    assert policy.act(base_obs)["harvest"] == 1  # still contrite
    for _ in range(4):
        policy.act(base_obs)
    assert policy.act(base_obs)["harvest"] == 3  # cooldown expired


def test_llm_policy_parses_replies_and_builds_prompt(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", raising=False)
    policy = LlmPolicy()
    assert policy.backend == "bedrock"
    assert policy._parse('{"harvest": 2}') == {"harvest": 2}
    assert policy._parse('Sure! {"harvest": 1, "message": "hi"} done')["harvest"] == 1
    assert policy._parse("no json here") is None
    assert policy._parse('{"not_harvest": 2}') is None

    cfg = config(sanctions_enabled=True, norm_text="sustainable: 1 each")
    state = new_state(cfg)
    obs = observation(state, cfg, 0, default_player_names(8), round_seconds=10.0)
    prompt = policy._build_system_prompt(obs)
    assert "sanction" in prompt and "sustainable: 1 each" in prompt
    quiet_obs = observation(state, config(), 0, default_player_names(8), round_seconds=10.0)
    assert "sanction" not in LlmPolicy()._build_system_prompt(quiet_obs)
