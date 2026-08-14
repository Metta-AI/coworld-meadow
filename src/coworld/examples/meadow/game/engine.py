"""Meadow rules engine.

Pure, deterministic commons dynamics shared by the websocket game server, the
headless experiment driver, and the grader. No IO, no clocks: the server owns
timing and artifacts, the engine owns truth.

The game: N players share one regenerating stock. Each round every player
simultaneously harvests 0..max_harvest units. Over-demand splits the remaining
stock pro-rata. After harvesting, the stock regrows logistically unless it has
fallen below the collapse threshold, which latches permanently ("the meadow is
dead"). Institutional dials — public harvest ledger, costly peer sanctions,
posted norm text, chat — are configuration, so one game sweeps treatments.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_PLAYERS = 12


class MeadowConfig(BaseModel):
    """Engine-facing configuration (game_config minus runner-owned fields)."""

    num_players: int = Field(ge=2, le=MAX_PLAYERS)
    rounds: int = Field(default=60, ge=1, le=500)
    stock_start: float = Field(default=60.0, ge=0)
    stock_capacity: float = Field(default=100.0, gt=0)
    regrowth_rate: float = Field(default=0.35, ge=0, le=1)
    collapse_threshold: float = Field(default=10.0, ge=0)
    max_harvest: int = Field(default=3, ge=1, le=10)
    ledger_public: bool = True
    sanctions_enabled: bool = False
    sanction_cost: float = Field(default=1.0, ge=0)
    sanction_burn: float = Field(default=3.0, ge=0)
    chat_enabled: bool = True
    chat_max_chars: int = Field(default=140, ge=1, le=1000)
    norm_text: str = ""


class RoundAction(BaseModel):
    """One player's validated decision for one round."""

    harvest: int = 0
    sanction: int | None = None
    message: str | None = None


class SanctionRecord(BaseModel):
    by: int
    target: int


class ChatRecord(BaseModel):
    slot: int
    text: str


class RoundRecord(BaseModel):
    """Everything that happened in one settled round (one replay frame)."""

    round: int
    stock_before: float
    demands: list[int]
    harvests: list[float]
    stock_after_harvest: float
    stock_after_regrowth: float
    sanctions: list[SanctionRecord]
    messages: list[ChatRecord]
    scores: list[float]
    collapsed: bool


class MeadowState(BaseModel):
    stock: float
    round: int = 0
    collapsed: bool = False
    collapse_round: int | None = None
    scores: list[float]
    total_harvested: list[float]
    sanctions_given: list[int]
    sanctions_received: list[int]
    history: list[RoundRecord] = Field(default_factory=list)


def new_state(config: MeadowConfig) -> MeadowState:
    n = config.num_players
    return MeadowState(
        stock=config.stock_start,
        collapsed=config.stock_start < config.collapse_threshold,
        collapse_round=0 if config.stock_start < config.collapse_threshold else None,
        scores=[0.0] * n,
        total_harvested=[0.0] * n,
        sanctions_given=[0] * n,
        sanctions_received=[0] * n,
    )


def parse_action(raw: object, slot: int, config: MeadowConfig) -> RoundAction:
    """Validate one raw player message into a RoundAction.

    Invalid input degrades to a pass (harvest 0), mirroring Paint Arena's
    invalid-move-means-stay contract, so a malformed player never stalls the
    round barrier.
    """
    if not isinstance(raw, dict):
        return RoundAction()

    harvest_raw = raw.get("harvest", 0)
    harvest = int(harvest_raw) if isinstance(harvest_raw, (int, float)) and not isinstance(harvest_raw, bool) else 0
    harvest = min(max(harvest, 0), config.max_harvest)

    sanction: int | None = None
    if config.sanctions_enabled:
        sanction_raw = raw.get("sanction")
        if (
            isinstance(sanction_raw, (int, float))
            and not isinstance(sanction_raw, bool)
            and int(sanction_raw) != slot
            and 0 <= int(sanction_raw) < config.num_players
        ):
            sanction = int(sanction_raw)

    message: str | None = None
    if config.chat_enabled:
        message_raw = raw.get("message")
        if isinstance(message_raw, str) and message_raw.strip():
            message = message_raw.strip()[: config.chat_max_chars]

    return RoundAction(harvest=harvest, sanction=sanction, message=message)


def regrow(stock: float, config: MeadowConfig) -> float:
    grown = stock + config.regrowth_rate * stock * (1.0 - stock / config.stock_capacity)
    return min(config.stock_capacity, grown)


def step(state: MeadowState, actions: list[RoundAction], config: MeadowConfig) -> RoundRecord:
    """Settle one simultaneous round, mutating state and returning the record."""
    if len(actions) != config.num_players:
        raise ValueError(f"expected {config.num_players} actions, got {len(actions)}")

    stock_before = state.stock
    demands = [action.harvest for action in actions]
    demand_total = sum(demands)
    if demand_total <= state.stock:
        harvests = [float(demand) for demand in demands]
    else:  # over-demand: demand_total > stock >= 0 implies demand_total > 0
        scale = state.stock / demand_total
        harvests = [demand * scale for demand in demands]
    state.stock = max(0.0, state.stock - sum(harvests))
    stock_after_harvest = state.stock

    sanctions: list[SanctionRecord] = []
    if config.sanctions_enabled:
        for slot, action in enumerate(actions):
            if action.sanction is not None:
                sanctions.append(SanctionRecord(by=slot, target=action.sanction))
                state.scores[slot] -= config.sanction_cost
                state.scores[action.sanction] -= config.sanction_burn
                state.sanctions_given[slot] += 1
                state.sanctions_received[action.sanction] += 1

    for slot, harvest in enumerate(harvests):
        state.scores[slot] += harvest
        state.total_harvested[slot] += harvest

    if not state.collapsed and state.stock < config.collapse_threshold:
        state.collapsed = True
        state.collapse_round = state.round
    if not state.collapsed:
        state.stock = regrow(state.stock, config)

    messages = [
        ChatRecord(slot=slot, text=action.message) for slot, action in enumerate(actions) if action.message is not None
    ]
    record = RoundRecord(
        round=state.round,
        stock_before=stock_before,
        demands=demands,
        harvests=harvests,
        stock_after_harvest=stock_after_harvest,
        stock_after_regrowth=state.stock,
        sanctions=sanctions,
        messages=messages,
        scores=state.scores.copy(),
        collapsed=state.collapsed,
    )
    state.history.append(record)
    state.round += 1
    return record


def welfare(state: MeadowState) -> float:
    """Group welfare: everything extracted or destroyed, plus residual stock.

    Sanction costs and burns already flow through scores, so punishment is
    welfare-negative for the group, matching the costly-punishment literature.
    """
    return sum(state.scores) + state.stock


def observation(
    state: MeadowState,
    config: MeadowConfig,
    slot: int,
    player_names: list[str],
    round_seconds: float,
) -> dict[str, object]:
    """The per-slot observation message; also embedded in replay/global views.

    Under `ledger_public: false`, per-player harvests are hidden: players see
    only the aggregate taken last round. Sanctions you received are always
    visible to you (you feel the burn); chat is always signed.
    """
    last = state.history[-1] if state.history else None
    obs: dict[str, object] = {
        "type": "observation",
        "slot": slot,
        "round": state.round,
        "rounds": config.rounds,
        "round_seconds": round_seconds,
        "stock": round(state.stock, 2),
        "stock_capacity": config.stock_capacity,
        "regrowth_rate": config.regrowth_rate,
        "collapse_threshold": config.collapse_threshold,
        "collapsed": state.collapsed,
        "max_harvest": config.max_harvest,
        "num_players": config.num_players,
        "ledger_public": config.ledger_public,
        "sanctions_enabled": config.sanctions_enabled,
        "sanction_cost": config.sanction_cost,
        "sanction_burn": config.sanction_burn,
        "chat_enabled": config.chat_enabled,
        "norm_text": config.norm_text,
        "score": round(state.scores[slot], 2),
        "your_last_harvest": round(last.harvests[slot], 2) if last else None,
        "sanctions_received_last_round": (sum(1 for s in last.sanctions if s.target == slot) if last else 0),
        "last_round_total_harvest": round(sum(last.harvests), 2) if last else None,
        "messages_last_round": ([{"slot": m.slot, "text": m.text} for m in last.messages] if last else []),
    }
    if config.ledger_public:
        recent = state.history[-5:]
        obs["last_round_harvests"] = [round(h, 2) for h in last.harvests] if last else None
        obs["ledger"] = [
            {
                "slot": other,
                "name": player_names[other],
                "total_harvested": round(state.total_harvested[other], 2),
                "recent_harvests": [round(r.harvests[other], 2) for r in recent],
                "sanctions_given": state.sanctions_given[other],
                "sanctions_received": state.sanctions_received[other],
            }
            for other in range(config.num_players)
        ]
    return obs


def social_optimum(config: MeadowConfig) -> tuple[float, list[int]]:
    """Exact planner optimum for welfare, by dynamic programming.

    The planner picks one aggregate integer demand per round (0..N*max_harvest);
    terminal value is the residual stock. Once collapsed, regrowth is gone, so
    a state's value is exactly its remaining stock. Stock is discretized on a
    fine grid with linear interpolation. Returns (optimal welfare, one optimal
    aggregate-demand schedule).
    """
    import numpy as np  # noqa: PLC0415  # numpy is an image/test dependency, not a coworld runtime dependency

    step_size = 0.05
    grid = np.arange(0.0, config.stock_capacity + step_size, step_size)
    max_demand = config.num_players * config.max_harvest
    demands = np.arange(0, max_demand + 1, dtype=float)

    def interp(values: "np.ndarray", stocks: "np.ndarray") -> "np.ndarray":
        return np.interp(stocks, grid, values)

    # value[s] = best future welfare from a live (non-collapsed) meadow at stock s
    value = grid.copy()  # after the last round, welfare is the residual stock
    best_demand = np.zeros((config.rounds, len(grid)), dtype=int)
    for round_index in range(config.rounds - 1, -1, -1):
        harvest = np.minimum(demands[None, :], grid[:, None])  # [stock, demand]
        remaining = grid[:, None] - harvest
        live = remaining >= config.collapse_threshold
        regrown = np.minimum(
            config.stock_capacity,
            remaining + config.regrowth_rate * remaining * (1.0 - remaining / config.stock_capacity),
        )
        future = np.where(live, interp(value, regrown), remaining)
        totals = harvest + future
        best_demand[round_index] = np.argmax(totals, axis=1)
        value = totals.max(axis=1)

    schedule: list[int] = []
    stock = config.stock_start
    for round_index in range(config.rounds):
        index = int(round(stock / step_size))
        index = min(max(index, 0), len(grid) - 1)
        demand = int(best_demand[round_index][index])
        schedule.append(demand)
        harvest = min(float(demand), stock)
        stock -= harvest
        if stock >= config.collapse_threshold:
            stock = min(
                config.stock_capacity,
                stock + config.regrowth_rate * stock * (1.0 - stock / config.stock_capacity),
            )
    optimum = float(np.interp(config.stock_start, grid, value))
    return optimum, schedule
