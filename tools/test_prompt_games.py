"""Complete Meadow bridge games, with original-source and wording comparisons."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TextIO, cast

VARIANTS = ("certification", "default", "anonymous", "institutions", "no-chat")
WORDINGS = (
    "canonical",
    "plain",
    "numbered",
    "questions",
    "reordered",
    "heldout-briefing",
    "heldout-reference",
)
ROOT = Path(__file__).resolve().parents[1]


def play(
    root: Path,
    variant: str,
    mode: str,
    seed: int,
    wording: str,
    prompt_seed: int,
    original: bool,
) -> list:
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    process = subprocess.Popen(
        [
            sys.executable,
            str(root / "tools/training_bridge.py"),
            "--variant",
            variant,
            "--mode",
            mode,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdin = cast(TextIO, process.stdin)
    stdout = cast(TextIO, process.stdout)
    stderr = cast(TextIO, process.stderr)

    def request(body: dict) -> dict:
        stdin.write(json.dumps(body) + "\n")
        stdin.flush()
        line = stdout.readline()
        assert line, stderr.read()
        return json.loads(line)

    transcript = []
    obs = request(
        {
            "kind": "reset",
            "seed": seed,
            "players": 8,
            "promptVariant": wording,
            "promptSeed": prompt_seed,
        }
    )
    selected = WORDINGS[prompt_seed % 5] if wording == "mixed" else wording
    seen_systems = {}
    while obs["kind"] != "terminal":
        system, user = (message["content"] for message in obs["messages"])
        if not original:
            family = obs["semantic_view"].pop("scenario_family")
            assert family.startswith("meadow-")
            assert "scenario_family" not in json.loads(user)
            metadata = obs["semantic_view"].pop("prompt_template")
            assert metadata == {
                "bank": "meadow-rules-v2",
                "variant": selected,
                "selection": wording,
                "seed": prompt_seed,
                "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
                "user_sha256": hashlib.sha256(user.encode()).hexdigest(),
            }
            if mode == "choice":
                obs["typed_question"]["state"].pop("prompt_template")
                assert obs["typed_question"]["state"].pop("scenario_family") == family
        assert json.loads(user) == {
            k: v
            for k, v in obs["semantic_view"].items()
            if k not in ("type", "round_seconds")
        }
        seat = obs["seat"]
        if seat in seen_systems:
            assert seen_systems[seat] == system
        seen_systems[seat] = system
        if wording != "canonical":
            obs["messages"][0]["content"] = system[system.index("Your goal") :]
        encoding = request({"kind": "encode"}) if mode == "choice" else None
        if encoding is not None:
            assert len(encoding["values"]) == 34
        teacher = request({"kind": "teacher"})
        response = request(
            {
                "kind": "step",
                "decision_id": obs["decision_id"],
                "response": teacher["response"],
            }
        )
        assert response["kind"] == "accepted"
        transcript.append((obs, encoding, teacher, response["action"]))
        obs = response["observation"]
    transcript.append(obs)
    stdin.close()
    assert process.wait(timeout=30) == 0, stderr.read()
    return transcript


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path)
    args = parser.parse_args()
    count = 0
    for variant in VARIANTS:
        for mode in ("choice", "text"):
            for seed in (1,):
                canonical = play(ROOT, variant, mode, seed, "canonical", 0, False)
                if args.original:
                    assert canonical == play(
                        args.original, variant, mode, seed, "canonical", 0, True
                    )
                for row in canonical[:-1]:
                    row[0]["messages"][0]["content"] = row[0]["messages"][0]["content"][
                        row[0]["messages"][0]["content"].index("Your goal") :
                    ]
                count += 1
                for wording, prompt_seed in [(w, 0) for w in WORDINGS[1:]] + [
                    ("mixed", 3)
                ]:
                    assert (
                        play(ROOT, variant, mode, seed, wording, prompt_seed, False)
                        == canonical
                    ), (variant, mode, seed, wording, prompt_seed)
                    count += 1
        print(
            f"{variant}: complete games preserve views, rules, encodings, actions and outcomes",
            flush=True,
        )
    for wording in WORDINGS[-2:]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/training_bridge.py")],
            input=json.dumps(
                {
                    "kind": "reset",
                    "players": 8,
                    "seed": 1,
                    "split": "train",
                    "promptVariant": wording,
                }
            )
            + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        assert (
            result.returncode != 0
            and "held-out wording is evaluation only" in result.stderr
        )
    print(f"PASS {count} complete games; held-out training rejected", flush=True)


if __name__ == "__main__":
    main()
