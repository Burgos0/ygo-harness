# ygo-harness

A Yu-Gi-Oh! simulator and AI pilots for the **Edison format** (the March 2010 metagame), built directly on
`ygopro-core` - the real C++ rules engine behind EDOPro - and checked against thousands of real tournament
matches from TopDeck.gg.

> **Status: parked** (2026-09-30). Steps 1-3 of 5 done, step 4 in progress. Handoff and next steps:
> [`docs/STATUS.md`](docs/STATUS.md). Every measurement, with its conditions: [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).

## What it does

Three deck pilots play full Edison duels against each other on the real engine, thousands of games per
run, and the simulated matchup win rates are compared with real tournament results (8,852 TopDeck.gg
matches with both decklists known). The goal is a simulated metagame good enough to optimize decks
against; the finding so far is where and why it is not yet.

## Architecture

```
ygopro-core (C++, vendored)      the official rules engine; we never re-implement a ruling
  engine/                        ctypes bindings, message decoding, board queries, .yrp replay export
  edison/                        Edison layer: 2010 rules preset, card pool, banlist, April-2010 errata
                                 as script overrides, TopDeck.gg data -> decklists and a matchup matrix
  agents/lookahead.py            ONE generic pilot, no card names in it
  agents/profiles.py             per-deck profiles: weights, key cards, setup progress (Vayu, Judgment Dragon...)
  edison/pilot_eval.py, matchup.py   parallel runners: vs random-legal, and Bo3 matchups vs the real numbers
```

- **Generic pilot + deck profiles.** For each Main/Battle Phase decision the pilot builds a copy of the
  position from what that player may know (hidden cards replaced, own Deck order reshuffled), plays each
  candidate to the end of the turn, and scores the result: card advantage, a nonlinear life-point value,
  threat-weighted board, holding value for unused traps. Everything deck-specific is a profile.
- **Response search.** Chain windows on the opponent's turn and in battle are searched too, on *forks*:
  the real duel replayed from its seeds and response log to the prompt, then scrubbed of hidden
  information with the engine's own `Card.Recreate` before any candidate is tried.
- **Decision tests.** Recorded real positions with the answer the pilot must give (e.g. Solemn Judgment
  must negate a Synchro boss, and must not be spent on a 400-ATK monster), replayed from the log.
- **No random choices.** An audit found four prompt types silently answered by the random fallback
  (Synchro materials, Tributes, zones, Card Trooper's count); each now has a real rule, and every run
  report counts fallback answers per game (0).
- **Reproducible.** Every duel is (seeds, response log). Exported replays are verified byte-for-byte
  against EDOPro's own engine and open in the real client.

## Key results

| | |
|---|---|
| Raw engine | 127 random-vs-random duels/s single-threaded (M3 Air) |
| Pilot throughput | ~4 pilot-vs-random duels/s, ~45 Bo3 pilot-vs-pilot matches/min on 8 cores |
| Pilots vs random-legal (200 duels) | Lightsworn 97.5%, Blackwing-DAD 98.5%, Blackwing 99.5%; 0 rejected answers |

**Simulation vs reality** (200 Bo3 each, consensus decklists, first deck's match win, 95% CIs):

| Matchup | Simulated | Real (TopDeck.gg) |
|---|---|---|
| Lightsworn vs Blackwing-DAD | 60.0% [53.1, 66.5] | 45.1% [40.4, 50.0] |
| Blackwing vs Lightsworn | 77.5% [71.2, 82.7] | 54.3% [49.2, 59.3] |
| Blackwing vs Blackwing-DAD | 78.5% [72.3, 83.6] | 48.6% [44.5, 52.7] |

What the validation found:
- Making the pilot play the **opponent's turn** (response search) was the one change that moved a
  matchup a lot: Lightsworn vs Blackwing-DAD went from 81% to 59% as traps stopped firing at the first
  opportunity.
- After that, five evaluation and tuning changes, and switching to consensus decklists, each changed
  25-30% of individual games on the same seeds but **none moved a win rate beyond noise** (paired tests
  on fixed seeds).
- The simulated **tier order is roughly reversed** from reality: the most proactive deck wins every
  simulated matchup, the most reactive loses every one. The likely cause is structural - the lookahead
  assumes an opponent who never responds - and fixing that is the next step.

## Limitations

- The lookahead's opponent is passive; that biases the simulation toward proactive decks.
- No side decking; one decklist per archetype; the real data includes player skill.
- 3 of 6 pilots built. Most numbers are n = 200 Bo3 per condition.

## Running it

```bash
brew install cmake lua@5.4 meson ninja pkg-config        # macOS
./scripts/build_core.sh && ./scripts/fetch_data.sh        # engine + card data
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install pytest openai rich pyyaml

python -m pytest tests/ edison/tests -q                   # EDOPro-backed tests need EDOPRO_DIR
python -m edison.pilot_eval --profile blackwing --duels 200 --tag demo
python -m edison.matchup --a lightsworn --b blackwing_dad --matches 200 --tag demo --deck-variant consensus
```

## History

The repo began as an LLM agent harness for Yu-Gi-Oh (a planner/executor model pair, EDOPro puzzle runs,
`.yrp` export); that phase's write-up is in [`docs/HISTORY-llm-harness.md`](docs/HISTORY-llm-harness.md)
and `docs/PLAN.md`. Card data and scripts: ProjectIgnis. Tournament data: [TopDeck.gg](https://topdeck.gg).
