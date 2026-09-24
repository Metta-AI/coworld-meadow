"""Player-visible Meadow decisions through the shared Coworld JSONL protocol."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    new_state,
    observation,
    parse_action,
    step,
)
from coworld.examples.meadow.player.policies import (
    EnforcerPolicy,
    LlmPolicy,
    SustainablePolicy,
)

MANIFEST = ROOT / "src/coworld/examples/meadow/coworld_manifest_template.json"
MAX_PLAYERS = 12


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


class TrainingSession:
    def __init__(self, variant: str, mode: str, rounds: int | None):
        manifest = json.loads(MANIFEST.read_text())
        self.base = (
            manifest["certification"]["game_config"]
            if variant == "certification"
            else next(
                entry["game_config"]
                for entry in manifest["variants"]
                if entry["id"] == variant
            )
        )
        self.mode = mode
        self.rounds = rounds

    def reset(self, request: dict[str, object]) -> dict[str, object]:
        players = int(request["players"])
        if players != len(self.base["players"]):
            raise ValueError(f"Variant requires {len(self.base['players'])} seats")
        config = dict(self.base)
        if self.rounds is not None:
            config["rounds"] = self.rounds
        self.config = MeadowConfig.model_validate({**config, "num_players": players})
        self.round_seconds = float(config["round_seconds"])
        self.names = [player["name"] for player in config["players"]]
        self.state = new_state(self.config)
        self.prompt_policy = LlmPolicy(strategy="")
        self.seat = 0
        self.decision_id = 0
        self.actions = []
        seed = hashlib.sha256(str(request["seed"]).encode()).digest()
        self.teachers = [
            EnforcerPolicy(quota=1)
            if self.config.sanctions_enabled and seed[seat] % 4 == 0
            else SustainablePolicy(quota=(0, 1, 1, 2, 3)[seed[seat] % 5])
            for seat in range(players)
        ]
        return self.observation()

    def player_view(self) -> dict[str, object]:
        return observation(
            self.state, self.config, self.seat, self.names, self.round_seconds
        )

    def observation(self) -> dict[str, object]:
        if self.state.round == self.config.rounds:
            return {
                "kind": "terminal",
                "scores": {
                    seat: round(score, 3)
                    for seat, score in enumerate(self.state.scores)
                },
            }
        view = self.player_view()
        messages = [
            {
                "role": "system",
                "content": self.prompt_policy._build_system_prompt(view),
            },
            {
                "role": "user",
                "content": compact(
                    {
                        key: value
                        for key, value in view.items()
                        if key not in ("type", "round_seconds")
                    }
                ),
            },
        ]
        candidates = {
            f"{harvest}:{target}": {
                "decision": {"harvest": harvest, "sanction": target},
                "criterion": {"harvest": harvest, "sanction": target},
            }
            for harvest in range(self.config.max_harvest + 1)
            for target in (
                [
                    "none",
                    *[
                        seat
                        for seat in range(self.config.num_players)
                        if seat != self.seat
                    ],
                ]
                if self.config.sanctions_enabled
                else ["none"]
            )
        }
        return {
            "kind": "decision",
            "game": "meadow",
            "decision_id": self.decision_id,
            "seat": self.seat,
            "engine_seat": self.seat,
            "turn": self.state.round,
            "semantic_view": view,
            "inbox": [],
            "messages": messages,
            "speech_messages": [],
            "action_schema": {
                "type": "object",
                "properties": {
                    "harvest": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": self.config.max_harvest,
                    },
                    "sanction": {"type": ["integer", "string", "null"]},
                    "message": {
                        "type": "string",
                        "maxLength": self.config.chat_max_chars,
                    },
                },
                "required": ["harvest"],
            },
            "typed_question": {
                "state": view,
                "instructions": "Choose harvest and optional sanction.",
                "candidates": candidates,
            }
            if self.mode == "choice"
            else None,
        }

    def encode(self) -> dict[str, object]:
        if self.mode != "choice":
            raise ValueError("Numeric encoding requires choice mode")
        view = self.player_view()
        ledger = view["ledger"] if self.config.ledger_public else []
        values = [
            self.seat / MAX_PLAYERS,
            self.state.round / self.config.rounds,
            float(view["stock"]) / self.config.stock_capacity,
            float(view["collapsed"]),
            float(view["score"]) / (1 + self.config.rounds * self.config.max_harvest),
            float(view["your_last_harvest"] or 0) / self.config.max_harvest,
            float(view["last_round_total_harvest"] or 0)
            / (self.config.max_harvest * self.config.num_players),
            float(view["sanctions_received_last_round"]) / self.config.num_players,
            float(self.config.ledger_public),
            float(self.config.sanctions_enabled),
            *(
                float(ledger[seat]["total_harvested"])
                / (1 + self.config.rounds * self.config.max_harvest)
                if seat < len(ledger)
                else 0.0
                for seat in range(MAX_PLAYERS)
            ),
            *(
                float(view["last_round_harvests"][seat]) / self.config.max_harvest
                if self.config.ledger_public
                and view["last_round_harvests"] is not None
                and seat < self.config.num_players
                else 0.0
                for seat in range(MAX_PLAYERS)
            ),
        ]
        sanctions = [
            "none",
            *[
                seat if seat != self.seat and self.config.sanctions_enabled else None
                for seat in range(self.config.num_players)
            ],
        ]
        return {
            "decision_id": self.decision_id,
            "values": values,
            "action_heads": [
                {
                    "name": "harvest",
                    "choices": list(range(self.config.max_harvest + 1)),
                },
                {"name": "sanction", "choices": sanctions},
            ],
        }

    def teacher(self) -> dict[str, str]:
        raw = self.teachers[self.seat].act(self.player_view())
        action = parse_action(raw, self.seat, self.config)
        return {
            "response": compact(
                {
                    "harvest": action.harvest,
                    "sanction": action.sanction
                    if action.sanction is not None
                    else "none",
                }
            )
        }

    def step(self, request: dict[str, object]) -> dict[str, object]:
        if request["decision_id"] != self.decision_id:
            return {"kind": "rejected", "reason": "stale decision"}
        raw = self.prompt_policy._parse(str(request["response"]))
        if self.mode == "choice":
            if not isinstance(raw, dict) or raw.keys() != {"harvest", "sanction"}:
                return {
                    "kind": "rejected",
                    "reason": "choice needs harvest and sanction",
                }
            encoding = self.encode()["action_heads"]
            if (
                type(raw["harvest"]) is not int
                or raw["harvest"] not in encoding[0]["choices"]
                or raw["sanction"] is None
                or type(raw["sanction"]) not in (int, str)
                or raw["sanction"] not in encoding[1]["choices"]
            ):
                return {"kind": "rejected", "reason": "illegal choice"}
        action = parse_action(raw, self.seat, self.config)
        self.actions.append(action)
        self.decision_id += 1
        self.seat += 1
        if self.seat == self.config.num_players:
            step(self.state, self.actions, self.config)
            self.actions = []
            self.seat = 0
        return {
            "kind": "accepted",
            "action": action.model_dump(),
            "observation": self.observation(),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="certification")
    parser.add_argument("--mode", choices=("choice", "text"), default="choice")
    parser.add_argument("--rounds", type=int)
    args = parser.parse_args()
    session = TrainingSession(args.variant, args.mode, args.rounds)
    for line in sys.stdin:
        request = json.loads(line)
        match request["kind"]:
            case "reset":
                response = session.reset(request)
            case "encode":
                response = session.encode()
            case "teacher":
                response = session.teacher()
            case "step":
                response = session.step(request)
            case _:
                raise ValueError(f"Unknown training command {request['kind']}")
        print(compact(response), flush=True)


if __name__ == "__main__":
    main()
