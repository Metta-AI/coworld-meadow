"""Complete bridge games keep seed/wording replicas in one physical partition."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def play(variant, seed, wording):
    process = subprocess.Popen(
        [
            sys.executable,
            "tools/training_bridge.py",
            "--variant",
            variant,
            "--mode",
            "text",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    stdin, stdout = process.stdin, process.stdout

    def send(request):
        stdin.write(json.dumps(request) + "\n")
        stdin.flush()
        return json.loads(stdout.readline())

    try:
        frame = send(
            {
                "kind": "reset",
                "seed": seed,
                "players": 8,
                "promptVariant": wording,
                "promptSeed": 0,
            }
        )
        first_view = frame["semantic_view"]
        family = first_view.get("scenario_family")
        turns = 0
        while frame["kind"] != "terminal":
            assert frame["semantic_view"].get("scenario_family") == family
            target = send({"kind": "teacher"})
            frame = send(
                {
                    "kind": "step",
                    "decision_id": frame["decision_id"],
                    "response": target["response"],
                }
            )["observation"]
            turns += 1
        assert len(frame["scores"]) == 8
        return family, turns, frame["scores"]
    finally:
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        process.stdout.close()


def test_seed_and_wording_replicas_share_partition_after_complete_games():
    canonical = play("certification", "scenario-a", "canonical")
    replica = play("certification", "scenario-b", "questions")
    other_horizon = play("default", "scenario-a", "canonical")
    assert isinstance(canonical[0], str) and canonical[0]
    assert canonical[0] == replica[0]
    assert canonical[0] != other_horizon[0]
    assert canonical[1] == replica[1] == 8 * 20
    assert other_horizon[1] == 8 * 60
