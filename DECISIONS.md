# Decisions and deferrals

Running record of choices that would otherwise be re-litigated, and of work
deliberately put off. Newest first.

---

## The agent never retraces, so plan adherence is the architecture

**Status:** decided. Extends "No rollback at play time" below, and settles a
question that entry left open.

Two architectures were on the table once the agent started failing on
*sequencing* - producing a correct, lethal plan and then executing its steps
out of order until the key action stopped being legal.

- **Search as the executor.** Explore action sequences in the engine, roll
  back, keep one that reaches lethal, play that. Adherence is redundant by
  construction: you cannot deviate from a sequence you found by walking it.
- **Plan adherence.** The agent commits to one action at a time and is held
  against its own plan without ever speculating.

**Chosen: adherence.** Not because search is weaker - it is stronger - but
because retracing is not something a duel permits. Rolling back means undoing
the opponent's negations and chains too, and there is no version of that which
works against a person: you cannot ask an opponent to take back their action.
An agent built on rollback is an agent that only functions in a dummy duel.

The mode the project actually wants forces the same answer. Search-as-agent
needs rollback during play, and rollback does not work over a network - EDOPro
owns the core and nothing on a remote server can be undone. So in the mode
where a human duels the agent, search is unavailable, and an agent that
depends on it does not play at all.

**What this costs, stated plainly.** Without speculative execution a plan
cannot be *verified* as achievable, only observed to have died. There is no
"try it and see" before committing. The compensating mechanism has to be
noticing quickly and re-planning, rather than looking ahead.

**What is unaffected.** Search as *referee* stays: it replays a recorded
(seed, response log) offline, after the duel, so it still scores duels played
over a network and the regret metric survives intact. Rollback offline is
fine; rollback during play is not.

---

## Puzzles are a debug tool; the sealed splits stay the benchmark

**Status:** decided.

EDOPro's puzzle collection gives something this project otherwise has to build
an entire search layer to get: **ground truth the engine computes itself**.
`aux.BeginPuzzle()` registers an `EVENT_TURN_END` effect that zeroes the
solver's life points, so failing to win the turn *is* losing. Binary,
verifiable, free.

It was tempting to promote that to the benchmark. Declined, because a puzzle
has no live opponent — `DUEL_SIMPLE_AI`, and the duel ends before the
opponent's turn ever arrives. Puzzles measure single-turn combo execution;
the thesis is resource management under interruption. Scoring the project on
puzzles would be measuring the thing that was easy to measure.

So: puzzles live alongside `agents/` as a stress test and a development
target, tuning against them is legitimate, and `bench/` stays sealed for the
Sky Striker splits, which are built after the puzzles are solved.

The collection is pinned in `data/DATA_COMMITS` like the card data. Reading
whatever the EDOPro install happens to hold is not reproducible, and the
install updates itself on launch (trap 11).

---

## The agent is a network client, not a host

**Status:** supersedes the transport shape assumed in "Deferred: YGOPro
network transport" below. The deferral itself still stands until the puzzle
work is done.

Measured against the installed client rather than reasoned about:
`config/system.conf` sets `serverport = 7911`, and `WindBot.exe` contains
`CtosMessage`/`StocMessage` classes. **EDOPro hosts the room; WindBot joins it
as a client.** EDOPro's "Add AI player" button launches a WindBot into that
slot. Our agent takes the same slot by connecting to `127.0.0.1:7911` — so we
implement the *client* half, and the user hosts a LAN game normally rather
than clicking "Add AI player".

Two consequences:

- **The core belongs to EDOPro during a networked duel**, so there is no
  `OCG_DuelQuery` for us. This looked like it would force the shadow state
  machine the conventions forbid. It does not: the server pushes query buffers
  as `MSG_UPDATE_DATA` (6) and `MSG_UPDATE_CARD` (7), in the same TLV format
  `engine/board.py` already parses. Reuse that parser.
- **Our `.yrp` export does not apply** to a networked duel — EDOPro writes its
  own replay, which `scripts/verify_yrp.py` can already read. Offline scoring
  of a networked duel goes through EDOPro's replay, not ours.

**WindBot as a baseline is cheaper than assumed, with two real blockers.** The
install ships 43 bots across 50 decks, already built — no C# compilation. But
`WindBot.exe` is a Windows PE32 .NET assembly launched through Mono
(`config/configs.json` puts `/Library/Frameworks/Mono.framework` on the path),
and Mono is not installed here. And because WindBot is a *client*, an
agent-vs-WindBot match with no human in it needs a **server** — a second
protocol implementation. Revisit only after human-vs-agent works.

---

## .yrp export works in EDOPro

**Status:** closed. Two format bugs found and fixed; confirmed in the client.

The previous entry said the bytes round-tripped through our own parser and
that this proved self-consistency, not compatibility. That was right, and the
gap was real: the file **did not open**. Two fields were missing, both of them
required only because we set `REPLAY_NEWREPLAY`, and both silent:

- `Replay::ParseNames` reads a `uint32` player count per side *before* the
  names. Without it the client read the first four bytes of `"Player 1"` as a
  count of seven million players.
- `Replay::ParseDecks` reads a `uint32` custom-rule-card count immediately
  after the decks. Without it the client ate the first response byte as part
  of that count.

Neither could ever fail a round-trip test, because our reader agreed with our
writer about omitting them. The guard that does catch them is
`test_body_layout_matches_client_reading_order`, which pins byte offsets
transcribed from the client rather than from us.

The other suspects listed in the old entry turned out to be fine, and EDOPro's
own `replay/_LastReplay.yrp` settles them: it writes `hash` and `datasize` as
0, so neither is checked; its `version` is `0x000b0029`, which is exactly the
value we now compute (client 41.0, core 11.0); and its flag set is ours plus
`REPLAY_SINGLE_MODE`. `ParseReplayHeader` checks only `header_version <= 1`.

**How it is verified now.** `scripts/verify_yrp.py` replays a `.yrp` through
the EDOPro install's *own* core, card databases and Lua scripts, following
`ReplayMode::StartDuel`. This is not a stand-in for the client - it is the
client's code path, minus rendering. A duel of 917 responses reproduces in
2212 engine steps with the same winner, identical to our own engine.
`tests/test_yrp_edopro.py` keeps it, skipping when EDOPro is not installed.

Confirmed in the GUI on 2026-08-24: an exported duel opens from EDOPro's
replay menu and plays back with card art and animation. Reviewing a duel the
agent played is now a thing that happens by watching it, which was the whole
argument for doing M1.5 before anything prettier.

---

## A replay is only as portable as the card scripts it was played with

**Status:** empirical, found while verifying the export.

EDOPro does not store a picture of a duel. It re-creates one from the seed and
feeds the responses back into its own core, so a response is only legal if the
client's engine offers the same menu ours did. Card scripts move, and when they
move the menu changes.

Measured, not theorised: against EDOPro 41.0.2 as shipped, our replay desynced
at response 18 of 917 - `MSG_SELECT_IDLECMD`, turn 2. The installer's April
2025 script snapshot was **missing eight of the deck's cards outright** and
differed on six more. EDOPro clones `ProjectIgnis/DeltaBagooska` over that
snapshot on first launch; against the updated scripts the same file replays
clean. So the failure was never in the file.

**Consequences:**

- A `.yrp` we publish is only replayable by a client whose scripts cover the
  cards played. "It desynced" is not evidence the export is broken - check the
  data versions first, which is what `--engine ours` exists for.
- Read EDOPro's data the way EDOPro does: prefer
  `repositories/delta-bagooska/{script,bin,*.delta.cdb}` over the bundled
  `script/`, `libocgcore.dylib` and `expansions/`. The bundled copies are the
  installer's snapshot and are stale the moment the client first runs.
- `data/DATA_COMMITS` pins babelcdb at `d1cf9e0a`, which is what
  `repositories/delta-bagooska/VERSION` reports today. That agreement is
  luck, not machinery. Nothing enforces it.

---

## The planner fires on chain resolutions it has no reason to

**Status:** fixed, measured.

`chain resolved` was an unconditional planning edge, and it dominated the
split. Measured over 20 random-legal duels - free, because when to deliberate
depends on the duel's counters and the board rather than on what the models
answer (`scripts/deliberation_report.py`), planner calls per duel:

| rule | planner/duel | |
|---|---|---|
| any chain resolves | 82.1 | |
| ...and the board changed | 78.6 | −4% |
| ...and the opponent was in the chain | 60.5 | −26% |
| ...both | **57.2** | **−30%** |
| ...never | 40.6 | −51% |

The dominant term is **our own uncontested chains: 431 of 830 resolutions.**
Nobody interfered, so the resolution is the plan working as planned, and
paying the expensive model to look again is the single largest waste in the
split. The board-change gate alone is nearly worthless (−4%) because a chain
that resolves almost always changes something.

`never` scores best and is still wrong: `opponent chained` fires when they
*activate*, so a rule with no chain-resolution edge does its only thinking on
a board mid-chain, before the interruption has resolved.

Shipping `both`. `tests/test_deliberation.py` asserts the shipped rule and the
table's winner stay the same thing, so the justification cannot drift away
from what runs.

**Note on reading that table:** random play makes worse choices, so its duels
run longer and pile up more near-forced executor decisions than an agent's do.
Planner calls *per duel* transfer; the percentage does not.

---

## "The agent wins by deck-out" was the wrong diagnosis

**Status:** corrected by measurement. Small sample.

The recorded symptom was that the agent plays real lines but closes games by
deck-out rather than damage, with the implication that it was declining
attacks. `scripts/lethal_audit.py` scores every battle-phase decision against
the board the engine reports. Over 5 LLM duels and 31 battle decisions with an
attack available:

- it declined **0** of them;
- a lethal board - opponent with an empty field, our ATK at or above their
  life points - appeared **once**, and it attacked;
- 3 of 5 duels ended on life points, not deck-out.

So attack selection is not the problem, and the deck-out characterisation is
itself partly stale - it likely predates the Lua globals fix, which
invalidated everything measured before it. What is true is that the agent gets
only ~6 battle decisions a duel: it rarely develops a board that can kill.
**The work is in board development, not the battle phase.**

Five duels is not many. Re-run at n=20 before building on it.

The audit reports the seed and turn of every miss on purpose. Duels export to
`.yrp`, so a miss is something to go and watch rather than infer.

---

## Deferred: WindBot as an opponent

**Status:** not in v1. Revisit after M2.

[WindBot](https://github.com/IceYGO/windbot) is the community's rule-based bot:
C#, per-deck `Executor` classes, speaks the YGOPro network protocol over TCP.
It never links the core.

Worth knowing when this comes back: installing EDOPro drops a WindBot build at
`~/Applications/ProjectIgnis/WindBot`, so the "real WindBot over a local
server" option no longer starts with a C# build.

It was going to be the fixed-skill baseline. Dropped for now because a baseline
is only useful once there is an agent worth measuring, and the human-vs-agent
test covers the same ground earlier and more cheaply.

When it comes back, there are two options and they are not equivalent:

- **Real WindBot over a local server.** True external baseline, no
  reimplementation risk. Costs a network transport (see below).
- **A Python rule-based opponent in-process**, informed by WindBot's Sky
  Striker executor. Cheaper, works with everything, but it is our
  interpretation of the baseline rather than the baseline.

---

## No rollback at play time

**Status:** decided.

The agent commits to its actions. It does not explore and undo during a duel.

This was previously muddled with search, so, precisely:

| | Runs | Needs rollback | Works over a network |
|---|---|---|---|
| Search as **referee** (computes `V*` for the regret metric) | Offline, after the duel | Yes, offline | **Yes** |
| Search as **agent** (plays stronger by exploring branches) | Online, mid-duel | Yes, during play | No |

Only search-as-agent needs rollback while playing, and that is M3+. The referee
replays a recorded `(seed, response log)` in a fresh in-process duel after the
fact, so duels played over a network - against WindBot, or against a human in
EDOPro - can still be scored by search afterwards.

**Consequence:** keep recording `(seed, response log)` for every duel
regardless. Not for rollback - it is what makes replay, offline scoring, and
`.yrp` export possible, and it is nearly free.

---

## Deferred: YGOPro network transport

**Status:** not in v1. Required by both WindBot-as-opponent and
human-vs-agent-in-EDOPro.

Everything in this ecosystem is a network client - EDOPro, WindBot, Neos. To
play against any of them live, the agent has to speak the YGOPro protocol
rather than drive the core in-process.

Cost is real but bounded: the *duel* half of that protocol is the `MSG_*`
stream we already decode. What is missing is the lobby half - handshake, deck
exchange, player slots, rematch. Estimate one to two days, not an afternoon.

Do not start this before there is an agent worth playing against.

---

## Win rate is not a skill signal without turn-order control

**Status:** empirical, measured at M0.

40/40 random-vs-random duels were won by player 0. Not a bug: random play
almost never deals lethal, so games become deck-out races, and the player going
second draws one extra card over the game and decks out first. The result is
deterministic and has nothing to do with play quality.

**Consequence:** every win-rate number this project reports must be split by
going first vs. going second. It is also direct evidence for the plan's
argument that regret-against-achievable-value is the better primary metric -
"did you win" is a weak signal in this game.

**The evidence above is stale; the conclusion is not.** That 40/40 was measured
before the Lua globals fix, when no card had an effect and every duel was
necessarily a deck-out race. Re-measured afterwards (`scripts/lethal_audit.py
--agent random -n 10`): player 0 won 4 of 10, and 7 of 10 ended on life points
rather than deck-out. Only ten duels, so treat it as "the old number no longer
reproduces" rather than as a new number. Split by turn order regardless - the
reason to was never the size of the effect.

## Response prompts are searched on forks of the real duel, not puzzle copies

**Status:** decided 2026-09-29 (Edison pilots, `agents/lookahead.py`).

The lookahead pilot's copies are puzzles rebuilt from what the pilot may know, and they start at a
fresh Main Phase. A response prompt - an attack just declared, a chain link just made, a monster just
summoned - cannot be expressed that way: the pending event is the whole point of the prompt. So a
response prompt is searched on a *fork*: the real duel replayed from its seeds, dealt decks and
response log (what a `.yrp` holds) up to the prompt. That rebuild contains hidden information, so it
is scrubbed with `Card.Recreate` before any candidate is played (our Deck order permuted with the
pilot's RNG; the opponent's hand, Deck and face-down monsters made an inert effect monster; the RNG
advanced a pilot-chosen amount). Cost: about 100 ms per fork, almost all of it script loading - the
same as a puzzle copy - and 0 of ~14,000 forks in the first runs failed to reach their prompt.

Rejected: rebuilding the event inside a puzzle (replaying the opponent's visible actions into a copy
with the seats swapped). It works for attacks but not for chains or Special Summons from effects, and
it would need a shadow model of the turn built from the message stream, which the conventions forbid.
Left unscrubbed, and documented in `Fork`: the opponent's face-down Spells/Traps (a passive opponent
never activates them).
