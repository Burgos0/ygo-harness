# Status - parked 2026-09-30

Handoff for whoever picks this up next (probably me). Everything measured is in `docs/EXPERIMENTS.md`
with its conditions; traps that cost a debugging session are in `CLAUDE.md`; design choices in
`DECISIONS.md`.

## Roadmap

| Step | What | Status |
|---|---|---|
| 1 | Engine: ygopro-core bindings, Edison 2010 rules layer, card pool, banlist, errata | **done** |
| 2 | One pilot (Lightsworn): lookahead + scoring, beats random-legal | **done** |
| 3 | Second pilot (Blackwing-DAD) + first real matchup against TopDeck.gg data | **done** - closed with a documented +15-20 point gap |
| 4 | All 6 pilots + round-robin | **in progress** - 3 of 6 pilots (Lightsworn, Blackwing-DAD, Blackwing) |
| 5 | Optimizer (deck / tech choices against the simulated metagame) | not started |

## Current results

Three pilots on the generic lookahead pilot, each with a deck profile. Vs random-legal, 200 duels each:
Lightsworn 97.5%, Blackwing-DAD 98.5%, Blackwing 99.5%; 0 rejected answers, 0 random fallbacks.

Matchups with **consensus decklists** (`edison/decks/<deck>_consensus.ydk`: modal copy counts over the
archetype's lists with a winning record), 200 Bo3 each, same seeds, the first-named deck's match win:

| Matchup | Simulated [95% CI] | Real, TopDeck.gg [95% CI] | Gap |
|---|---|---|---|
| Lightsworn vs Blackwing-DAD | 60.0% [53.1, 66.5] | 45.1% [40.4, 50.0], n=411 | +14.9 |
| Blackwing vs Lightsworn | 77.5% [71.2, 82.7] | 54.3% [49.2, 59.3], n=376 | +23.2 |
| Blackwing vs Blackwing-DAD | 78.5% [72.3, 83.6] | 48.6% [44.5, 52.7], n=580 | +29.9 |

**The simulated tier order is roughly the reverse of reality.** Simulated: Blackwing > Lightsworn >
Blackwing-DAD. Real: Blackwing-DAD wins both its matchups (54.9% vs Lightsworn, 51.4% vs Blackwing) and
Blackwing beats Lightsworn narrowly.

What has and has not moved the numbers: one structural change moved a matchup a lot - response search
(the pilot playing the opponent's turn), 81.0% -> 58.8%. Five later changes (evaluation upgrade, hold
scaling, two tuning rounds, the random-fallback fix) and switching to consensus lists each flipped
25-30% of individual matches on the same seeds without moving any rate beyond noise.

## Known sim biases

See the "Known sim biases" section of `docs/EXPERIMENTS.md`. In short:
- **The lookahead assumes a passive opponent.** Copies and forks let the opponent do nothing, so a deck
  that wins on its own turn is valued correctly and a deck that wins by answering the opponent is not.
  This is the likely reason the tier order is reversed: the most reactive deck (Blackwing-DAD) loses
  every simulated matchup, the most proactive (Blackwing) wins every one.
- No side decking in games 2-3.
- One decklist per deck, where the real data has hundreds of builds.
- Player-skill selection in the real data.

## Next step: an opponent model in the lookahead

Replace the passive opponent in copies and forks with a sampled one:
- the opponent's face-down cards and hand are sampled from **their consensus list** (minus what is
  public), instead of an inert placeholder;
- the opponent answers with **cheap greedy responses** (fixed rules: chain a trap when it would destroy
  or negate something, attack when it wins a battle), not a search;
- every candidate is scored as the **average over K = 3** samples.

Pass bar: the simulated tier order moves toward reality (Blackwing-DAD's matchups improve relative to
Blackwing's). Budget: **2 sessions**. If it does not move the order, stop and write up why before
building pilots 4-6.

Costs to expect: K = 3 samples triples lookahead time (currently ~45 matches/min on 8 cores).

## Step 4 exit criteria

- Tier order roughly right against the TopDeck matchup matrix.
- Every matchup gap within 15-20 points.
- `tests/test_decisions.py` passes.
- 0 random-fallback answers per game (every run report prints it).

## Remaining pilots

Frog Monarchs, Machina, Gladiator Beasts - the other three of the six largest archetypes. Each needs a
consensus list (`python -m edison.consensus <stem> "<Archetype>"`), a profile in `agents/profiles.py`
(ideally from an expert guide, saved under `docs/guides/`), the >= 90% vs-random checkpoint, and at
least one decision test.

## Commands

Setup (once):

```bash
brew install cmake lua@5.4 meson ninja pkg-config
./scripts/build_core.sh && ./scripts/fetch_data.sh
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install pytest openai rich pyyaml
```

Tests (the EDOPro-backed ones skip silently unless `EDOPRO_DIR` points at an install; on this machine
it is the system-wide `/Applications/ProjectIgnis`):

```bash
EDOPRO_DIR=/Applications/ProjectIgnis .venv/bin/python -m pytest tests/ edison/tests -q
```

A pilot vs random-legal (the checkpoint every new pilot must pass; ~1 minute on 8 cores):

```bash
.venv/bin/python -m edison.pilot_eval --profile blackwing --duels 200 --tag check
```

A matchup, 200 Bo3 on the fixed seeds, consensus lists (~5 minutes):

```bash
.venv/bin/python -m edison.matchup --a lightsworn --b blackwing_dad --matches 200 --tag check --deck-variant consensus
```

Both print progress, the result with a 95% CI beside the TopDeck number, rejected answers and random-
fallback answers per game, and write one JSON line per duel/match with its seeds to `runs/`
(gitignored). Loss replays are verified against EDOPro's own engine and copied to its replay folder.
Other tools: `edison.response_report` (trap timing), `edison.dad_report` (Blackwing-DAD guide metrics),
`edison.fallback_audit`, `edison.export_games`, `scripts/capture_positions.py` (new decision tests).
