"""The training bridge follows the hosted engine and its player views."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.training_bridge import TrainingSession

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "variant,rounds",
    [
        ("certification", 20),
        ("default", 60),
        ("anonymous", 60),
        ("institutions", 60),
        ("no-chat", 60),
    ],
)
def test_complete_variant_uses_real_scores(variant: str, rounds: int) -> None:
    session = TrainingSession(variant, "choice", None)
    decision = session.reset({"seed": "training-proof", "players": 8})
    count = 0
    while decision["kind"] != "terminal":
        assert decision["semantic_view"] == session.player_view()
        assert len(session.encode()["values"]) == 34
        assert [len(head["choices"]) for head in session.encode()["action_heads"]] == [
            4,
            9,
        ]
        if variant == "anonymous":
            assert "ledger" not in decision["semantic_view"]
            assert "last_round_harvests" not in decision["semantic_view"]
        response = session.teacher()["response"]
        decision = session.step(
            {"decision_id": decision["decision_id"], "response": response}
        )["observation"]
        count += 1
    assert count == 8 * rounds
    assert decision["scores"] == {
        seat: round(score, 3) for seat, score in enumerate(session.state.scores)
    }


def test_text_mode_accepts_game_chat_and_consumes_malformed_action() -> None:
    session = TrainingSession("certification", "text", 1)
    decision = session.reset({"seed": "text", "players": 8})
    result = session.step(
        {
            "decision_id": decision["decision_id"],
            "response": '{"harvest":2,"message":"Share."}',
        }
    )
    assert result["action"] == {"harvest": 2, "sanction": None, "message": "Share."}
    assert result["observation"]["seat"] == 1
    result = session.step(
        {"decision_id": result["observation"]["decision_id"], "response": "bad reply"}
    )
    assert result["action"] == {"harvest": 0, "sanction": None, "message": None}


def test_jsonl_process_resets_without_losing_seeded_session() -> None:
    process = subprocess.Popen(
        ["python3", str(ROOT / "tools/training_bridge.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    for seed in ("alpha", "beta"):
        process.stdin.write(
            json.dumps({"kind": "reset", "seed": seed, "players": 8}) + "\n"
        )
        process.stdin.flush()
        decision = json.loads(process.stdout.readline())
        assert decision["decision_id"] == 0
        assert decision["kind"] == "decision"
    process.stdin.close()
    assert process.wait(timeout=5) == 0
