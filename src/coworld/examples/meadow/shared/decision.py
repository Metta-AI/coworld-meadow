"""The same parsed player decision drives hosted, headless, and language training."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from coworld.examples.meadow.game.engine import (
    MeadowConfig,
    RoundAction,
    RoundRecord,
    parse_action,
)
from coworld.examples.meadow.shared.trajectory import Attempt


class PlayerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["action"] = "action"
    round: int = Field(ge=0)
    action: RoundAction
    attempts: list[Attempt] = Field(default_factory=list)
    selected_attempt_id: str | None = None
    fallback_origin: str | None = None


def parse_reply(raw: str, slot: int, config: MeadowConfig) -> RoundAction | None:
    """Use the shipped text parser, then the engine's legal-action normalization."""
    from coworld.examples.meadow.player.policies import LlmPolicy

    parsed = LlmPolicy._parse(raw)
    return parse_action(parsed, slot, config) if parsed is not None else None


def apply_player_decision(decision: PlayerDecision, slot: int, config: MeadowConfig) -> PlayerDecision:
    """The authenticated socket owns the seat; it does not establish a teacher identity."""
    decision = decision.model_copy(deep=True)
    for attempt in decision.attempts:
        attempt.accepted = False
        if attempt.origin in {"teacher", "human"}:
            attempt.origin = "unknown"
    canonical = parse_action(decision.action.model_dump(), slot, config)
    if not decision.attempts and decision.fallback_origin is None:
        attempt = Attempt(policy="external-action", origin="unknown", prompt=None,
            response=decision.action.model_dump_json(), parsed_action=canonical.model_dump(),
            accepted=True, rejection_reason=None)
        decision.attempts = [attempt]
        decision.selected_attempt_id = attempt.attempt_id
    selected = [attempt for attempt in decision.attempts if attempt.attempt_id == decision.selected_attempt_id]
    if len({attempt.attempt_id for attempt in decision.attempts}) != len(decision.attempts):
        raise ValueError("duplicate native attempt identity")
    if decision.fallback_origin is not None:
        if decision.selected_attempt_id is not None:
            raise ValueError("fallback cannot select an attempt")
        decision.action = RoundAction()
        return decision
    if len(selected) != 1:
        raise ValueError("submitted decision must select exactly one response")
    attempt = selected[0]
    parsed = parse_reply(TypeAdapter(str).validate_python(attempt.response), slot, config)
    attempt.parsed_action = parsed.model_dump() if parsed is not None else None
    if attempt.parsed_action != canonical.model_dump():
        attempt.rejection_reason = "model response differs from submitted canonical action"
        decision.action = RoundAction()
        decision.selected_attempt_id = None
        decision.fallback_origin = "player-parser-mismatch"
        return decision
    attempt.accepted = True
    attempt.rejection_reason = None
    decision.action = canonical
    return decision


def decision_prompt(view: dict, strategy: str = "") -> list[dict[str, str]]:
    from coworld.examples.meadow.player.policies import system_prompt

    return [
        {"role": "system", "content": system_prompt(view, strategy)},
        {"role": "user", "content": json.dumps({key: value for key, value in view.items() if key not in {"type", "round_seconds"}}, separators=(",", ":"))},
    ]


def executed_action(record: RoundRecord, slot: int) -> RoundAction:
    """Derive the applied command from the settled engine record, including chat and sanctions."""
    return RoundAction(harvest=record.demands[slot],
        sanction=next((entry.target for entry in record.sanctions if entry.by == slot), None),
        message=next((entry.text for entry in record.messages if entry.slot == slot), None))


class AttemptProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["attempt"] = "attempt"
    round: int = Field(ge=0)
    attempt: Attempt
