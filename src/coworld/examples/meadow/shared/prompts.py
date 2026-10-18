"""Episode-stable Meadow introductions, independent of engine configuration."""

import hashlib
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Wording = Literal[
    "canonical",
    "plain",
    "numbered",
    "questions",
    "reordered",
    "heldout-briefing",
    "heldout-reference",
]
Variant = Wording | Literal["mixed"]
TRAIN: tuple[Wording, ...] = (
    "canonical",
    "plain",
    "numbered",
    "questions",
    "reordered",
)


class PromptSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    bank: Literal["meadow-rules-v1"] = "meadow-rules-v1"
    variant: Wording = "canonical"
    selection: Variant = "canonical"
    seed: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        expected = (
            TRAIN[self.seed % len(TRAIN)]
            if self.selection == "mixed"
            else self.selection
        )
        if self.variant != expected:
            raise ValueError("resolved wording differs from episode selection")
        return self

    def metadata(self, system: str, user: str) -> dict:
        return {
            **self.model_dump(),
            "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
            "user_sha256": hashlib.sha256(user.encode()).hexdigest(),
        }

    def introduction(self, name: str, slot: int, players: int) -> str:
        templates = {
            "canonical": "You are {name}, player slot {slot} of {players} in Meadow, a shared-commons game.",
            "plain": "In Meadow, a shared-commons game, you play {name} in slot {slot} among {players} players.",
            "numbered": "1. Game: Meadow, a shared commons. 2. Players: {players}. 3. You are {name}, in slot {slot}.",
            "questions": "Which game? Meadow, a shared-commons game. Who are you? {name}, player slot {slot} among {players} players.",
            "reordered": "Meadow is a shared-commons game with {players} players. Your name is {name}; your player slot is {slot}.",
            "heldout-briefing": "Meadow briefing: {players} players share a commons. You are {name}, assigned player slot {slot}.",
            "heldout-reference": "Game: Meadow (shared commons). Player count: {players}. Your identity: {name}. Your slot: {slot}.",
        }
        return templates[self.variant].format(name=name, slot=slot, players=players)


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)
    variant: Variant = Field(default="canonical", alias="promptVariant")
    seed: int = Field(default=0, ge=0, alias="promptSeed")

    @model_validator(mode="after")
    def explicit_mixed_seed(self) -> Self:
        if self.variant == "mixed" and "seed" not in self.model_fields_set:
            raise ValueError("mixed wording requires an explicit promptSeed")
        return self

    def resolve(self) -> PromptSelection:
        return PromptSelection(
            selection=self.variant,
            variant=TRAIN[self.seed % len(TRAIN)]
            if self.variant == "mixed"
            else self.variant,
            seed=self.seed,
        )
