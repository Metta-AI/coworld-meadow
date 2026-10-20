"""Episode-stable Meadow rules, independent of engine configuration."""

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

    bank: Literal["meadow-rules-v2"] = "meadow-rules-v2"
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

    def rules(self, canonical: str) -> str:
        paragraphs = (
            "The commons holds at most {stock_capacity}. Each round its growth is {regrowth_rate} * stock * (1 - stock/capacity).",
            "Stock below {collapse_threshold} collapses permanently; it cannot regrow during any remaining round.",
            "Players choose harvests simultaneously, each an integer from 0 through {max_harvest}. When combined demand exceeds available stock, players receive proportional shares.",
            "Play lasts {rounds} rounds. Harvest adds to your score.{sanction_rules}{norm_line}",
        )
        match self.variant:
            case "canonical":
                return canonical
            case "plain":
                return "Rules:\n" + "\n\n".join(paragraphs)
            case "numbered":
                return "Rules:\n" + "\n".join(
                    f"{i}. {p}" for i, p in enumerate(paragraphs, 1)
                )
            case "questions":
                questions = (
                    "How does the resource grow?",
                    "What ends regrowth?",
                    "How is stock allocated?",
                    "How long do we play and score?",
                )
                return "Rules:\n" + "\n\n".join(
                    f"{q} {p}" for q, p in zip(questions, paragraphs, strict=True)
                )
            case "reordered":
                return "Rules:\n" + "\n\n".join(paragraphs[i] for i in (3, 2, 0, 1))
            case "heldout-briefing":
                return "Rules briefing:\nChoose an integer harvest in 0..{max_harvest} at the same time as everyone else. Excess demand is met pro-rata from the available stock. Across {rounds} rounds, harvested amounts contribute to your score.{sanction_rules}{norm_line}\n\nCapacity is {stock_capacity}; per-round growth follows {regrowth_rate} * stock * (1 - stock/capacity). Crossing below {collapse_threshold} permanently disables growth for this game."
            case "heldout-reference":
                return "Rules reference:\nResource: capacity {stock_capacity}, growth per round {regrowth_rate} * stock * (1 - stock/capacity).\nCollapse: below {collapse_threshold}, no further regeneration is possible.\nAllocation: simultaneous integer demands between 0 and {max_harvest}; insufficient stock is apportioned in proportion to demand.\nDuration and score: {rounds} rounds; harvest contributes to your score.{sanction_rules}{norm_line}"

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
