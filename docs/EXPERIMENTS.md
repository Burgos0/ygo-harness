# Experiments

Running log of what has actually been measured. Newest first.

Rules for this file, so it stays worth reading:

- **Record the conditions, not just the number.** A solve rate without the
  model, the puzzle and the harness commit is not a result.
- **Record failures and dead ends too.** Most of the entries below are things
  that did not work, and they are the reason the next person does not retry
  them.
- **Say the sample size.** Almost everything here is n=1. Say so, and do not
  write conclusions a single run cannot support.

---

## Model comparison on Master Rule 5 puzzles (2026-08-25)

Three models, both roles on one model per run, thinking left at each model's
default. `scripts/run_puzzles.py --model <id> --filter <puzzle>`.

### Home of the Fiends (2/10) — one run each, sequential

| model | result | secs | decisions | plan | re-plans | out tok | cost |
|---|---|---|---|---|---|---|---|
| `google/gemini-3.7-flash` | **solved** | 254 | 17 | 5/7 | 2 | 35,818 | $0.085 |
| `anthropic/claude-haiku-4.5` | unsolved | 144 | 13 | 4/22 | 0 | 13,776 | $0.138 |
| `qwen/qwen3.7-flash` | unsolved | 532 | 12 | 3/5 | 2 | 112,617 | $0.015 |

### Seto VS Ishizu (4/10) — one run each, before the deck/menu fixes

| model | result | secs | decisions | plan | re-plans | out tok | cost |
|---|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-4.5` | unsolved | 199 | 25 | 3/8 | 2 | 18,482 | $0.208 |
| `google/gemini-3.7-flash` | unsolved | 359 | 38 | 7/8 | 2 | 31,510 | $0.109 |
| `qwen/qwen3.7-flash` | unsolved | 768 | 16 | 3/4 | 2 | 154,092 | $0.021 |

**What these support, and what they do not.** n=1 per cell, and run-to-run
variance is known to be large - qwen solved Home of the Fiends earlier the
same day under a bounded reasoning budget and failed it here. So:

- Supported: gemini produced a solve on the first attempt where the others did
  not; qwen is 5-10x cheaper than either; nothing solved Seto.
- **Not** supported: any ranking of these models by capability. Three runs are
  three anecdotes.

**Cost is not capability.** qwen wins cost by an order of magnitude and is the
only one that caches at these prompt sizes, but it also generated 3-8x more
output than the others and lost both puzzles. Choosing it is a cost decision,
and should be written down as one.

---

## Prompt caching by model (2026-08-25)

Two identical calls through OpenRouter, checking `cache_write_tokens` and
`cached_tokens`. **The harness sends an Anthropic-style `cache_control`
breakpoint on the system prompt** (`Provider.cache_system`); without it
nothing is written to cache at all.

| model | ~1.5k tok | ~3k | ~5k | ~9.9k |
|---|---|---|---|---|
| `qwen/qwen3.7-flash` | caches | caches | caches | caches |
| `google/gemini-3.7-flash` | no | no | no | no |
| `anthropic/claude-haiku-4.5` | no | no | no | caches |

Measured economics on a 9,926-token system prompt:

| | first call | second call |
|---|---|---|
| haiku | $0.012429 (write) | **$0.001030** (read) |
| qwen | $0.000335 (write) | **$0.0000291** (read) |

**Consequence for reading any cost number here.** Puzzle system prompts are
small - Home of the Fiends builds 1,497 tokens, Seto 2,330 - so gemini and
haiku costs in this file are entirely uncached and will stay that way until
the card corpus is much larger. The Sky Striker duel corpus (~3,900 tokens)
is the case where this starts to matter.

---

## Provider prices, OpenRouter, 2026-08-25

Fetched live from `/api/v1/models`, per 1M tokens. These drift; refetch rather
than trusting this table.

| model | in | out |
|---|---|---|
| `mistralai/mistral-nemo` | $0.019 | $0.030 |
| `qwen/qwen3.7-flash` | $0.030 | $0.130 |
| `google/gemini-3.7-flash` | $0.375 | $1.875 |
| `anthropic/claude-haiku-4.5` | $1.00 | $5.00 |
| `anthropic/claude-sonnet-5` | $2.00 | $10.00 |
| `openai/gpt-5.2` | $1.75 | $14.00 |
| `anthropic/claude-opus-5` | $5.00 | $25.00 |

Output dominates: a puzzle runs roughly 25k in / 30k out, so the output rate
is what decides cost.

---

## What "default" reasoning actually means (2026-08-25)

qwen3.7-flash, same planning question, only `max_tokens` changed. No
`reasoning` block — the model's own default.

| `max_tokens` | output tokens | reasoning chars | finish reason |
|---|---|---|---|
| 2,048 | 2,050 | 7,052 | **length** — cut off |
| 8,192 | 8,194 | 29,027 | **length** — cut off |
| 32,768 | 3,024 | 11,471 | **stop** — finished on its own |

**Default is adaptive and self-terminating, not unbounded.** Given room it
stopped at 3,024 tokens. Below that it does not think less — it is truncated
mid-thought and returns *empty content*, which is worse than a small explicit
budget because you get no answer at all rather than a shallow one.

Two consequences:

- `max_tokens` is the real limiter, not the reasoning setting. Raising it from
  2,048 to 32,768 is what let per-puzzle output grow to 112k-154k tokens.
- The figure recorded in `llm/models.yaml` as "default -> 1,331 output tokens"
  was measured under a 2,048 cap. It was a truncation artifact, not the
  model's natural length.

**Open, and worth fixing:** the executor runs at `max_tokens: 8192`, which
truncated in this test. It answers easier questions than the planner so it may
not bite in practice, but `stats.truncated` is the number to watch.

## Summoning costs in the primer (2026-08-25)

`Home_of_the_Fiends` (2/10, MR5). Four planners, one planning call each, same
prompt before and after adding Tribute costs to `RULES_PRIMER`.

The error the primer targets: three of four models planned "Normal Summon
Zanki" as a free action and then attacked with La Jinn — the monster the
Tribute consumes. The prompt already said `Zanki … Level 5`. Nothing said what
a Level *costs*, so the datum was present and inert. That is the same failure
shape as Main Phase 2 and as the graveyard past six cards: not bad reasoning,
missing state or missing rule.

| planner | before | after |
|---|---|---|
| sonnet | Zanki free -> claimed 3300, unreachable | **correct, 3700** |
| gemini-3.7-flash | correct | **correct, 3700** |
| qwen3.7-flash | illegal line | legal, plans 2000 vs 2400 — no lethal |
| haiku-4.5 | illegal line | *"I cannot find a winning line"* |

Nobody proposes the illegal line any more. Sonnet and gemini converged
independently on the same solution by different orderings, which is the
strongest signal available that it is the authored one — these puzzles ship no
solution to diff against.

**The floor rose; the ceiling did not.** The two cheap models stopped being
wrong and started being stuck. That is worth something — the executor will
walk a confidently wrong plan straight into a loss — but it is not a solve.

**It costs latency.** sonnet 142s -> 313s (30k reasoning chars), qwen 44s ->
94s (42k). The primer makes models think harder, and 313s of planning alone
eats a 5-minute budget.

### End to end, four runs

gemini-3.7-flash, hierarchical split (*not* `--all-planner`) — the
configuration that previously lost this solve.

| run | outcome | seconds | plan steps | out of order |
|---|---|---|---|---|
| 1 (solo) | solved | 212 | 6/6 | 2 |
| 2 | solved | 185 | 6/6 | 2 |
| 3 | solved | 283 | 6/7 | 2 |
| 4 | solved | 297 | 6/7 | 3 |

4/4, mean 244s, max 297s. Runs 2-4 ran three-way parallel and run 2 was the
*fastest* of all four, so the spread is sampling variance rather than
contention. One solve would have been a sample; four is the fix.

Under the 5-minute target — by three seconds at worst. Not comfortable.

**Still unexplained:** every run replans twice and takes 2-3 steps out of
order, including the two that executed 6/6. A plan that has to be rebuilt
twice on a puzzle the agent then solves is not a plan being followed.

### A harness bug found by trying to verify this

The first end-to-end run reported *ran clean 1/1, harness fault 0, no answer
1, solved 0*. There was no key in the shell: `provider.py` fell back to the
literal string `"not-needed"`, failed as a 401 three retries deep, and landed
in `no answer` — the agent-facing column meaning "the model declined to
choose", where a config error is indistinguishable from a useless agent.

Fixed in `ed2432a`: `.env` is read by `provider.py` itself, and
`NotAuthenticated` joins `OutOfCredit` under `FatalProviderError`, which stops
the run. The test asserts the key *resolves*; a "does not raise" test would
have passed against the bug.

## Making the plan execute itself (2026-08-26)

`Home_of_the_Fiends`, gemini-3.7-flash, four runs each side.

The tracker matched every card a step *mentioned*. "Activate Raigeki Break,
discarding Night Assailant, destroying Dark Jeroid" therefore hit three
options in a Main Phase menu, read as ambiguous, and went to the model. The
better a plan described itself, the less it was used — and asking plans to
name their targets, done earlier to *help* the tracker, was suppressing it.
Auto-execution fired once in nineteen decisions.

Steps now carry `actor` (what the step acts with) and `operands` (what it
spends or points at), split at the first cost marker that is not "Tribute
Summon", plus a verb so `summon: Zanki` and `set monster: Zanki` are different
things. `_CardMenu` consults the plan before the model; `is_dead` keys on the
actor, so a step whose *target* was listed no longer reads as available.

| | before | after |
|---|---|---|
| solved | 4/5 | **4/4** |
| seconds | 185, 212, 283, 297 (+185 lost) | **144, 166, 175, 186** |
| mean | 244s | **168s** |
| executor secs | 109 | **27-33** |
| out of order, 4 runs | 9 | **3** |
| decisions taken with no model call | 1 | **6-7** |

**Every auto-taken decision was audited and every one was correct.** In three
of six in run 1 the menu offered the same card under a different verb —
`set spell/trap: Monster Reincarnation` beside `activate:` — which is
precisely what used to read as ambiguous.

**One run at 373s was not a regression.** It appeared between these two sets
and looked like the change had tripled planner time. It was variance: gemini's
planner output ranges 10,798-21,148 tokens across the four runs here. Refusing
to attribute it from n=1 was correct, and n=4 settled it.

**The cost has moved, not vanished.** The planner is now 110-157s of a
144-186s run — roughly 80%. The executor is no longer worth optimising; the
planner is the whole budget. Sub-minute is not reachable by removing executor
calls, because there are barely any left to remove.

**Not fixed:** 3 out-of-order actions remain across 4 runs, all in decisions
the model still makes, and every run still replans twice despite solving.

## Things tried that did not work

**Unbounded planner reasoning made qwen worse.** Removing the 256-token budget
was meant to help it find multi-step lines. It produced 112k-154k output
tokens per puzzle, ran 2-3x longer, and lost a puzzle it had previously
solved. More thinking was not better.

**Routing every decision to the planner cost 14 minutes a puzzle** and did not
change the plan, which is where the reasoning actually happens. Reverted to
the hierarchical split; a puzzle now runs 2-5 minutes.

**A rules primer was argued against on the strength of a bad scan.** A scan of
368k characters of reasoning classified the model's mechanics claims as
correct and concluded rules knowledge was not the gap. It sampled claims and
never checked *turn structure*, which was exactly what was broken - the agent
planned an attack from Main Phase 2. The primer helped. Sampling a category
you did not think to look for proves nothing about it.

## Edison pilots: generic lookahead + profiles, first pilot-vs-pilot matchup (2026-09-29)

Engine-only measurements (no model calls). Edison rules (`EdisonDuel`), both lists from
`edison/decks/`. Logs (one JSON line per duel/match, with seeds) in `runs/` (gitignored).

**Refactor check.** `agents/lookahead.py` (generic) + `agents/profiles.py` (per deck). Lightsworn
profile vs random-legal, 200 duels, alternating seats: **97.0% [93.6, 98.6]** (first 99/100,
second 95/100), 0 rejected answers. The losses are the same six duel keys v2 lost on its first
200 (059, 061, 067, 089, 132, 181), so the refactor is behaviour-identical; v2 was 98.0% over 500.

**Pilot #2 = Blackwing-DAD**, the deck with the most recorded matches vs Lightsworn (TopDeck.gg,
Lightsworn's row; mirrors excluded):

| Lightsworn vs | Matches | Lightsworn W-L-D | Match win % [95% Wilson] |
|---|---|---|---|
| Blackwing-DAD | 411 | 185-225-1 | 45.1 [40.4, 50.0] |
| Blackwing | 376 | 171-203-2 | 45.7 [40.7, 50.8] |
| Frog Monarchs | 312 | 158-151-3 | 51.1 [45.6, 56.7] |
| Machina | 194 | 105-88-1 | 54.4 [47.4, 61.3] |
| Gladiator Beasts | 146 | 74-68-4 | 52.1 [43.9, 60.2] |

(The six pilot decks = the six largest archetypes by deck count in `matchups.md`.)

Blackwing-DAD profile v0 vs random-legal, 200 duels: **95.5% [91.7, 97.6]** (first 94/100,
second 97/100), 0 rejected answers. Checkpoint (>= 90%) passed.

**Lightsworn vs Blackwing-DAD, 500 Bo3** (game 1 alternates by match, loser of a game goes first
next; `python -m edison.matchup --tag v0`): Lightsworn **81.0% [77.3, 84.2]** (405-95), 1221 games,
games 71.5% to Lightsworn, 0 rejected answers, 1216 games ended on LP. Real: **45.1% [40.4, 50.0]**.
**Difference +35.9 points - flagged (> 15).** The going-first player won only 48.4% of games.

Not yet diagnosed. The obvious suspect is pilot skill, not the deck: the Lightsworn profile had three
rounds of replay review and scenario tests, the Blackwing-DAD profile none; and Blackwing-DAD is a
trap/control deck whose value is mostly on the *opponent's* turn, where the pilot does no search at
all (fixed rule: activate the first chainable card). A pilot-vs-pilot number measures the pilots
until both are shown to play their deck competently; it should not be read as a deck result.

## Response search: the opponent's turn searched too (2026-09-29)

Same conditions as above. No profile was tuned. `LookaheadPilot(respond_search=True)` searches every
prompt on the opponent's turn and every chain window / yes-no in any Battle Phase - pass vs each legal
response, then each target - on forks of the real duel (see `DECISIONS.md`). `--no-respond` gives the
old fixed rule ("activate the first chainable card on the opponent's turn") and reproduces the earlier
numbers exactly (95.5% vs random, 81.0% in the matchup, same W-L), which is the before/after control.

**Regression vs random-legal, 200 duels each** (limit: no drop over 3 points):

| Pilot | Before | After | Rejected | Forks/duel (failed) |
|---|---|---|---|---|
| Lightsworn | 97.0% [93.6, 98.6] | **99.0%** [96.4, 99.7] | 0 | 11 (0) |
| Blackwing-DAD | 95.5% [91.7, 97.6] | **99.5%** [97.2, 99.9] | 0 | 72 (0) |

**Lightsworn vs Blackwing-DAD, 500 Bo3, same keys/seeds as the v0 run:**

| | Lightsworn match win [95% CI] | W-L | Games | Going first won |
|---|---|---|---|---|
| Real (TopDeck.gg) | 45.1% [40.4, 50.0] | 185-225 | - | - |
| Before (fixed chain rule) | 81.0% [77.3, 84.2] | 405-95 | 1221 | 48.4% |
| **After (response search)** | **58.8% [54.4, 63.0]** | 294-206 | 1280 | 55.0% |

Gap to the real number: +35.9 -> **+13.7 points**, inside the 15-point flag. Going first became an
advantage (48.4% -> 55.0% of games), which is the direction the real format has.

**Blackwing-DAD's traps, in the matchup** (`python -m edison.response_report`):

| | Before | After |
|---|---|---|
| Trap windows / game | 4.3 | 16.4 (traps are held, so they stay available) |
| Traps activated / game | 2.48 | 2.25 |
| Activated when offered | 57.8% | 13.7% |
| ...on an attack declaration | 60% (742/1240) | 42% (1231/2904) |
| ...at a bare phase change | 57% | 10% |
| Share of activations answering an attack | 25% | **43%** |
| Share in the opponent's Draw Phase | 52% | 35% |
| Solemn Judgment / Torrential Tribute used | 325 / 292 | 146 / 218 |

Before, the fixed rule spent traps at the first window - half of them in the opponent's Draw Phase,
Solemn Judgment on the first thing it could negate. After, traps are mostly held for attacks. The Draw
Phase activations that remain are largely Legacy of Yata-Garasu, Trap Dustshoot and Icarus Attack, where
the score sees no reason to wait (it has no term for "this could be better later").

Not fixed by this: the pilots still model a passive opponent (in forks and in copies), and 58.8% is
still above the real 45.1% - the remaining gap is in range for profile tuning, which was deliberately
not done here. n=500 matches per row; one run each.

## Evaluation upgrade: card advantage, holding value, setup progress (2026-09-29)

Same conditions. `agents/lookahead.py` `score()` gained, with no card names:
- **Card advantage** over hand + field for both sides, plus usable GY resources (a card whose own script
  registers an effect with a GY range - `GraveResources`, read from the script, no list) at half a card.
- **Opponent's board** subtracted at the same rate as ours (1000 ATK = 25), so a 1-for-1 on a strong
  monster gains and on a weak one does not; **lethal threat** (their face-up ATK already reaches our
  LP) -250 and **near-lethal** (-60 per 1000 LP below 2000).
- **Holding value** 40 per unused set card / quick-play / trap in hand (the opponent's set cards
  count the same, as a threat), plus 60 per profile key card in hand.
- **Progress hook** (`Profile.progress`): Lightsworn - distinct Lightsworn monster names in the GY toward
  4, 25 each, +60 with Judgment Dragon live in hand. Blackwing-DAD - DARK monsters in the GY, 25 each up
  to exactly 3, -40 per extra, +60 with Dark Armed Dragon live in hand. Key cards: Judgment Dragon;
  Dark Armed Dragon, Gorz. Weights are first guesses, not tuned.

**Regression vs random, 200 duels:** Lightsworn 99.0% -> **98.0%** [95.0, 99.2]; Blackwing-DAD 99.5% ->
**100.0%** [98.1, 100.0]. 0 rejected answers, 0 failed forks. Within the 3-point limit.

**500 Bo3, same seeds:**

| | Lightsworn match win [95% CI] | Gap to real |
|---|---|---|
| Real (TopDeck.gg) | 45.1% [40.4, 50.0] | - |
| Response search (previous) | 58.8% [54.4, 63.0] | +13.7 |
| **Evaluation upgrade** | **64.0% [59.7, 68.1]** | **+18.9 - flagged** |

Game 1 on the play: Lightsworn 68.4% when Lightsworn goes first, 59.6% when Blackwing-DAD does. Going
first won 56.5% of games (55.0% before). Card advantage at the start of turn 5 (each pilot's own view,
1265 games): **Lightsworn +0.17, Blackwing-DAD -0.17** - close to even, so the result is not decided by
card count by turn 5.

**Blackwing-DAD's traps in the matchup** (previous -> now): activated when offered 13.7% -> 11.5%; per
game 2.25 -> 2.24; answering an attack 43% -> 38% of activations; opponent's Draw Phase 35% -> 20%;
Main Phase 1 15% -> 24% (Torrential 218 -> 264, Solemn 146 -> 177 - more used on summons); Trap Dustshoot
295 -> 119 (a 1-for-0 on sight no longer scores).

The upgrade moved the simulation *away* from the real number: whatever it gave Blackwing-DAD, it gave
Lightsworn more. Both decks run the same evaluation, so this does not say which side's play improved;
an ablation (new Lightsworn vs previous Blackwing-DAD and the reverse) is the way to find out. Not run.

## Speed pass, and attributing the 58.8% -> 64.0% shift (2026-09-29)

**Speed** (no behaviour change). Profile of a 50-match Lightsworn vs Blackwing-DAD run: lookahead copies
58% of game time, response-search forks 39%, the real duel 3%; inside those, ~40% of all time was
re-reading and re-compiling Lua for each short-lived duel. `edison/fastload.py` compiles each script
once per process with the core's own Lua (bytecode via `string.dump`) and caches card rows; copies no
longer go through a temp file and `Puzzle.load`. **19.4 -> 46.8 matches/min** on 8 cores; 200 matches
on the same seeds identical to c62c3c6 in every game, winner, turn count and Blackwing-DAD chain
decision. Remaining time: board-query parsing in `engine/board.py` (~a third; engine code, untouched).
Pass-only prompts were already never searched (0 of 43,304 windows).

**Attribution.** `lightsworn@v1` / `blackwing_dad@v1` in `agents/profiles.py` are the evaluation before
c62c3c6 (the new terms at zero weight, the old progress bonuses). Control: v1 vs v1 on the first 200
seeds reproduces the 58.8% run's first 200 matches *exactly*, so the v1 profiles are the old pilots.
200 Bo3 each, same seeds (match keys 100000-101992), Lightsworn's match win:

| Lightsworn eval \ Blackwing-DAD eval | old (v1) | new |
|---|---|---|
| **old (v1)** | 62.5% [55.6, 68.9] (= the 58.8% run's first 200) | 62.0% [55.1, 68.4] |
| **new** | 65.0% [58.2, 71.3] | 67.0% [60.2, 73.1] (= the 64.0% run's first 200) |

Same seeds, so matches can be paired. Switching one side's evaluation flips 25-30% of matches *in both
directions* - the games are chaotic under any change - and no switch is distinguishable from noise
(exact sign test on flipped matches): new Lightsworn eval 32 flips its way vs 27 against (p=0.60); new
Blackwing-DAD eval 29 vs 28 (p=1.00); both switched, 41 vs 32 (p=0.35). Direction, not proof: the
new evaluation helps Lightsworn by ~+2.5 to +5 points and does nothing measurable for Blackwing-DAD.
The earlier "58.8% -> 64.0%" at n=500 is ~1.7 standard errors and should not be read as the upgrade
making the simulation worse.

**Traps unused at game end** (`end_traps` per game; set = face-down in the S/T zones):

| | games lost | set + in hand, per lost game | lost games ending with >= 1 | per won game |
|---|---|---|---|---|
| Blackwing-DAD v1 (vs Lightsworn v1) | 297 | 0.58 + 0.04 | 46% | 0.97 + 0.01 |
| Blackwing-DAD new (vs Lightsworn v1) | 292 | 0.67 + 0.05 | 47% | 1.05 + 0.01 |
| Blackwing-DAD new (vs Lightsworn new) | 307 | 0.63 + 0.06 | 48% | 0.87 + 0.00 |
| Lightsworn (any), for scale | 201-221 | 0.06-0.19 + 0.01 | 7-19% | 0.19-0.29 |

Nearly half of Blackwing-DAD's lost games end with a trap still set. The holding value added in c62c3c6
makes that slightly more common, not less.

## Holding value scaled by board state (2026-09-29)

`hold_scale()` in `agents/lookahead.py`: our holding value (set cards, traps/quick-plays in hand, key
cards) is full when even or ahead on board, shrinks linearly to 0 at 3000 face-up ATK behind, and is
0 while facing a monster the opponent Summoned this turn with ATK >= 2000 and above our best.

Checked first: in match137 game2 turn 14 the Blackwing-DAD pilot *was* offered Solemn Judgment on
Lightsworn's Synchro Summon of Thought Ruler Archfiend (and on Chaos Sorcerer, Plaguespreader Zombie),
searched, and passed: 87.5 vs 14.5. Rescored at the same position (captured from 244cbee) with the
change: 47.5 vs 14.5 - still a pass; Solemn's half-LP cost outweighs the 2700 ATK removed.

Vs random, 200 duels: Lightsworn 97.5%, Blackwing-DAD 100.0%, 0 rejected. 200 Bo3 on the same seeds as
the 67.0% (new vs new) run: Lightsworn **60.0% [53.1, 66.5]** vs 45.1% real; paired, 28 matches flipped
to Blackwing-DAD and 14 to Lightsworn (sign test p = 0.044). Blackwing-DAD traps: activated in 14.7% of
trap windows (11.6%), Special Summons answered 33% (13%), attacks 42% (35%); Solemn Judgment 108 uses
(79), Trap Dustshoot 82 (55); lost games ending with a trap still set 40% (48%).

## Tuning round 1: hidden-card removal, nonlinear LP, threat-weighted removal (2026-09-30)

Three generic terms in `score()` (no card names); v1 profiles switch all three off.
1. **Hidden cards:** each unknown card in the opponent's hand is worth `hidden_hand` = 40 on top of a
   card, so removing or shuffling one away is not a neutral 1-for-1; +`reveal` = 20 when their hand
   is shown (a `MSG_CONFIRM_CARDS` of their hand during the copy/fork).
2. **LP curve:** our LP is worth 300 * (1 - exp(-t)), t = LP / the opponent's visible face-up ATK
   (at least 1000) - paying 4000 of 8000 against a 1000 board costs ~5, 1500 of 3000 against 2700
   costs ~95. Replaces the linear term and the low-LP penalty.
3. **Threat:** an opposing monster counts ATK + 800 if from the Extra Deck, + 600 if its script has
   an on-field (MZONE) effect, + 400 if a level 7+ Main Deck monster (scored at 1/40 per point).

**Pass check** (match137 game2, turn 14, the same positions captured from 244cbee):

| Window (Solemn Judgment offered) | 1810865: pass vs activate | now: pass vs activate |
|---|---|---|
| Chaos Sorcerer, Special Summon | 232.5 vs 149.5 - pass | 180.2 vs **218.5 - negate** |
| Plaguespreader Zombie, Normal Summon | -2.5 vs -143.0 - pass | -23.6 vs -108.4 - pass |
| Thought Ruler Archfiend, Synchro | 47.5 vs 14.5 - pass | 6.4 vs **123.5 - negate** |

**Regression vs random, 200 duels:** Lightsworn 97.5% (unchanged), Blackwing-DAD 99.5% (100.0%);
0 rejected, 0 failed forks.

**200 Bo3, same seeds as the 60.0% run:** Lightsworn **65.5% [58.7, 71.7]** vs 45.1% real. Paired:
36 matches flipped to Lightsworn, 25 to Blackwing-DAD (sign test p = 0.20) - not distinguishable
from the 60.0% run.

Activations, 60.0% run -> now: Blackwing-DAD's traps in 14.7% -> 25.1% of trap windows (2.40 -> 2.51
per game); Solemn Judgment 108 -> 164, Trap Dustshoot 82 -> 116, Gorz 12 -> 21, Dimensional Prison
255 -> 234, others within noise. Lightsworn: Trap Dustshoot 12 -> **71** - the hidden-card term applies
to both decks, and Lightsworn plays Dustshoot too - traps 0.32 -> 0.42 per game. Blackwing-DAD lost
games ending with a trap still set: 40% -> 35%.

## Known sim biases

Read every simulated matchup number against these. None of them is corrected for.

- **No side decking.** Real Edison matches are Bo3 with a 15-card side deck swapped in for games 2
  and 3; the simulation plays the main deck in all three games. Matchup-specific side cards (and a
  deck's ability to side against its bad matchups) are absent.
- **One decklist per deck.** Each archetype is one list (`edison/decks/`); the TopDeck numbers
  aggregate hundreds of builds (549 Blackwing-DAD, 372 Lightsworn), some tuned against each other.
- **The lookahead assumes a passive opponent.** Copies and forks never let the opponent respond, so
  lines that walk into a set trap or a hand trap are overvalued and cautious lines undervalued -
  equally for both pilots, but not equally for both decks: a deck that wins through the opponent's
  turn (traps) is modelled worse than one that wins on its own turn.
- **Real data includes player-skill selection.** Who picks which deck is not random, and players differ
  in skill; the simulation has two fixed pilots of whatever skill the code has.
- Smaller: the real data includes match draws (time), which the simulation never produces; games 2-3
  here go loser-first by convention; the opponent's face-down Spells/Traps are not scrubbed in forks.

**Generic fixes lift both decks.** Every evaluation change so far is deck-agnostic, so it improves both
pilots, and the Lightsworn vs Blackwing-DAD gap to the real 45.1% has held at **+15 to +20 points**
through all of them (58.8% response search, 64.0% card advantage, 60.0% hold scaling, 65.5% tuning
round 1; paired tests on the same seeds put every step within noise except hold scaling, p = 0.044).
Closing that gap is not a matter of one more generic term; the biases above are the candidates.

## Tuning round 2: Blackwing-DAD profile from an expert guide (2026-09-30)

Guide: `docs/guides/blackwing-dad.md`. All card knowledge is in `agents/profiles.py` (`_blackwing_dad`);
`lookahead.py` gained only generic hooks, each needed by one guide item:
- `Profile.always_consider` (never cut from the Main Phase candidates, not auto-activated in copies) -
  Vayu and Return from the Different Dimension;
- `Profile.hold_factor` (per-card holding value) - Icarus Attack at 0.5 (plain 2-for-2 acceptable);
- progress hooks receive LP (`ctx.my_lp`, `ctx.op_lp`) - the RftDD lethal check;
- target tracking (`MSG_BECOME_TARGET` until `MSG_CHAIN_END`) and a rule for `MSG_SELECT_UNSELECT_CARD`:
  a cost paid with our own monsters while one is targeted by the chain pays with the doomed one.
  **Found on the way:** the pilot had no rule for that prompt, so Icarus Attack's Tribute (it goes
  through `Group.SelectUnselect`) fell through to random-legal, which always answers index 0 - the
  first Winged Beast listed, whichever it was. Outside that one case the answer is unchanged.
- a per-duel log of Main Phase activations (`actions`) and `mine_targeted` in the chain-window log.

Profile: Vayu in GY +20 each (up to 2); a live Vayu Synchro (a non-Tuner Blackwing partner whose Level + 1
is a Blackwing Synchro in the Extra) +60; each dead Blackwing Synchro Vayu can climb from +50 (half a
card back); DARKs toward exactly 3, the excess penalty halved when a Vayu use brings it back to 3; RftDD
available: up to +60 for banished ATK (free zones, blockers take our strongest) against their LP, +150
when that is lethal. The list has no Blizzard, so that part of the guide has nothing to act on.

`tests/test_decisions.py` still passes. Vs random, 200 duels: Lightsworn 97.5% (unchanged),
Blackwing-DAD 98.5% (99.5%); 0 rejected, 0 failed forks.

**200 Bo3, same seeds as the 65.5% run:** Lightsworn **62.0% [55.1, 68.4]** vs 45.1% real. Paired: 25
matches flipped to Blackwing-DAD, 18 to Lightsworn (sign test p = 0.36) - not distinguishable.

Per game (530 games; Blackwing-DAD won 233): **Vayu activations 280 (0.53/game)**; **Icarus Attack in
response to removal 10 (0.02/game)** vs plain trades 198 (0.37/game: 174 in chain windows, 24 from the
Main Phase) - Lightsworn's removal rarely targets (Judgment Dragon and Lyla-style wipes/sends do not);
**RftDD 109 activations (0.21/game), 16 lethal** (the 65.5% run: 102 in chain windows, 1 lethal - its
Main Phase activations were not logged, so the lethal count is not comparable). Lost games ending with a
trap still set: 35% -> 36%.

## Random-fallback audit (2026-09-30)

`python -m edison.fallback_audit` reran the 62.0% matchup and both vs-random checkpoints on their seeds
(600/600 reruns identical to the logs) counting every prompt a pilot's rules passed to random-legal.
Four prompt types, in the real duel, per game:

| Prompt | Blackwing-DAD (matchup / vs random) | Lightsworn (matchup / vs random) | What asked |
|---|---|---|---|
| zone (`SELECT_PLACE`) | 11.4 / 13.2 | 9.8 / 9.8 | every monster and Spell/Trap placement |
| one-at-a-time pick (`SELECT_UNSELECT_CARD`) | 0.88 / 1.52 | 0.91 / 1.46 | Synchro materials (Goyo Guardian, Colossal Fighter, Armor Master), Chaos Sorcerer's banish cost, Icarus Attack's Tribute |
| Tribute Summon (`SELECT_TRIBUTE`) | 0.23 / 0.41 | 0.33 / 0.36 | Sirocco, Gorz; Caius, Celestia |
| number (`ANNOUNCE_NUMBER`) | 0.28 / 0.52 | 0.18 / 0.28 | Card Trooper's mill count |

Inside lookahead copies and forks the same four ran ~80-100 times per game. So every Synchro's
materials were "the first listed", every Tribute Summon's tributes and Card Trooper's count were random.

Now (`lookahead.py`, no card names): in the real duel each of these prompts is searched like a response
- every candidate answer (each zone, each Tribute set of the minimum size, each single pick plus
"finish" when finishing is legal, each number) forked and scored with the same evaluation. Inside
copies and forks, fixed rules: lowest free zone, lowest-ATK tributes, costs paid with our lowest-ATK card
and the opponent's best card chosen, the largest number. **Cancelling a one-at-a-time pick is not a
candidate**: it backs out of the whole action to the menu, the pilot picks the same action again, and
the first version of this looped a duel forever.

Every run report now prints random-fallback answers per game (real duel and inside lookahead).

Checks: `tests/test_decisions.py` passes. Vs random, 200 duels: Lightsworn 97.5% (unchanged),
Blackwing-DAD 98.5% (unchanged); fallback answers 0.00 / 0.00. **200 Bo3 on the same seeds as the 62.0%
run: Lightsworn 63.0% [56.1, 69.4]** vs 45.1% real; paired 28 matches flipped to Lightsworn, 26 to
Blackwing-DAD (p = 0.89); fallback answers 0.00 per game for both pilots, real duel and lookahead.
Cost: zone forks are the bulk of the new searches - 47.9 -> 29.8 matches/min.

## Step 3 closed: second pilot and the first real matchup (2026-09-30)

Pilot #2 is Blackwing-DAD (most recorded matches vs Lightsworn: 411). Both pilots are the generic
lookahead pilot with a profile; both beat random-legal 97-100% with 0 rejected answers and 0 random
fallbacks. Lightsworn vs Blackwing-DAD, Lightsworn's match win (real: **45.1% [40.4, 50.0]**, n=411):

| Step | Change | n (Bo3) | Lightsworn | Paired vs previous |
|---|---|---|---|---|
| v0 | fixed chain rule (traps fired at the first window) | 500 | 81.0% | - |
| response search | opponent-turn / battle prompts searched on forks | 500 | 58.8% | (same seeds; 81.0 reproduced) |
| evaluation upgrade | card advantage, holding value, setup progress | 500 | 64.0% | attribution: no switch distinguishable |
| hold scaling | holding value scales with board / new threats | 200 | 60.0% | p = 0.044 |
| tuning round 1 | hidden cards, LP curve, threat-weighted removal | 200 | 65.5% | p = 0.20 |
| tuning round 2 | Blackwing-DAD profile from an expert guide | 200 | 62.0% | p = 0.36 |
| fallback audit | real rules for every prompt left to random | 200 | **63.0% [56.1, 69.4]** | p = 0.89 |

**Final gap: +17.9 points.** One structural change moved it - response search, which fixed a pilot that
could not play the opponent's turn (81.0 -> 58.8). Since then five changes, two of them Blackwing-DAD-
specific (the guide, and the decision test showing it now negates the right summons) and three generic,
have each changed individual games (25-30% of paired matches flip) without moving the rate beyond noise,
and the gap has held at +15 to +20. The Blackwing-DAD pilot now does what the guide asks - traps held
for threats, Vayu 0.5 times a game, RftDD lethal 16 times in 200 matches, no random choices - and
still loses the matchup by the same margin.

**Conclusion:** the remaining gap is not a pilot-tuning problem that another term will close. It points
at the documented biases (see "Known sim biases"): no side decking in games 2-3, one decklist against
hundreds of builds, a lookahead that assumes the opponent never responds (which costs a trap deck more
than a Lightsworn deck), and player-skill selection in the real data. Step 4 should carry the
+15-20 point matchup gap as a known offset rather than a tuning target.

## Zone choice back to the fixed rule (2026-09-30)

Zones (`MSG_SELECT_PLACE` / `DISFIELD`) are answered by `Rules.place_rule` (lowest free zone) in the
real duel too; one-at-a-time picks, Tributes and numbers stay searched. Vs random, 200 duels: Lightsworn
97.5%, Blackwing-DAD 98.5% (both unchanged), 0 fallbacks, 0 rejected. 200 Bo3 same seeds: Lightsworn
**62.5% [55.6, 68.9]** vs 63.0% with zone search - within noise (paired p above). **29.8 -> 41.9
matches/min.**
