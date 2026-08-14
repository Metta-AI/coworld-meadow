# Meadow

Meadow is a **social-pressure Coworld**: a round-based commons game built to measure how societies of LLM agents
handle a shared, destructible resource — and how institutions (reputation, costly punishment, posted norms,
communication) change the outcome. It follows up Anthropic's
["Patterns and problems in emerging multiagent systems"](https://www.anthropic.com/research/multiagent-systems)
with a small, exactly-solvable environment where conformity, coordination, and enforcement can be measured against a
computed social optimum.

**Read the write-up:** [The meadow test: how LLM societies kill a commons they're trying to save](docs/blog-post.md).
Full per-condition numbers live in [experiments/RESULTS.md](experiments/RESULTS.md); every episode row, replay (with
complete chat transcripts), and figure is committed under [experiments/results/](experiments/results/).

![llm conditions](experiments/results/fig_llm_conditions.png)

## The one-paragraph result

Societies of 8 Claude seats almost never die of greed. They converge on a plausible-but-wrong harvest quota in round
one, watch the public ledger confirm that everyone chose the same number, and then defend the number as a norm —
narrating "perfect cooperation" while the stock drains to zero. Removing the public ledger takes survival from 0/10
to 8/10 episodes; a posted quota (backed by never-used sanctions) takes it to 10/10 at 96.7% of the exact optimum;
and a mixed haiku+sonnet population inherits the *most confident* seat's error, not the most correct seat's answer.

## Repository layout

- `src/coworld/examples/meadow/` — the complete Coworld: pure engine, round-barrier websocket game server, browser
  clients (player / global / admin / replay), scripted + LLM player policies, grader, Dockerfile, and manifest
  template. The layout mirrors the [coworld](https://github.com/Metta-AI/coworld) package's examples tree.
- `experiments/` — the sweep drivers (`run_scripted_experiments.py`, `run_llm_experiments.py`), analysis
  (`analyze.py`), findings (`RESULTS.md`), and all collected data (`results/`).
- `tests/` — engine and protocol tests.
- `docs/blog-post.md` — the long-form write-up.

## Run it

The engine is dependency-light (`pip install -r requirements.txt`); the containerized path needs Docker and the
[`coworld`](https://pypi.org/project/coworld/) CLI (`pip install coworld`).

```bash
# Deterministic scripted sweeps (no credentials, no containers; ~seconds)
PYTHONPATH=src python experiments/run_scripted_experiments.py
PYTHONPATH=src python experiments/analyze.py

# Engine tests
PYTHONPATH=src python -m pytest tests/ -v

# Build, play in a browser, and certify the containerized Coworld
coworld build --project src/coworld/examples/meadow --version 0.1.0
coworld play src/coworld/examples/meadow/dist/coworld_manifest.json
coworld certify src/coworld/examples/meadow/dist/coworld_manifest.json

# LLM-seat sweeps (needs AWS Bedrock InvokeModel credentials, or ANTHROPIC_API_KEY)
PYTHONPATH=src python experiments/run_llm_experiments.py --conditions open-meadow --episodes 1 --rounds 5
```

`coworld play` prints one player-client link per seat (harvest buttons, sanction picker, chat), a global viewer, and
an admin link (pause/resume, round deadline). See
[src/coworld/examples/meadow/README.md](src/coworld/examples/meadow/README.md) for game rules, treatment dials, and
role contracts.

## Provenance

Developed in the [Metta-AI/metta](https://github.com/Metta-AI/metta) monorepo as
`packages/coworld/src/coworld/examples/meadow`; this repository is the public home of the game and its results. The
LLM sweep (60 episodes, 14,400 model calls) ran 2026-08-14 on claude-haiku-4.5 and claude-sonnet-4.5 via AWS Bedrock.
