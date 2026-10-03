"""Export whole production Meadow teacher episodes; use the shared importer for dataset splits."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coworld.examples.meadow.game.engine import MeadowConfig
from coworld.examples.meadow.headless import run_episode
from coworld.examples.meadow.player.policies import EnforcerPolicy, SustainablePolicy
from coworld.examples.meadow.shared.trajectory import Trajectory

MANIFEST = ROOT / "src/coworld/examples/meadow/coworld_manifest_template.json"


def export(args: argparse.Namespace) -> None:
    if args.games < 10:
        raise ValueError("qualification requires at least ten complete games per variant")
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty:
        raise ValueError("commit the source before exporting a pinned teacher corpus")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = json.loads(MANIFEST.read_text())
    base = next(entry["game_config"] for entry in manifest["variants"] if entry["id"] == args.variant)
    os.umask(0o077)
    root = args.output.resolve()
    root.mkdir(mode=0o700)
    runs = []
    for seed in range(args.first_seed, args.first_seed + args.games):
        config = MeadowConfig.model_validate({**base, "num_players": len(base["players"]), "seed": seed})
        policies = [EnforcerPolicy(quota=1) if config.sanctions_enabled and (seed + slot) % 4 == 0
            else SustainablePolicy(quota=(0, 1, 1, 2, 3)[(seed + slot) % 5]) for slot in range(config.num_players)]
        episode_id = f"meadow-{args.variant}-{seed}"
        trajectory = Trajectory(episode_id=episode_id, game_version="source-" + revision,
            source_revision=revision, image_digest=None, seed_family=f"meadow-{seed}")
        state = run_episode(config, policies, [entry["name"] for entry in base["players"]], trajectory=trajectory)
        trajectory.write(root / "episodes" / (episode_id + ".jsonl"))
        runs.append({"episode_id": episode_id, "seed": seed, "seed_family": f"meadow-{seed}",
            "configuration": config.model_dump(), "teacher_policies": [{"kind": type(policy).__name__,
                "quota": policy.quota, "stock_floor": policy.stock_floor} for policy in policies],
            "scores": state.scores, "decisions": len(trajectory.records) - 1})
    destination = root / "manifest.json"
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump({"format": "coworld-private-teacher-corpus-v1", "game": "meadow",
            "variant": args.variant, "source_revision": revision, "runs": runs,
            "dataset_export": "canonical complete private trajectories; shared importer owns seed-family splitting"}, handle, indent=2)
        handle.write("\n")
    print(f"complete private episodes={len(runs)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--variant", choices=[entry["id"] for entry in json.loads(MANIFEST.read_text())["variants"]], required=True)
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--first-seed", type=int, default=1)
    export(parser.parse_args())
