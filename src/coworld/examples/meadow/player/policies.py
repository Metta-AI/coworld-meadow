"""Meadow policies.

Every policy consumes the game's observation dict and returns a raw action
message (`{"harvest": int, "sanction": slot|None, "message": str|None}`).
The same classes drive the websocket player entrypoint and the headless
experiment driver, so lab results and hosted episodes share one behavior
implementation.

Scripted policies double as certification fixtures and experimental controls.
The LLM policy follows BEDROCK.md: inside a hosted episode boto3 picks up the
`AWS_ENDPOINT_URL_BEDROCK_RUNTIME` sidecar endpoint automatically and must use
InvokeModel; locally it can fall back to the direct Anthropic API when
`ANTHROPIC_API_KEY` is set.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


class LlmPolicy:
    """An LLM seat. Model and standing orders come from the environment.

    Env vars:
    - `COWORLD_MEADOW_MODEL`: model id (Bedrock or Anthropic form, per backend).
    - `COWORLD_MEADOW_PROMPT`: optional standing-orders strategy text.
    - `AWS_ENDPOINT_URL_BEDROCK_RUNTIME`: set by the hosted runner sidecar;
      its presence selects the Bedrock InvokeModel backend (see BEDROCK.md).
    - `ANTHROPIC_API_KEY` (+ optional `ANTHROPIC_BASE_URL`): local direct API.

    Throttling is retried within the round; a round that still fails becomes a
    pass (harvest 0) and is counted in `llm_failures`. Auth/validation errors
    raise immediately so a misconfigured player fails loudly at round 0 instead
    of silently playing as a non-LLM baseline.
    """

    def __init__(self, seed: int = 0, model: str | None = None, strategy: str | None = None) -> None:
        self.strategy = strategy if strategy is not None else os.environ.get("COWORLD_MEADOW_PROMPT", "")
        self.llm_failures = 0
        self.llm_calls = 0
        self._system_prompt: str | None = None
        if os.environ.get("AWS_ENDPOINT_URL_BEDROCK_RUNTIME") or not os.environ.get("ANTHROPIC_API_KEY"):
            self.backend = "bedrock"
            default_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        else:
            self.backend = "anthropic"
            default_model = "claude-haiku-4-5-20251001"
        self.model = model or os.environ.get("COWORLD_MEADOW_MODEL", default_model)
        self._bedrock_client = None

    def act(self, obs: dict) -> dict:
        if self._system_prompt is None:
            self._system_prompt = self._build_system_prompt(obs)
        payload = {key: value for key, value in obs.items() if key not in ("type", "round_seconds")}
        raw = self._complete(json.dumps(payload, separators=(",", ":")))
        if raw is None:
            self.llm_failures += 1
            return {"harvest": 0}
        action = self._parse(raw)
        if action is None:
            self.llm_failures += 1
            logger.warning("unparseable model reply, passing: %r", raw[:200])
            return {"harvest": 0}
        return action

    def _build_system_prompt(self, obs: dict) -> str:
        sanction_rules = ""
        sanction_field = ""
        if obs["sanctions_enabled"]:
            sanction_rules = LLM_SANCTION_RULES.format(
                sanction_cost=obs["sanction_cost"], sanction_burn=obs["sanction_burn"]
            )
            sanction_field = ', "sanction": <player slot int or null>'
        message_field = ', "message": "<optional chat, may be empty>"' if obs["chat_enabled"] else ""
        norm_line = f"\n- Posted notice: {obs['norm_text']}" if obs["norm_text"] else ""
        strategy = f"\n\nStanding orders from your operator:\n{self.strategy}" if self.strategy else ""
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

    def _complete(self, user_text: str) -> str | None:
        self.llm_calls += 1
        # Pre-4.6 models (haiku 4.5, sonnet 4.5) narrate their analysis and never reach the JSON
        # unless an assistant prefill forces the reply to be the JSON object itself. 4.6+ models
        # reject prefill outright, emit clean JSON unprompted, and think before the text block —
        # so they need max_tokens headroom for the thinking spend instead.
        prefill = any(marker in self.model for marker in ("haiku-4-5", "sonnet-4-5"))
        messages = [{"role": "user", "content": user_text}]
        if prefill:
            messages.append({"role": "assistant", "content": "{"})
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200 if prefill else 4000,
            "system": self._system_prompt,
            "messages": messages,
        }
        if not prefill:
            # Thinking shares the max_tokens budget on 4.6+ models; low effort keeps a
            # one-integer harvest decision from burning the budget before the text block.
            body["output_config"] = {"effort": "low"}
        completion = self._complete_bedrock(body) if self.backend == "bedrock" else self._complete_anthropic(body)
        if completion is None:
            return None
        return "{" + completion if prefill else completion

    def _complete_bedrock(self, body: dict) -> str | None:
        import botocore.exceptions  # noqa: PLC0415  # boto3 ships in the player image, not the coworld package

        if self._bedrock_client is None:
            import boto3  # noqa: PLC0415

            self._bedrock_client = boto3.client("bedrock-runtime")
        for sleep_seconds in (*LLM_THROTTLE_SLEEPS, None):
            try:
                response = self._bedrock_client.invoke_model(modelId=self.model, body=json.dumps(body))
                content = json.loads(response["body"].read())["content"]
                return next((block["text"] for block in content if block["type"] == "text"), "")
            except botocore.exceptions.ClientError as error:
                code = error.response.get("Error", {}).get("Code", "")
                if code not in ("ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"):
                    raise
                if sleep_seconds is None:
                    logger.warning("bedrock still throttled after retries, passing this round")
                    return None
                time.sleep(sleep_seconds)
        return None

    def _complete_anthropic(self, body: dict) -> str | None:
        base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        request_body = {
            "model": self.model,
            "max_tokens": body["max_tokens"],
            "system": body["system"],
            "messages": body["messages"],
        }
        request = Request(
            f"{base}/v1/messages",
            data=json.dumps(request_body).encode(),
            headers={
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "user-agent": "coworld-meadow/0.1",
            },
        )
        for sleep_seconds in (*LLM_THROTTLE_SLEEPS, None):
            try:
                with urlopen(request, timeout=60) as response:
                    content = json.load(response)["content"]
                    return next((block["text"] for block in content if block["type"] == "text"), "")
            except HTTPError as error:
                if error.code not in (429, 529):
                    raise
                if sleep_seconds is None:
                    logger.warning("anthropic API still overloaded after retries, passing this round")
                    return None
                time.sleep(sleep_seconds)
        return None

    def _parse(self, raw: str) -> dict | None:
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
SEEDED_POLICIES = ("random", "llm")


def make_policy(name: str, seed: int = 0):
    """Instantiate a policy by registry name; seeded policies get the seed."""
    if name not in POLICIES:
        raise ValueError(f"unknown meadow policy {name!r}; known: {sorted(POLICIES)}")
    if name in SEEDED_POLICIES:
        return POLICIES[name](seed=seed)
    return POLICIES[name]()
