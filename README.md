# ygo-harness

An LLM agent and benchmark for Yu-Gi-Oh, built directly on the game's real rules engine.

> **Status: M1 complete.** The engine builds on Apple Silicon, duels run end to
> end, determinism is proven, and a two-model hierarchical agent plays full
> duels for under a cent each. Exported `.yrp` replays open and play back in
> EDOPro. No benchmark yet — `search/` and `bench/` are still empty.

```
50 full duels in 0.39s  ->  7.9 ms/duel, 127 duels/sec
~989 engine steps per duel -> 125,631 steps/sec
same seed -> byte-identical message stream
diff seed -> genuinely different duel
```

## Why this exists

Yu-Gi-Oh is the hardest mainstream TCG nobody has pointed an LLM at. Pokémon TCG has PTCG-Bench,
Magic has UrzaGPT and a causal-RL gym. Yu-Gi-Oh has exactly one serious AI attempt — [ygo-agent][],
pure RL — which cost 32× RTX 4090 for 5 days / 100M games, covers a narrow deck set, and produces a
policy that cannot explain a single decision.

This project takes the other road: an LLM harness on top of `ygopro-core`, the actual C++ rules
engine that EDOPro and every other simulator runs on.

## The bet

**The engine hands you a legal-action menu at every decision point.** You do not read a screen, you
do not validate moves, you do not recover from illegal actions — the agent returns an index into a
menu the engine built. Everything that remains is planning under interruption, which is the part
worth studying.

The common objection to LLMs playing Yu-Gi-Oh is that they will hallucinate rulings and fabricate
card interactions. [Can Large Language Models Master Complex Card Games?][cardgames] documents
exactly that across Dou Dizhu and Mahjong. Three of its four reported failure modes are
architecturally excluded here:

| Reported failure mode | Status here |
|---|---|
| Rule violations, invalid moves | **Impossible** — no channel exists to express one |
| Hallucinated card interactions | **Delegated to the engine** — search executes and reports ground truth |
| Large discrete action-space mishandling | **Bounded** — an index into ~5–25 options |
| Hidden information | **Real and unfixed** — a genuine limitation |

## Yu-Gi-Oh is not solitaire

An early version of this design assumed combo lines have canonical correct sequences that could be
scored by line-matching. That is wrong. You commit an action, the engine resolves it, the engine
tells you whether the opponent chained, and only then do you choose again — possibly spending
resources to answer the interruption, possibly rerouting, possibly ending with nothing.

So ground truth is **computed, not authored**. For a given (hand, interruption schedule),
engine-backed search yields the best achievable value `V*`; the agent scores `V`; the metric is
**regret = V\* − V**. This handles "you got Ashed, so a weaker board was correct" natively.

**The search is the referee, not just a stronger agent.**

## What M0 established

- **ygopro-core builds on arm64 macOS** and exports all 13 `OCG_*` functions.
  `scripts/build_core.sh` reproduces it; see the header comment for the two
  upstream traps (stale `meson.build`, and Lua having to be compiled as C++).
- **Replay-based state restore is cheap.** At ~126k engine steps/sec, replaying
  a turn prefix to reconstruct a node costs single-digit milliseconds. The
  search layer is affordable.
- **The engine does not shuffle.** `Processors::Startup` draws `start_count`
  cards off the back of the main deck and nothing more; shuffling is the
  client's job. So reproducing a duel needs *two* seeds - one for the deal, one
  for the engine's in-duel randomness. The upside is that the deal is ours to
  control, which is exactly what sealed benchmark hands require: order the list
  and you have dealt an exact opening hand.
- **The current card pool covers the target deck.** All 36 distinct cards in the
  Sky Striker list resolve in BabelCDB with Lua scripts present, including every
  card newer than the assistant's knowledge cutoff.

## What M1 added

- **A two-model agent** (`agents/hierarchical.py`): a planner that thinks, and
  an executor that only picks an index. Board state via the engine's query
  API, with hidden information masked once, in `render.py`.
- **The cost model in the plan was wrong by ~10x, in our favour.** Board state
  costs ~170 tokens per decision, not ~2,000; a duel costs **$0.004–0.013**,
  not $0.25. Cost is dominated by the model's own reasoning output, so
  reasoning length is the only dial that matters. Full duels are affordable.
- **`.yrp` replay export**, verified. EDOPro does not store a picture of a
  duel — it re-simulates one from the seed and feeds the recorded responses
  back into its own core. So `scripts/verify_yrp.py` replays an exported file
  through EDOPro's *own* core, card database and Lua scripts, which is the
  client's code path minus rendering. Duels are watchable in the real client,
  with card art, for no rendering work of ours.

The corollary is worth stating: because the client re-simulates, **a replay is
only as portable as the card scripts it was played with**. A client whose
scripts differ from `data/DATA_COMMITS` can desync mid-duel — which is not a
bug in the file. See `DECISIONS.md`.

## Puzzles as a free stress test

EDOPro ships a puzzle collection: each script fixes a hand and field and
demands a win in one turn. The win condition is enforced by the engine —
`aux.BeginPuzzle()` registers an end-of-turn effect that sets the solver's life
points to zero — so **solved/unsolved is the duel's own verdict**, with no
value function, no search referee and no authored solution to diff against.

```
239 playable puzzles (219 of 458 are Rush Duel, a different ruleset)
239 ran clean  ->  100%    the harness number
  0 harness faults, 0 messages answered generically
```

Read the *ran clean* number, not the solved count.

Getting there took four missing decision types and two wrong response formats.
The instructive part is how they presented: a message the loop does not
recognise never becomes the pending decision, so the policy keeps answering the
*previous* question and the engine keeps replying `MSG_RETRY` without restating
anything. Nine failures were therefore reported as format bugs in
`MSG_SELECT_CARD`, `MSG_SELECT_CHAIN`, `MSG_SELECT_PLACE` and
`MSG_SELECT_YESNO` — none of which was actually at fault. The set of blocking
messages is now derived from `playerop.cpp` in a test, and the loop raises
rather than answering into the void.

`python scripts/run_puzzles.py` plays them with the random-legal policy, so
this costs nothing. The number that matters is how many the harness could
*run*: a puzzle the agent loses is a puzzle the agent lost, while a puzzle that
raises or stalls is a bug in `engine/`. The two are reported separately and
never summed.

Puzzles are a **debug tool, not the benchmark**. They have no live opponent, so
they test single-turn combo execution and say nothing about planning under
interruption — which is the thesis. `bench/` stays sealed.

### What the puzzles found

Running them turned up six harness defects, and only two were what the error
message said. Four blocking messages were missing from the decision table, and
a missing blocking message does not present as an unhandled message — the loop
never updates the pending decision, so the policy answers the *previous*
question forever and the failure is reported against whatever happened to be
pending.

That pattern is why the project stopped hunting gaps duel by duel.
`scripts/coverage_report.py` walks the vendored core instead and reports what
it can tell us against what we use:

```
QUERY fields   19/26 requested      (was 5/26)
MESSAGES       76/76 named          (was 29/76)
               39/72 reach the agent
```

The first audit found that Level, Rank, Attribute, Link rating and markers,
base ATK, Xyz materials, counters, equips and negation status were never
queried at all — so a monster whose Level an effect had changed was reported
at its printed value, and a negated monster looked ordinary. It also found
that `MSG_SELECT_CARD` was being misparsed: the core writes a 10-byte
`loc_info` per entry and we skipped 4, so every candidate after the first was
read out of the middle of the previous one. Nothing raised, because the engine
acts on the index the agent returns rather than the name.

### Where the agent actually is

```
Master Rule 5 puzzles:  2 / 20 solved     (random-legal: 0 / 20)
                       20 / 20 run clean
```

The second was `Home of the Fiends`, and getting there took four fixes that
were all the same fix: state the engine reported and the harness discarded.
The agent was never told which phase of the turn it was in, so it planned an
attack from Main Phase 2 and declined a free direct attack to carry it out.
The graveyard was truncated to six cards, the banished pile was never shown,
and the Extra Deck was a count rather than a list. Its plans were also never
checked against the opponent's life total, which the engine knows - so it
executed a line that dealt 200 into 2400.

Fixed, it finds the intended solution: clear both monsters, Normal Summon,
Monster Reincarnation to retrieve Dark Necrofear from the graveyard, Special
Summon it, and attack for lethal.

Card text and full stats, field zones, battle position, engine events and
all-planner routing have each been fixed, and **none of them moved the solve
rate**. That is worth stating plainly: the remaining gap is not obviously an
information gap.

That held until the one decision that mattered was read closely, at which
point it stopped holding - see `docs/PLAN.md`. The agent had never been told
which phase of the turn it was in, planned an attack from Main Phase 2 (which
is impossible), and declined a free direct attack to carry the plan out. With
the phase shown and turn structure in the primer it attacks, and dealt this
puzzle its first damage in any run.

The scan below is kept because its method was sound and its conclusion was
not: it sampled the model's mechanics claims, found them individually correct,
and never checked turn structure.

Scanning 368,000 characters of the agent's own reasoning supports that. Its
statements about the rules are correct - it knows you cannot Normal Summon in
Main Phase 2, it quotes card text accurately. What it doubts is our
presentation: classifying every "wait, …" self-correction put **49% on the
board or the interface** and only 20% on rules. After the fixes above, on a
current run, interface doubt is down to 35% and unresolved card codes from 200
to 0. So a rules primer would spend tokens on the one thing that is not
broken.

## Layout

```
engine/   ctypes bindings to ygopro-core + MSG_* decoders + text renderer
llm/      one OpenAI-compatible adapter: OpenRouter | Ollama | LM Studio | llama.cpp
search/   replay-based state restore, DFS/MCTS, value function
agents/   free-for-all: hierarchical LLM agent, search-guided agent, baselines
bench/    SEALED: eval splits, interrupt schedules, scoring protocol, results
viz/      terminal live view + .yrp replay export
data/     cards.cdb + scripts, pinned by commit hash
```

`agents/` and `bench/` are deliberately separated. Overfitting is a virtue in one and a sin in the
other; eval splits are sealed and hashed before any agent tuning begins.

## Data sources

Tournament data for the Edison format (`edison/topdeck/`) is
**data provided by [TopDeck.gg](https://topdeck.gg)** through its
[tournament API](https://topdeck.gg/docs/tournaments-v2). Only derived data is committed
(deck contents, results, pseudonymous player keys - no names); raw responses stay in the
gitignored `edison/.cache/`. Fetching needs a free API key as `TOPDECK_API_KEY` in `.env`.

The Edison card pool and March 2010 banlist come from [edisonformat.net](https://edisonformat.net);
release dates for the cross-check from [YGOPRODeck](https://ygoprodeck.com).

## License

**AGPL-3.0.** Not a choice — `ygopro-core` is AGPL and this links it.

[ygo-agent]: https://github.com/sbl1996/ygo-agent
[cardgames]: https://arxiv.org/abs/2509.01328
