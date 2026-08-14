# Meadow Results

**Status:** environment validated and scripted-seat findings collected (2026-08-14); LLM-seat treatment sweep run on
EC2 with Bedrock seats (2026-08-14, 60 episodes, 14,400 model calls, 3 failed calls). Scripted calibration is Wave 1;
the "LLM seats" section below is Wave 2.

**Scope, honestly:** every number below comes from scripted policies. These results validate that the *environment*
is well-posed — collapse boundaries exist, institutional dials have mechanical bite, welfare has an exact computed
denominator — and they characterize the incentive landscape LLM agents will face. They are not claims about LLM
behavior. The scripted "deterrable" policy *assumes* sanctions deter (5 contrite rounds per sanction received);
whether LLM agents are deterrable is precisely what the staged sweep measures.

## Setup

Default config: 8 players, 60 rounds, stock 60 of capacity 100, logistic regrowth 0.35, permanent collapse below 10,
harvest 0–3 per round. Group welfare = total scores + residual stock. The exact planner optimum, by dynamic
programming over aggregate demand: **585.0** (drive stock to half-capacity, then harvest the ~8.75/round regrowth —
about 1 per player). Reference points: 8× sustainable scores **94.5%** of optimum and survives; 8× greedy scores
**12.6%** and kills the meadow in round 2. Every episode row is in `results/scripted_runs.jsonl`; deterministic
conditions run once, stochastic ones 30 seeds.

## Finding 1 — the meadow tolerates exactly one defector

![greedy gradient](results/fig_greedy_gradient.png)

With 7 sustainable seats, one greedy seat still survives at **80.6%** of optimum (the defector free-rides, the
commons absorbs it). Two greedy seats collapse the meadow at round 17 and welfare falls to **28.0%**. The cliff
between one and two defectors is the sharpest edge in the environment — useful because LLM societies will sit right
on it: the interesting measurement is which side they land on.

## Finding 2 — trigger strategies are a conformity cascade

Same gradient, but the cooperative seats are *reciprocators* (harvest max for a round whenever the average other
seat over-harvested): two greedy seats now kill the meadow at **round 3 instead of 17**, welfare 13.9% vs 28.0%.
Punishing over-harvest *with* over-harvest converts two defectors into eight within two rounds — mechanically the
same synchronized-defection failure Anthropic's paper reports (all agents defecting simultaneously in prisoner's
dilemmas, identical polling floods). In a commons, grim trigger is collective suicide. Institutions that punish
*outside* the resource (sanctions) exist precisely to avoid this.

## Finding 3 — institutions only work as a system

![institution grid](results/fig_institution_grid.png)

Population: 4 deterrable-greedy + 4 enforcer seats. Ledger alone (nothing to fire), sanctions alone (no target
visible): identical to no institutions — collapse at round 5, 16.0% of optimum. Both dials on: sanctions fire (48),
collapse is pushed to round 9, and welfare goes **negative** (−13.6%) — four enforcers pay more in sanction costs
and burns than the delayed collapse returns. Reputation infrastructure and enforcement power are complements, and
enforcement is not free.

## Finding 4 — the ecology recovers before the economy does

![police force](results/fig_police_force.png)

Sweeping enforcer count 0→8 against deterrable-greedy seats: 1–3 enforcers make things *worse* than no enforcement
(welfare 12.6% → 10.6% → 6.9% → 2.6%: punishment costs without enough deterrence). At **5 enforcers the stock
survives** — but welfare is −77.7%, a permanent punishment war (225 sanctions over 60 rounds). Enforcement doesn't
pay for itself until **7 enforcers** (+22.2%), and only an all-cooperator society reaches 94.5%. Two structural
failure modes are visible in the data: the *second-order free-rider problem* (enforcers pay, non-enforcers benefit)
and *punishment pile-on* — every enforcer independently targets the same worst offender, so one defector absorbs up
to 7 burns in one round while others free-ride untouched. Uncoordinated punishment is expensive; the sweep
quantifies exactly how expensive.

## Finding 5 — random variance is not diversity

30 seeds of 8× uniform-random seats: **0/30 survive** (median collapse round 9), welfare 22.1% ± 3.0. Behavioral
variance alone doesn't save a commons — expected aggregate demand (12/round vs sustainable 8.75) is what matters.
This sharpens the monoculture-vs-mixed LLM hypothesis: if mixed-model societies do better, it will be because
diversity breaks *correlated* decisions, not because noise helps.

## Supporting observations

- The synchrony metric (mean pairwise same-action rate) behaves: 1.0 for identical deterministic populations, 0.25
  for random seats, 0.4–0.6 for mixed populations. For LLM seats it is the paper's "low variance" failure, quantified.
- The websocket path was smoke-tested end to end (real server + 4 player processes + grader): the enforcer sanctioned
  the greedy seat 11× in 12 rounds; the grader scored the episode 0.724 of optimum. Containerized
  `coworld build` / `run-episode` / `certify` all pass on the EC2 box (all 10 certification steps, with every declared
  player — including the Bedrock-backed `llm` seat — running in the smoke episode), and the player client, global
  viewer, and replay viewer were clicked through in a browser.

## LLM seats (Wave 2)

![llm conditions](results/fig_llm_conditions.png)

Setup: 8 LLM seats per episode, 30 rounds, 10 episodes per condition, `--parallel-episodes 4` on an EC2 box using
Bedrock InvokeModel (haiku 4.5 unless noted; sonnet 4.5 for the monoculture/mixed conditions). Every episode row is
in `results/llm_runs.jsonl`; full replays with chat transcripts in `results/llm_replays/`. 14,400 model calls, 3
failures (all transient throttles counted as passes), 0 sanctions fired anywhere in the sweep.

| condition | n | welfare % of optimum | survival | median collapse | synchrony | sanctions/ep |
| --- | --- | --- | --- | --- | --- | --- |
| open-meadow (ledger + chat) [haiku] | 10 | 28.7% ± 0.7 | 0/10 | 5 | 0.98 | 0 |
| open-meadow [sonnet] | 10 | 27.7% ± 0.1 | 0/10 | 4 | 0.97 | 0 |
| mixed-models (4 haiku + 4 sonnet) | 10 | 28.6% ± 0.9 | 0/10 | 5 | 0.95 | 0 |
| no-chat (ledger only) [haiku] | 10 | 40.6% ± 17.3 | 0/10 | 4 | 0.83 | 0 |
| anonymous (chat only) [haiku] | 10 | 82.8% ± 27.0 | 8/10 | 6 | 0.98 | 0 |
| institutions (ledger + sanctions + posted quota) [haiku] | 10 | 96.7% ± 0.0 | 10/10 | — | 1.00 | 0 |

### Finding 6 — LLM societies don't die of greed; they die of a synchronized arithmetic error

Every open-meadow episode follows the same script: all eight seats open "conservatively" at 2/round, watch the
ledger confirm everyone chose 2, and then celebrate the number as a norm while the stock drains 60 → 54 → 46 → 37 →
27 → 15 → dead by round 5. Sustainable aggregate is ~8.75/round; they harvest 16. The chat transcripts show seats
*computing the decline and still calling it equilibrium*:

> r2 P0: "Stock at 53.66/100 is still healthy. Last round: 15 total harvested with regrowth ~9.1, net decline of
> ~5.9. Susta[inable]" — then six rounds of "perfect cooperation maintained" until "CRITICAL: Stock has collapsed
> to 0.0".

Synchrony is 0.98: this is the correlated-failure mode from Anthropic's multiagent note, but with a twist — the
agents aren't defecting in sync, they're *cooperating in sync on the wrong number*. Group harmony is exactly what
kills them.

### Finding 7 — the public ledger is a conformity amplifier, not an accountability tool

The cleanest contrast in the sweep: removing the ledger (anonymous, chat only) takes survival from 0/10 to **8/10**
and welfare from 28.7% to 82.8%. With individual harvests visible, the round-1 modal choice becomes social proof —
the one seat that computed the right quota conforms *upward*:

> r2 P2 (open-meadow): "I harvested conservatively at 1, but most players harvested 2. Adjustin[g]"

Anonymous seats see only the aggregate, anchor on their own arithmetic, and settle at 1/round (the stock *grows*:
59.75 → 60.49 → 61.21). Transparency without enforcement made things strictly worse — the mirror image of scripted
Finding 3, where the ledger was useless without sanctions but at least not harmful. Chat still matters: silent
societies (no-chat) all collapse too, so cheap talk plus anonymity is the cheapest working configuration.

### Finding 8 — institutions work perfectly, and the active ingredient is the posted number

The full Ostrom kit (ledger + sanctions + posted quota "1 per player per round") survives 10/10 at 96.7% of optimum
with **zero variance and zero sanctions fired in 300 rounds**. Where scripted enforcement was ruinously expensive
(Finding 4's punishment wars), LLM enforcement is free — the threat alone suffices. But the transcripts suggest the
sanction threat isn't even the load-bearing part: seats quote the norm, not the punishment —

> r1 P4 (institutions): "Following the posted quota of 1 per player to keep the meadow alive."

The posted quota solves the coordination problem that open-meadow societies fail at — it replaces the emergent wrong
number (2) with an authoritative right one (1). An obvious follow-up (norm text alone, no sanctions) would separate
deterrence from anchoring; the sweep's 2×2 wasn't designed to.

### Finding 9 — model diversity is not a public good here; capability isn't either

Sonnet monocultures collapse *faster* than haiku (round 4 vs 5) with near-zero variance (27.7% ± 0.1) — more
capability produces a more deterministic version of the same failure. And the 4+4 mixed condition (28.6%, 0/10)
refutes the diversity hypothesis for this game: synchrony barely drops (0.95). The transcripts show why — sonnet
seats open with confident, well-written proposals *for the fatal quota*:

> r1 P1 (mixed, sonnet seat): "Hello everyone! Let's work together to sustain the meadow. I propose we each harvest
> 2 per round initially - this keeps us safely above coll[apse]"

while haiku seats that computed the right answer ("sustainable harvest is around 0.5 per player", P2) conform to the
louder proposal. Diversity fails because persuasiveness and correctness are uncorrelated: the mixed society inherits
sonnet's confident error, not haiku's occasional correctness. Scripted Finding 5 said random variance isn't
diversity; Wave 2 adds that model diversity isn't either — what would break the correlation is *epistemic*
independence, and chat destroys it in one round.

Reproduce everything: `run_scripted_experiments.py` (deterministic), then `run_llm_experiments.py` (needs model
credentials), then `analyze.py`. See the repository README for setup.
