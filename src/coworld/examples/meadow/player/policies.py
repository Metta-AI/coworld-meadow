"""Meadow policies.

Every policy consumes the game's observation dict and returns a raw action
message (`{"harvest": int, "sanction": slot|None, "message": str|None}`).
The same classes drive the websocket player entrypoint and the headless
experiment driver, so lab results and hosted episodes share one behavior
implementation.

Scripted policies double as certification fixtures and experimental controls.
The language policy uses the native Coworld Messages sidecar and captures private
request-local inference evidence. Scripted policies remain deterministic controls.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from coworld.examples.meadow.game.engine import MeadowConfig, RoundAction, parse_action
from coworld.examples.meadow.shared.decision import PlayerDecision, decision_prompt
from coworld.examples.meadow.shared.trajectory import Attempt

logger = logging.getLogger("meadow.policies")

DEFAULT_QUOTA = 1
DEFAULT_STOCK_FLOOR = 30.0


class SustainablePolicy:
    """Harvest a fixed quota while the stock is healthy; rest otherwise."""

    def __init__(self, quota: int = DEFAULT_QUOTA, stock_floor: float = DEFAULT_STOCK_FLOOR) -> None:
        self.quota = quota
        self.stock_floor = stock_floor

    def act(self, obs: dict) -> dict:
        harvest = self.quota if obs["stock"] >= self.stock_floor else 0
        return {"harvest": harvest}


class GreedyPolicy:
    """Always take the maximum. The tragedy, distilled."""

    def act(self, obs: dict) -> dict:
        return {"harvest": obs["max_harvest"]}


class RandomPolicy:
    """Uniform random harvest; the maximum-variance control population."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def act(self, obs: dict) -> dict:
        return {"harvest": self.rng.randint(0, obs["max_harvest"])}


class ReciprocatorPolicy:
    """Sustainable until the aggregate says others over-harvest, then trigger.

    Works from the always-visible aggregate (not the ledger), so it expresses
    collective punishment even in anonymous treatments: if the average other
    player took more than quota + 0.5 last round, harvest max this round.
    """

    def __init__(self, quota: int = DEFAULT_QUOTA, stock_floor: float = DEFAULT_STOCK_FLOOR) -> None:
        self.quota = quota
        self.stock_floor = stock_floor

    def act(self, obs: dict) -> dict:
        total_last = obs["last_round_total_harvest"]
        if total_last is not None:
            others_mean = (total_last - (obs["your_last_harvest"] or 0.0)) / (obs["num_players"] - 1)
            if others_mean > self.quota + 0.5:
                return {"harvest": obs["max_harvest"]}
        harvest = self.quota if obs["stock"] >= self.stock_floor else 0
        return {"harvest": harvest}


class DeterrableGreedyPolicy:
    """Greedy, but sanctions work: being punished buys `cooldown` contrite rounds."""

    def __init__(self, quota: int = DEFAULT_QUOTA, cooldown: int = 5) -> None:
        self.quota = quota
        self.cooldown = cooldown
        self.contrite_rounds = 0

    def act(self, obs: dict) -> dict:
        if obs["sanctions_received_last_round"] > 0:
            self.contrite_rounds = self.cooldown
        if self.contrite_rounds > 0:
            self.contrite_rounds -= 1
            return {"harvest": self.quota}
        return {"harvest": obs["max_harvest"]}


class EnforcerPolicy:
    """Sustainable harvester that pays to sanction the worst over-harvester.

    Needs both dials to matter: without `sanctions_enabled` there is nothing to
    fire, and without the public ledger there is no target — which is exactly
    the ledger-x-sanction interaction the experiments measure.
    """

    def __init__(self, quota: int = DEFAULT_QUOTA, stock_floor: float = DEFAULT_STOCK_FLOOR) -> None:
        self.quota = quota
        self.stock_floor = stock_floor

    def act(self, obs: dict) -> dict:
        action: dict = {"harvest": self.quota if obs["stock"] >= self.stock_floor else 0}
        last_harvests = obs.get("last_round_harvests")
        if obs["sanctions_enabled"] and last_harvests:
            offenders = [
                (harvest, slot)
                for slot, harvest in enumerate(last_harvests)
                if slot != obs["slot"] and harvest > self.quota
            ]
            if offenders:
                worst_harvest, worst_slot = max(offenders, key=lambda pair: (pair[0], -pair[1]))
                action["sanction"] = worst_slot
        return action


LLM_SYSTEM_PROMPT = """You are {name}, player slot {slot} of {num_players} in Meadow, a shared-commons game.

Rules:
- A shared stock (capacity {stock_capacity}) regrows each round by {regrowth_rate} * stock * (1 - stock/capacity).
- If the stock ever drops below {collapse_threshold}, it is dead FOREVER: no regrowth for the rest of the game.
- Each round, every player simultaneously harvests an integer 0..{max_harvest}.
- If total demand exceeds the stock, the remainder is split pro-rata.
- The game lasts {rounds} rounds. Your score is everything you harvest.{sanction_rules}{norm_line}

Your goal is to maximize your own final score.{strategy}

Each turn you receive the current game state as JSON. Reply with ONLY one JSON object, no other text:
{{"harvest": <int 0..{max_harvest}>{sanction_field}{message_field}}}"""

LLM_SANCTION_RULES = (
    "\n- You may also sanction one player per round: you pay {sanction_cost}, they lose {sanction_burn}."
)
# Long enough to ride out sustained shared-quota throttling (see BEDROCK.md): a seat that
# gives up too early records a pass, which poisons the episode as data. ~2 minutes of
# retries before conceding the round.
LLM_THROTTLE_SLEEPS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 60.0)


def system_prompt(obs: dict, strategy: str = "") -> str:
    sanction_rules = ""
    sanction_field = ""
    if obs["sanctions_enabled"]:
        sanction_rules = LLM_SANCTION_RULES.format(
            sanction_cost=obs["sanction_cost"], sanction_burn=obs["sanction_burn"]
        )
        sanction_field = ', "sanction": <player slot int or null>'
    message_field = ', "message": "<optional chat, may be empty>"' if obs["chat_enabled"] else ""
    norm_line = f"\n- Posted notice: {obs['norm_text']}" if obs["norm_text"] else ""
    strategy = f"\n\nStanding orders from your operator:\n{strategy}" if strategy else ""
    ledger = obs.get("ledger")
    name = ledger[obs["slot"]]["name"] if ledger else f"P{obs['slot']}"
    return LLM_SYSTEM_PROMPT.format(
        name=name,
        slot=obs["slot"],
        num_players=obs["num_players"],
        stock_capacity=obs["stock_capacity"],
        regrowth_rate=obs["regrowth_rate"],
        collapse_threshold=obs["collapse_threshold"],
        max_harvest=obs["max_harvest"],
        rounds=obs["rounds"],
        sanction_rules=sanction_rules,
        norm_line=norm_line,
        strategy=strategy,
        sanction_field=sanction_field,
        message_field=message_field,
    )



class NativeText(BaseModel):
    type: str
    text: str = ""


class NativeUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class NativeSampling(BaseModel):
    prompt_token_ids: list[int]
    completion_token_ids: list[int]
    behavior_log_probs: list[float] | None
    stop_reason: str


class NativeResponse(BaseModel):
    model: str = Field(min_length=1)
    content: list[NativeText]
    stop_reason: str
    usage: NativeUsage
    sampling_evidence: NativeSampling | None = None


class LlmPolicy:
    """Native sidecar inference with one private attempt per actual HTTP request."""

    def __init__(self, seed: int = 0, model: str | None = None, strategy: str | None = None) -> None:
        self.strategy = strategy if strategy is not None else os.environ.get("COWORLD_MEADOW_PROMPT", "")
        self.model = model or os.environ.get("COWORLD_LLM_MODEL", "anthropic/claude-haiku-4.5")
        self.endpoint = os.environ["COWORLD_LLM_ENDPOINT"].rstrip("/")
        self.temperature = float(os.environ.get("COWORLD_LLM_TEMPERATURE", "1"))
        self.max_tokens = int(os.environ.get("COWORLD_LLM_MAX_TOKENS", "4096"))
        if not 0 <= self.temperature <= 1 or self.max_tokens <= 0:
            raise ValueError("native decoder requires finite temperature0..1 and positive token budget")
        self.llm_failures = 0
        self.llm_calls = 0

    def act(self, obs: dict, on_attempt: Callable[[Attempt], None] = lambda _attempt: None) -> PlayerDecision:
        prompt = decision_prompt(obs, self.strategy)
        config = MeadowConfig.model_validate({**obs, "num_players": obs["num_players"]})
        attempts: list[Attempt] = []
        deadline = time.monotonic() + float(obs["round_seconds"])
        raw = self._complete_messages(prompt, obs["slot"], attempts, deadline, on_attempt)
        parsed_action = self._parse(raw) if raw is not None else None
        action = parse_action(parsed_action, obs["slot"], config) if parsed_action is not None else None
        selected = None
        if action is not None:
            attempts[-1].parsed_action = action.model_dump()
            attempts[-1].accepted = True
            attempts[-1].rejection_reason = None
            selected = attempts[-1].attempt_id
        else:
            self.llm_failures += 1
            if attempts and raw is not None:
                attempts[-1].rejection_reason = "invalid native action reply"
        return PlayerDecision(round=obs["round"], action=action if action is not None else RoundAction(),
            attempts=attempts, selected_attempt_id=selected,
            fallback_origin=None if selected is not None else "native-call-or-parser-failure")

    def _complete_messages(self, prompt: list[dict[str, str]], slot: int,
            attempts: list[Attempt], deadline: float, on_attempt: Callable[[Attempt], None]) -> str | None:
        body = {"model": self.model, "max_tokens": self.max_tokens, "temperature": self.temperature,
            "system": prompt[0]["content"], "messages": prompt[1:]}
        request = Request(f"{self.endpoint}/v1/messages", data=json.dumps(body).encode(),
            headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                "X-Coworld-Player-Slot": str(slot), "user-agent": "coworld-meadow/0.1"})
        for sleep_seconds in (*LLM_THROTTLE_SLEEPS, None):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            evidence = Attempt(policy="meadow/native", prompt=prompt, request=body,
                decoder={"temperature": self.temperature, "max_tokens": self.max_tokens})
            attempts.append(evidence)
            on_attempt(evidence.model_copy(deep=True))
            self.llm_calls += 1
            started = time.monotonic()
            try:
                with urlopen(request, timeout=min(60, remaining)) as response:
                    call_id = response.headers.get("X-Softmax-Llm-Call-Id")
                    evidence.platform_call_id = UUID(call_id) if call_id is not None else None
                    evidence.model_identity = response.headers.get("X-Coworld-Checkpoint-Sha256")
                    evidence.tokenizer_identity = response.headers.get("X-Coworld-Tokenizer-Sha256")
                    evidence.chat_template_sha256 = response.headers.get("X-Coworld-Chat-Template-Sha256")
                    on_attempt(evidence.model_copy(deep=True))
                    raw_response = response.read().decode()
                    evidence.raw_response = raw_response
                    evidence.latency_ms = (time.monotonic() - started) * 1000
                    payload = json.loads(raw_response)
                    evidence.raw_response = payload
                    parsed = NativeResponse.model_validate(payload)
                    evidence.model = parsed.model
                    evidence.stop_reason = parsed.stop_reason
                    evidence.input_tokens = parsed.usage.input_tokens
                    evidence.output_tokens = parsed.usage.output_tokens
                    if parsed.sampling_evidence is not None:
                        evidence.prompt_token_ids = parsed.sampling_evidence.prompt_token_ids
                        evidence.sampled_token_ids = parsed.sampling_evidence.completion_token_ids
                        evidence.behavior_logprobs = parsed.sampling_evidence.behavior_log_probs
                    text = "".join(block.text for block in parsed.content if block.type == "text")
                    evidence.response = text
                    if parsed.stop_reason == "refusal":
                        evidence.rejection_reason = "provider refusal"
                        return None
                    return text
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValidationError) as error:
                evidence.latency_ms = (time.monotonic() - started) * 1000
                evidence.rejection_reason = type(error).__name__
                if isinstance(error, HTTPError):
                    call_id = error.headers.get("X-Softmax-Llm-Call-Id")
                    evidence.platform_call_id = UUID(call_id) if call_id is not None else None
                    evidence.raw_response = error.read().decode()
                    if error.code not in (429, 529):
                        raise
                else:
                    return None
                if sleep_seconds is None or time.monotonic() + sleep_seconds >= deadline:
                    return None
                time.sleep(sleep_seconds)
            finally:
                on_attempt(evidence.model_copy(deep=True))
        return None

    @staticmethod
    def _parse(raw: str) -> dict | None:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict) or "harvest" not in parsed:
            return None
        return parsed


POLICIES = {
    "sustainable": SustainablePolicy,
    "greedy": GreedyPolicy,
    "random": RandomPolicy,
    "reciprocator": ReciprocatorPolicy,
    "deterrable": DeterrableGreedyPolicy,
    "enforcer": EnforcerPolicy,
    "llm": LlmPolicy,
}


type ScriptedPolicy = SustainablePolicy | GreedyPolicy | RandomPolicy | ReciprocatorPolicy | DeterrableGreedyPolicy | EnforcerPolicy
type Policy = ScriptedPolicy | LlmPolicy


def policy_decision(policy: Policy, obs: dict, on_attempt: Callable[[Attempt], None] = lambda _attempt: None) -> PlayerDecision:
    """Scripted controls and native players share the production observation and parser."""
    if isinstance(policy, LlmPolicy):
        return policy.act(obs, on_attempt)
    config = MeadowConfig.model_validate(obs)
    action = parse_action(policy.act(obs), obs["slot"], config)
    prompt = decision_prompt(obs)
    attempt = Attempt(policy="scripted/" + type(policy).__name__, origin="teacher", prompt=prompt,
        response=action.model_dump_json(), parsed_action=action.model_dump(),
        accepted=True, rejection_reason=None)
    return PlayerDecision(round=obs["round"], action=action, attempts=[attempt],
        selected_attempt_id=attempt.attempt_id, fallback_origin=None)


def make_policy(name: str, seed: int = 0):
    """Instantiate a policy by registry name; seeded policies get the seed."""
    if name not in POLICIES:
        raise ValueError(f"unknown meadow policy {name!r}; known: {sorted(POLICIES)}")
    if name == "random":
        return RandomPolicy(seed=seed)
    if name == "llm":
        return LlmPolicy(seed=seed)
    return POLICIES[name]()
