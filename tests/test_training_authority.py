"""Player assertions are never authority for teacher identity or applied labels."""
import json

import pytest

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    RoundAction,
    new_state,
    observation,
    step,
)
from coworld.examples.meadow.shared.decision import (
    PlayerDecision,
    apply_player_decision,
    decision_prompt,
)
from coworld.examples.meadow.shared.trajectory import Attempt, Trajectory


@pytest.mark.parametrize("origin", ["teacher", "human"])
def test_external_assertion_is_unknown(origin):
    action = RoundAction(harvest=2)
    attempt = Attempt(policy="untrusted", origin=origin, prompt=None, response=action.model_dump_json())
    decision = apply_player_decision(PlayerDecision(round=0, action=action, attempts=[attempt],
        selected_attempt_id=attempt.attempt_id), 0, MeadowConfig(num_players=2))
    assert decision.attempts[0].origin == "unknown"
    assert decision.attempts[0].accepted


def test_response_and_submitted_action_mismatch_retains_rejected_sample():
    attempt = Attempt(policy="native", prompt=None, response='{"harvest":1}')
    decision = apply_player_decision(PlayerDecision(round=0, action=RoundAction(harvest=3),
        attempts=[attempt], selected_attempt_id=attempt.attempt_id), 0, MeadowConfig(num_players=2))
    assert decision.action == RoundAction()
    assert decision.selected_attempt_id is None and decision.fallback_origin == "player-parser-mismatch"
    assert not decision.attempts[0].accepted
    assert decision.attempts[0].parsed_action["harvest"] == 1


def test_private_complete_writer_preserves_engine_action_and_exclusive_file(tmp_path):
    trajectory = Trajectory(episode_id="fixture", game_version="source-fixture", source_revision="a" * 40,
        image_digest=None, seed_family="meadow-0")
    action = RoundAction(harvest=2)
    attempt = Attempt(policy="scripted", origin="teacher", prompt=[{"role": "user", "content": "PRIVATE"}],
        response=action.model_dump_json(), parsed_action=action.model_dump(), accepted=True, rejection_reason=None)
    with pytest.raises(ValueError, match="independently executed"):
        trajectory.record(decision_id="0", seat=0, observation={}, prompt=attempt.prompt,
            attempts=[attempt], executed_action=RoundAction(harvest=1).model_dump(), fallback_origin=None, terminal=True)
    trajectory.record(decision_id="0", seat=0, observation={}, prompt=attempt.prompt, attempts=[attempt],
        executed_action=action.model_dump(), fallback_origin=None, terminal=True)
    trajectory.finish(outcome={"scores": [2, 0]}, participant_outcomes={"0": {"score": 2}, "1": {"score": 0}}, completed=True)
    path = tmp_path / "private" / "episode.jsonl"
    trajectory.write(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text().splitlines()[-1])["status"] == "completed"
    with pytest.raises(FileExistsError):
        trajectory.write(path)


def test_anonymous_prompt_does_not_expose_other_seat_identity_or_private_accounts():
    config = MeadowConfig(num_players=3, ledger_public=False)
    original = new_state(config)
    step(original, [RoundAction(harvest=1), RoundAction(harvest=2), RoundAction(harvest=3)], config)
    changed = original.model_copy(deep=True)
    changed.scores[1:] = [999, -999]
    changed.total_harvested[1:] = [888, 777]
    changed.history[-1].harvests[1:] = list(reversed(changed.history[-1].harvests[1:]))
    first = observation(original, config, 0, ["own", "hidden-one", "hidden-two"], 2)
    second = observation(changed, config, 0, ["own", "different-one", "different-two"], 2)
    assert first == second
    assert decision_prompt(first, "operator") == decision_prompt(second, "operator")
