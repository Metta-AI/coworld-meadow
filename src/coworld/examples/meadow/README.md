# Meadow Coworld

Meadow is a social-pressure Coworld: a round-based commons game built to measure how agent societies handle a shared,
destructible resource — and how institutions (reputation, costly punishment, posted norms, communication) change the
outcome. It is the first world of Softmax's social-pressure program, following up Anthropic's ["Patterns and problems in multiagent systems"](https://www.anthropic.com/research/multiagent-systems).

## The game

N players (2–12) share one stock. Each round, everyone simultaneously harvests an integer `0..max_harvest`.

- The stock regrows logistically: `+ regrowth_rate * stock * (1 - stock / capacity)` per round.
- If it ever drops below `collapse_threshold`, it is dead **forever**. Post-collapse rounds only scavenge what's left.
- Over-demand splits the remaining stock pro-rata.
- Score = everything you harvest, minus sanction costs you pay and burns you receive.

Under the default config (8 players, capacity 100, regrowth 0.35), the sustainable aggregate near half-capacity is
about 8.75 units per round — roughly one per player. Eight greedy harvesters kill the meadow inside 3 rounds.

## Treatment dials (config, not code)

| Dial               | Fields                                            | Treatment it implements               |
| ------------------ | ------------------------------------------------- | ------------------------------------- |
| Reputation         | `ledger_public`                                   | Public per-player harvest history vs. anonymous aggregate |
| Costly punishment  | `sanctions_enabled`, `sanction_cost`, `sanction_burn` | Pay 1 to burn 3 from a named player |
| Norms              | `norm_text`                                       | A posted quota, institutional text only |
| Communication      | `chat_enabled`, `chat_max_chars`                  | One signed public message per round   |

The bundled variants `default`, `anonymous`, and `institutions` cover the main grid cells.

## Roles in this package

- **game** — round-barrier websocket server (`game/server.py`) over a pure engine (`game/engine.py`). Rounds settle
  when every connected player has submitted or `round_seconds` elapses; missing players pass.
- **players** — scripted baselines (`sustainable`, `greedy`, `reciprocator`, `deterrable`, `enforcer`, `random`) and
  an `llm` seat (`player/policies.py`). The LLM seat follows
  [BEDROCK.md](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/BEDROCK.md): Bedrock sidecar + InvokeModel in hosted episodes;
  `COWORLD_MEADOW_MODEL` picks the model and `COWORLD_MEADOW_PROMPT` injects standing orders.
- **grader** — the social planner's perspective (`grader/meadow_grader.py`): group welfare as a fraction of the exact
  dynamic-programming optimum, plus survival, collapse round, synchrony (conformity), and harvest Gini.

## Build, play, certify

From the repository root:

```bash
uv run coworld build --project src/coworld/examples/meadow --version 0.1.0
uv run coworld play src/coworld/examples/meadow/dist/coworld_manifest.json
uv run coworld run-episode src/coworld/examples/meadow/dist/coworld_manifest.json
uv run coworld certify src/coworld/examples/meadow/dist/coworld_manifest.json
```

`play` prints one player-client link per seat (harvest buttons, sanction picker, chat), a global viewer, and an admin
link (pause/resume, round deadline). Certification runs a 20-round episode with 8 mixed scripted seats, sanctions on.

## Headless experiments

The engine runs without containers for lab sweeps:

```python
from coworld.examples.meadow.game.engine import MeadowConfig, social_optimum, welfare
from coworld.examples.meadow.headless import build_policies, run_episode

config = MeadowConfig(num_players=8)
state = run_episode(config, build_policies(["sustainable"] * 4 + ["greedy"] * 4))
print(welfare(state), social_optimum(config)[0])
```

The experiment driver, sweep configs, and collected results live in `experiments/` at the repository root.
