"""Meadow grader: the social planner's perspective on one episode.

Consumes an episode bundle (`COGAME_EPISODE_BUNDLE_URI`), reads results and
replay, and writes a grade to `COGAME_GRADE_URI`. The grade's `score` is group
welfare as a fraction of the exact DP optimum for the episode's config — the
number the social-pressure experiments sweep. Synchrony (the conformity
measure) and the harvest Gini ride along.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from itertools import combinations

from pydantic import BaseModel

from coworld.examples.meadow.game.engine import MeadowConfig, social_optimum
from coworld.examples.meadow.shared.artifact_io import JSON_CONTENT_TYPE, read_data, write_data

GRADER_ID = "meadow-grader"


class GraderInputs(BaseModel):
    episode_bundle_uri: str
    grade_uri: str


class MeadowGrade(BaseModel):
    grader_id: str
    score: float
    scale: str
    welfare: float
    optimum_welfare: float
    survived: bool
    collapse_round: int | None
    synchrony_same_action_rate: float | None
    harvest_gini: float | None


def load_grader_inputs() -> GraderInputs:
    return GraderInputs(
        episode_bundle_uri=os.environ["COGAME_EPISODE_BUNDLE_URI"],
        grade_uri=os.environ["COGAME_GRADE_URI"],
    )


def load_bundle(bundle_uri: str) -> tuple[dict, dict]:
    bundle = zipfile.ZipFile(io.BytesIO(read_data(bundle_uri)))
    manifest = json.loads(bundle.read("manifest.json"))
    results = json.loads(bundle.read(manifest["files"]["results"]))
    replay = json.loads(bundle.read(manifest["files"]["replay"]))
    return results, replay


def synchrony_same_action_rate(demand_rows: list[list[int]]) -> float | None:
    """Mean over rounds and player pairs of "did the pair demand identically"."""
    if not demand_rows or len(demand_rows[0]) < 2:
        return None
    pairs = list(combinations(range(len(demand_rows[0])), 2))
    matches = sum(1 for row in demand_rows for left, right in pairs if row[left] == row[right])
    return matches / (len(demand_rows) * len(pairs))


def harvest_gini(totals: list[float]) -> float | None:
    if not totals or sum(totals) == 0:
        return None
    values = sorted(totals)
    n = len(values)
    cumulative = sum((2 * index - n - 1) * value for index, value in enumerate(values, start=1))
    return cumulative / (n * sum(values))


def build_grade(results: dict, replay: dict) -> MeadowGrade:
    config = MeadowConfig.model_validate({**replay["config"], "num_players": len(replay["player_names"])})
    optimum, _ = social_optimum(config)
    demand_rows = [frame["demands"] for frame in replay["frames"]]
    return MeadowGrade(
        grader_id=GRADER_ID,
        score=results["welfare"] / optimum,
        scale="group welfare (total scores + residual stock) as a fraction of the exact planner optimum",
        welfare=results["welfare"],
        optimum_welfare=round(optimum, 3),
        survived=results["collapse_round"] is None,
        collapse_round=results["collapse_round"],
        synchrony_same_action_rate=synchrony_same_action_rate(demand_rows),
        harvest_gini=harvest_gini(results["total_harvested"]),
    )


def run(inputs: GraderInputs) -> MeadowGrade:
    results, replay = load_bundle(inputs.episode_bundle_uri)
    grade = build_grade(results, replay)
    write_data(inputs.grade_uri, grade.model_dump_json(indent=2), content_type=JSON_CONTENT_TYPE)
    return grade


if __name__ == "__main__":
    print(run(load_grader_inputs()).model_dump_json(indent=2))
