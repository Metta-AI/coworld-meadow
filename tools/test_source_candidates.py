"""Qualify complete source-exported episodes against the production Meadow engine."""

import argparse
import json
from pathlib import Path

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    episode_results,
    new_state,
    observation,
    parse_action,
    step,
)
from coworld.examples.meadow.shared.decision import decision_prompt, executed_action
from coworld.examples.meadow.shared.prompts import PromptSelection
from coworld.examples.meadow.player.policies import LlmPolicy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.directory / "manifest.json").read_text())
    assert (
        manifest["format"] == "coworld-private-candidates-v1"
        and manifest["review_required"] is True
    )
    selection = PromptSelection.model_validate(manifest["prompt_configuration"])
    assert not selection.variant.startswith("heldout-")
    template = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "src/coworld/examples/meadow/coworld_manifest_template.json"
        ).read_text()
    )
    variant = next(
        item for item in template["variants"] if item["id"] == manifest["variant"]
    )
    names = [player["name"] for player in variant["game_config"]["players"]]
    families = set()
    for run in manifest["runs"]:
        config = MeadowConfig.model_validate(run["configuration"])
        state = new_state(config)
        source = args.directory / "episodes" / (run["episode_id"] + ".jsonl")
        assert source.stat().st_mode & 0o777 == 0o600
        events = [json.loads(line) for line in source.read_text().splitlines()]
        assert len(events) == config.rounds * config.num_players + 1
        for round_number in range(config.rounds):
            decisions = events[
                round_number * config.num_players : (round_number + 1)
                * config.num_players
            ]
            actions = []
            for seat, decision in enumerate(decisions):
                assert decision["episode_id"] == run["episode_id"]
                assert decision["source_revision"] == manifest["source_revision"]
                assert (
                    decision["decision_index"]
                    == round_number * config.num_players + seat
                )
                assert decision["seat"] == str(seat)
                assert decision["terminal"] == (round_number == config.rounds - 1)
                view = observation(state, config, seat, names, 60.0)
                view["prompt_configuration"] = selection.model_dump()
                prompt = decision_prompt(view, selection=selection)
                view["prompt_template"] = selection.metadata(
                    prompt[0]["content"], prompt[1]["content"]
                )
                assert decision["observation"] == view
                (attempt,) = decision["attempts"]
                assert decision["prompt"] == attempt["prompt"] == prompt
                assert attempt["origin"] == "teacher" and attempt["accepted"] is True
                assert decision["selected_attempt_id"] == attempt["attempt_id"]
                parsed = LlmPolicy._parse(attempt["response"])
                assert parsed is not None
                action = parse_action(parsed, seat, config)
                assert attempt["parsed_action"] == action.model_dump()
                actions.append(action)
            record = step(state, actions, config)
            for seat, decision in enumerate(decisions):
                assert (
                    decision["executed_action"]
                    == executed_action(record, seat).model_dump()
                )
                assert (
                    decision["action_status"] == "accepted"
                    and decision["fallback_origin"] is None
                )
        final = events[-1]
        assert (
            final["status"] == "completed"
            and final["source_revision"] == manifest["source_revision"]
        )
        assert final["outcome"] == episode_results(state).model_dump(mode="json")
        assert final["participant_outcomes"] == {
            str(seat): {"score": round(score, 3)}
            for seat, score in enumerate(state.scores)
        }
        assert final["seed_family"] == run["seed_family"] == f"meadow-{run['seed']}"
        assert run["scores"] == state.scores
        families.add(final["seed_family"])
    assert len(families) >= 10
    print(
        f"PASS {len(manifest['runs'])} complete production source episodes", flush=True
    )


if __name__ == "__main__":
    main()
