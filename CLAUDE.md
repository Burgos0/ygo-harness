# ygo-harness — working notes for agents

An LLM agent and benchmark for Yu-Gi-Oh, built on `ygopro-core` (the real
rules engine behind EDOPro). Read `docs/PLAN.md` for why the project exists
and where it is going; this file is how to work in it without re-learning
what already cost a debugging session.

## Setup

```bash
brew install cmake lua@5.4 meson ninja pkg-config   # macOS
./scripts/build_core.sh      # builds engine/lib/libocgcore.dylib
./scripts/fetch_data.sh      # card database + Lua card scripts + puzzles
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install pytest openai rich pyyaml
python -m pytest tests/ -q
```

`.env` holds `OPENROUTER_API_KEY`. It is gitignored — **this repo is public,
never commit it.**

Exercising the harness costs nothing: `python scripts/run_puzzles.py` plays
EDOPro's puzzle collection with the random-legal policy, no tokens involved.
Read the **"ran clean"** line, not the solved count — see the conventions.

`python scripts/coverage_report.py` is the authority on what the engine can
tell us versus what we use. Check it before concluding that some piece of
state is unavailable — several times it was available and simply never asked
for. `--missing-only` lists the gaps.

`tests/test_yrp_edopro.py` and one case in `tests/test_message_stream.py`
need an EDOPro install and **skip silently without one** — a green run does
not mean they ran. Install it from
[projectignis.github.io/download.html](https://projectignis.github.io/download.html);
on macOS the `.pkg` installs to `~/Applications/ProjectIgnis` with
`installer -pkg <pkg> -target CurrentUserHomeDirectory`, no root needed.
Point elsewhere with `EDOPRO_DIR` - a system-wide install (`/Applications/ProjectIgnis`, where
the replay folder is on this machine) is **not** found by default, and every EDOPro test skips. **Launch it once before trusting the
tests** — see trap 11.

## Layout

| Path | What |
|---|---|
| `engine/ocgapi.py` | ctypes bindings to the `OCG_*` C API |
| `engine/duel.py` | duel lifecycle + the message/response loop |
| `engine/messages.py` | decoders/encoders per `MSG_*` decision type |
| `engine/board.py` | board state via `OCG_DuelQuery*` |
| `engine/render.py` | compact text rendering, **hidden-info masking** |
| `engine/puzzle.py` | EDOPro puzzle scripts: locating, parsing, loading |
| `engine/declare.py` | the RPN filter `MSG_ANNOUNCE_CARD` ships, ported from the core |
| `llm/events.py` | engine messages -> lines the agent reads |
| `llm/provider.py` | one OpenAI-compatible client (OpenRouter/Ollama/…) |
| `llm/models.yaml` | model roles, with the measurements that chose them |
| `agents/` | policies. Anything goes here |
| `agents/lookahead.py`, `agents/profiles.py` | generic deck pilot (lookahead to end of turn + score); per-deck weights, priorities, hints |
| `edison/pilot_eval.py`, `edison/matchup.py` | profile pilot vs random-legal (the checkpoint); Bo3 pilot vs pilot beside the TopDeck number |
| `bench/` | **sealed** eval protocol. Do not tune against it |
| `viz/replay.py` | `.yrp` export - see the two `REPLAY_NEWREPLAY` traps below |
| `scripts/verify_yrp.py` | replays a `.yrp` through EDOPro's own core/cards/scripts |
| `scripts/run_puzzles.py` | runs the puzzle collection; separates harness faults from losses |
| `scripts/coverage_report.py` | what the core can report vs. what we use |
| `scripts/compare_models.py` | several models over the same puzzles, in parallel |
| `scripts/deliberation_report.py` | planner/executor split, measured on free random duels |
| `scripts/lethal_audit.py` | battle-phase misses, with the seed+turn to go watch |
| `docs/PLAN.md`, `DECISIONS.md` | plan, and the record of decisions/deferrals |
| `docs/STATUS.md` | where the Edison work stands, next step, exit criteria, exact commands |
| `edison/pool.py` | worker pool that never leaves workers behind (Ctrl+C, SIGTERM, errors) |
| `docs/EXPERIMENTS.md` | what has actually been measured, and what failed |
| `docs/RELATED.md` | YGO-Bench and the other harnesses; what we do differently |

## Traps

Every one of these cost real time. They share a shape: **the engine fails
silently rather than loudly**, so a bug looks like bad play rather than an
error.

1. **Global Lua scripts must be loaded before any card is created.** Every
   card script starts `local s,id=GetID()`, and `GetID` is in `utility.lua`.
   The core only ever requests `cXXXXXXX.lua` on demand. Without
   `constant.lua` + `utility.lua` (loaded in `Duel.load_globals`, cascading to
   everything else) *every card has no effects*, duels still run to
   completion, and it looks like a game where nothing has an ability.
   Guarded by `tests/test_card_effects.py`.

2. **The engine does not shuffle.** `Processors::Startup` draws `start_count`
   cards off the *back* of the main deck and nothing more. Shuffling is the
   client's job, so reproducing a duel needs **two** seeds — one for the deal,
   one for the engine's `seed[4]`. Upside: the deal is ours, so an exact
   opening hand can be dealt by ordering the list.

3. **`MSG_RETRY` does not restate the question.** Track the pending decision
   across loop iterations or the policy answers into the void forever.

4. **Query buffers start with a `uint32` total-length prefix.** Skip it or
   the whole TLV parse desyncs — and it renders as "the board is empty",
   not as an error.

5. **Field widths are not uniform within one message.** In
   `MSG_SELECT_IDLECMD` the *repositionable* list writes `sequence` as
   `uint8` while every other list in the same message uses `uint32`.

6. **Response formats differ per message and are not guessable:**
   - `MSG_SELECT_CARD`: `int32 type, uint32 count, indices…` (type 0 = uint32 indices)
   - `MSG_SELECT_UNSELECT_CARD`: **not** the same — `int32 1, int32 index`, one at a time
   - `MSG_SELECT_PLACE`: 3 `int8`s per placement; `flag` marks **unavailable** zones
   - `MSG_SELECT_POSITION`: a single position bit present in the allowed mask; `0` is never valid
   - `MSG_SELECT_CHAIN`: `-1` declines, **but only when `forced` is unset**
   - `MSG_SELECT_IDLECMD`: `(index << 16) | type`

   When in doubt read `vendor/ygopro-core/playerop.cpp` — the validator right
   after each `new_message(...)` is the spec.

7. **Constants are hand-transcribed and drift silently.** `MSG_SORT_CARD` and
   `MSG_SELECT_DISFIELD` were transposed once; a wrong id misroutes a
   decision instead of raising. `tests/test_constants.py` checks every one
   against the header. Note `LINK_MARKER_*` are **octal** in C (`0010` is 8).

8. **Hidden information is masked in `render.py`, once.** The query API
   returns the opponent's hand and set cards without complaint. Leaking them
   would invalidate every result without raising. When testing this,
   remember both players run the same deck — a whole-text substring search
   cannot tell "leaked their Ash Blossom" from "named my own".

9. **ctypes callbacks must be kept alive** for the duel's lifetime, or the
   core calls into freed memory.

10. **`.yrp` fields that exist only under `REPLAY_NEWREPLAY`.** A per-side
    `uint32` player count before the names, and a `uint32` custom-rule-card
    count after the decks. Omit either and EDOPro reads name bytes as a
    player count, or a response byte as a rule count - it does not reject the
    file, it misparses it. A round-trip through our own parser cannot catch
    this, so `tests/test_replay.py` pins byte offsets taken from
    `Replay::ParseNames`/`ParseDecks` instead.

11. **EDOPro's install directory is stale the moment it first runs.** The
    real core, cards and scripts live in
    `repositories/delta-bagooska/{bin,*.delta.cdb,script}`, cloned on first
    launch over the installer's snapshot. Reading the bundled `script/` gave
    a deck with eight cards missing and a replay that desynced at turn 2.

12. **Lua is compiled as C++** (see `scripts/build_core.sh`). Not cosmetic:
    Lua's `longjmp` error handling would skip C++ destructors otherwise. This
    is why upstream `meson.build` cannot be used — it links a C-compiled
    system Lua.

13. **A puzzle is not a deck duel, and the load order is not negotiable.**
    `Debug.ReloadFieldBegin` calls `pduel->clear()` and assigns
    `duel_options` outright, and every puzzle calls
    `Debug.SetPlayerInfo(p, lp, 0, 0)` — start count and draw count zero — so
    the script owns the ruleset, the life points and the opening hand.
    Anything passed to `Duel(...)` about those is inert. Sequence is
    create → `load_globals()` → `OCG_LoadScript(puzzle)` → `OCG_StartDuel`:
    the puzzle's top-level Lua runs *during* `OCG_LoadScript` and creates
    cards immediately, so globals loaded after it hit trap 1 in full. Use
    `Duel.from_puzzle`.

14. **The script vocabulary and the C header are different namespaces.**
    `constant.lua` defines names `ocgapi_constants.h` does not, and puzzle
    sources use them freely: `POS_FACEUP`/`POS_ATTACK`/`POS_DEFENSE` are
    composed positions, `LOCATION_FZONE` (0x100) and `LOCATION_PZONE` (0x200)
    are script-side locations that libdebug folds into `LOCATION_SZONE` when
    placing, and `DUEL_1_FIELD` is constant.lua's name for the header's
    `DUEL_1_FACEUP_FIELD`. A parser missing one of these does not raise — it
    drops the card. That is how six cards vanished from a parsed field while
    the engine placed all six.

15. **`Debug.AddCard` skips silently when the zone is unusable.** It checks
    `is_location_useable` and simply returns, so a puzzle that over-declares a
    location quietly loses the surplus, and cards declared to the main deck
    are re-routed if they are Extra Deck types. Declared-vs-actual is
    therefore *expected* to differ on a handful of puzzles; 231 of 237 match
    exactly and the six that do not are the engine being right.

16. **A blocking message missing from `DECISION_MESSAGES` does not look like
    an unhandled message.** It looks like a *response format bug in a
    different message*. The run loop only updates `pending` when it sees a
    message it recognises, so an unrecognised question leaves the previous
    one pending, the policy answers that, and `MSG_RETRY` comes back without
    restating anything (trap 3). Four were missing this way —
    `MSG_ANNOUNCE_RACE`, `MSG_ANNOUNCE_ATTRIB`, `MSG_ANNOUNCE_CARD`,
    `MSG_SELECT_SUM` — and produced nine failures reported against
    `SELECT_CARD`/`CHAIN`/`PLACE`/`YESNO`. `test_decision_messages_cover_
    everything_playerop_asks` now derives the required set from
    `playerop.cpp`, and `Duel.run` raises when the engine blocks on a batch
    holding no decision it knows.

17. **Two response formats that are not indices.** `MSG_SORT_CARD` wants a
    *permutation*, one `int8` per card, and rejects a repeat — answering `0`
    works only for a single card. `MSG_ANNOUNCE_CARD` wants a *card code*
    satisfying an RPN filter carried in the payload, not a menu choice; the
    filter is evaluated in `engine/declare.py`, a port of `is_declarable`.

18. **`MSG_SELECT_SUM` has two modes and the mode byte reads backwards.** The
    core writes 0 when a maximum was given and 1 when it was not, so 0 means
    the *exact* sum mode. In that mode every chosen card must be consumed —
    it is an exact cover, not a subset sum with slack. The other mode only
    requires reaching the total with no card removable. Each card carries two
    possible parameters packed into one uint32, so both modes need a search.

19. **Seven playable puzzles comment out `aux.BeginPuzzle()`.** Without it
    nothing zeroes the solver's life points at turn end, so they are ordinary
    duels from a fixed field — one puts the opponent on 9,999,999 LP. They run
    fine, but a policy that does not win them exhausts the step cap, which
    reads as a stall rather than a loss. `Puzzle.is_marathon` separates them.

20. **`MSG_SELECT_TRIBUTE` and `MSG_SELECT_CARD` share a header and not an
    entry layout.** Tribute writes `code, controller, location(uint8),
    sequence, release_param` - 11 bytes - where select-card writes a code plus
    a full 10-byte `loc_info`, 14 in all. Parsing tribute at the card stride
    desynchronises after the first entry and yields "codes" made of fragments
    of the previous one, which render as `<655360>`. Two messages that look
    interchangeable are not; check `playerop.cpp` per message.

21. **The harness must never choose a move.** Falling back to option 0 on an
    unusable reply is not a neutral default - in a chain window option 0 is
    *activate*. Measured: one fallback auto-activated Raigeki Break, destroyed
    the agent's own only monster, and made the puzzle unwinnable, after which
    the run reported `unsolved` as though the agent had played it out. A duel
    with no usable answer is reported `invalid`, which is a different fact
    from a loss. Provider errors retry with backoff; an unparseable reply gets
    one terse re-ask; after that the duel is abandoned.

22. **Most "missing" card scripts are vanilla monsters.** A Normal monster
    has no script in CardScripts at all, so the core asks, gets nothing, and
    is correct. Reporting those buries the one case that matters — an effect
    card left with no effects, which is trap 1. `Duel._script_absence_is_notable`
    filters on `TYPE_NORMAL`; the first puzzle run reported Blue-Eyes White
    Dragon and Dark Magician as missing before it did.

23. **An explicit reasoning budget must clear the model's own output cap.**
    The agent passed `reasoning: {max_tokens: 1024}` while the executor capped
    output at 64, and Alibaba rejected it outright — *"max_completion_tokens
    [64] must be greater than thinking_budget [1024]"*. mistral-nemo had
    silently ignored the parameter because it does not think at all, so the
    bug only appeared when both roles moved to a reasoning model. Thinking is
    now left at each model's default; a budget has to be re-checked against
    every model you switch to, and getting it wrong is a hard 400 rather than
    a degradation. `reasoning: {max_tokens: 0}` is also a 400 — use
    `{enabled: false}` if you ever need thinking off.

24. **Caching needs a breakpoint, and the threshold is per-model.** Nothing is
    written to cache unless the request carries `cache_control`
    (`Provider.cache_system` sends it on the system prompt). Even then,
    measured through OpenRouter: qwen caches at every size we use,
    gemini-3.7-flash never cached at any size tested, and haiku-4.5 cached
    nothing below ~5k tokens but did at ~9.9k. A puzzle system prompt is
    1,500–8,400 tokens, so most puzzle runs cache nothing at all on two of the
    three. Read `usage.cached_tokens`; a zero column is the only way to notice.

25. **The Deck is stored in draw order.** Rendering `b.deck` verbatim hands
    the agent its next draw — a hidden-information leak that looks like a
    helpful listing. `render_side` sorts by name and labels it
    `order unknown`. You know your own decklist in this game, so listing the
    contents is correct; listing the *sequence* is not.

26. **A plan is written against whatever the planning prompt contains.** For a
    long time that was the board and the objective, with no action menu — so
    every Seto VS Ishizu plan opened by Normal Summoning Obelisk, a card
    sitting in the Deck, and `summon: Obelisk` was never offered in any of 21
    menus. `plan_prompt` now takes the live menu. When a plan calls for
    something impossible, check what the planner was shown before concluding
    anything about the model.

27. **The turn player's priority erases what a response window is about.**
    At an attack declaration the engine asks the turn player first; answering
    that clears `Duel.since_last_decision`, so by the time the other player's
    `MSG_SELECT_CHAIN` arrives the `MSG_ATTACK` is gone and the window looks
    like a bare phase change. The first trap-timing report put 0 of 78 trap
    activations on attacks for this reason. Track the triggering event in the
    policy's own message hook (`LookaheadPilot.event`), not from that buffer.

28. **A fork of the real duel holds hidden information until it is scrubbed,
    and the scrub card cannot be a Normal monster.** Response-prompt forks
    replay the real duel from its log, so the opponent's hand, Deck and
    face-down monsters and our own Deck order are all real in them.
    `Fork.scrub_lua` rewrites them with `Card.Recreate(..., true)` before any
    candidate is played. `card::replace_effect` returns early when the new
    code is a Normal monster, so a vanilla filler keeps the hidden card's own
    effects (a scrubbed Sangan would still search) - the filler is an inert
    *effect* monster. Removed effects go to the core's deferred
    `reseted_effects`, so pending triggers do not dangle.
    `tests/test_response_search.py` guards both.

29. **A prompt the pilot has no rule for is answered by random-legal, and for
    some prompts that is not random at all.** `RandomLegal` answers
    `MSG_SELECT_UNSELECT_CARD` with index 0, so every cost paid through
    `Group.SelectUnselect` (Icarus Attack's Tribute, many material choices)
    silently took the first card listed. It looked like a strategic choice
    in replays. Before blaming a pilot's judgement for a card choice, check
    which code path answered that prompt.
    `python -m edison.fallback_audit` counts them; every run report prints
    them per game. And never offer "cancel" as a search candidate on such a
    prompt: it backs out to the menu, the same action is chosen again, and
    the duel loops forever.

## Models

See `llm/models.yaml`. Two findings worth not re-deriving:

- On OpenRouter, `reasoning` must go through the SDK's `extra_body`, not as a
  keyword argument.
- **`reasoning: {effort: "low"}` is *slower* than the default** on
  qwen3.7-flash (11.8s vs 7.7s). Use a bounded budget instead:
  `reasoning: {max_tokens: 256}` gives ~3.1s. Latency is roughly linear in
  reasoning tokens — 10ms/token plus 0.8s overhead.

## Conventions

- Prefer the engine's **query API** for state; never rebuild a shadow state
  machine from the message stream.
- Every duel records `(seed, response log)`. Not for rollback — it is what
  makes replay, offline scoring and `.yrp` export possible.
- **Win rate is not a skill signal without controlling turn order.** Always
  split results by going first vs. second. The original evidence — 40/40 duels
  won by player 0 in deck-out races — **no longer reproduces**, because it was
  measured before the Lua globals fix when no card had an effect (trap 1). The
  rule stands on the asymmetry itself, not on the size of that effect. Treat
  any number measured before that fix as void.
- **A test whose input our own code produced cannot fail for the interesting
  reason.** `.yrp` export round-tripped through our own parser for two commits
  while being unopenable, because our reader agreed with our writer about
  omitting two fields. Prefer inputs from outside: the vendored core header,
  a stream EDOPro recorded, EDOPro's own engine. Where that is impossible,
  pin offsets transcribed from the other side rather than asserting that we
  agree with ourselves.
- **Anything that does not depend on what the models answer can be measured
  for free.** When to deliberate is a function of the duel's counters and the
  board, so a random-legal duel exercises it exactly as an LLM duel does —
  which turned the planner/executor split from one hand-measured paid run into
  `scripts/deliberation_report.py`. Check for this before spending tokens on a
  measurement.
- `bench/` is sealed. Tune in `agents/`, never against the eval set.
- **EDOPro puzzles are a debug tool, not the benchmark.** They are a
  single-turn, no-opponent test of combo execution, so they say nothing about
  planning under interruption — the actual thesis. Tuning against them is
  fine and expected. The benchmark remains the sealed Sky Striker splits.
- **Iterate on one puzzle, not the set.** A full Master Rule 5 run is 20
  puzzles, several hundred model calls and roughly half an hour of wall time,
  and it answers a question a single puzzle already answers: did this change
  help. Debug against the simplest puzzle that still fails —
  `--hardest 1` for the other end, or `--filter` by name. **Only run the whole
  set once a change has solved an additional puzzle on the single-puzzle
  test.** The set is for confirming a result, never for finding one.

  The current ladder, easiest first, is
  `[GX_Spirit_Caller]I05_Home_of_the_Fiends` (2/10), `Naim_MathMech` (3/10),
  `Naim_Trickstar_Firewall` (5/10). Solved so far: `Tutorial_Ritual_Basic`.

- **Tutorials are not benchmarks.** Several are ruling demonstrations rather
  than solvable puzzles — `Tutorial_Ruling_Pain_Lanius` exists to show that a
  play is *illegal* — and the collection's own README says tutorials may be
  unsolvable. Exclude them when measuring; `Puzzle.is_tutorial` marks them.

- **Most "the agent reasoned badly" findings are the harness withholding
  state.** This has now happened five times in a row: the phase of the turn,
  the graveyard past six cards, the banished pile, the Extra Deck, and the
  Deck. Each presented as a reasoning failure, each was information the engine
  had and the harness did not pass on. **Before concluding anything about how
  a model thinks, print exactly what it was sent.** The transcript
  (`--transcript`) exists for this.

- **Fan out anything independent.** Puzzle runs, model comparisons and probe
  calls are separate processes against separate providers; nothing shares
  state. Sequential runs cost twenty minutes for what takes five, and the one
  thing that used to force serialisation was a bug - `--transcript` names its
  file after the puzzle, so a fan-out had every model clobbering the same
  path. `scripts/compare_models.py` fans out and gives each model its own
  transcript directory. Ad-hoc probes should be concurrent too: three API
  calls to compare settings is a thread pool, not a for-loop.

- **Model measurements go in `docs/EXPERIMENTS.md`, with their conditions.**
  A solve rate without the model, the puzzle and the sample size is not a
  result — and almost every number in there is n=1, which the file says out
  loud because the tables otherwise read like a ranking.

- **Research findings go back into the docs in the same change that found
  them.** `docs/PLAN.md` for anything that moves a milestone or invalidates
  an estimate, `README.md` for anything that changes what the project claims,
  `CLAUDE.md` for anything that would otherwise cost a second debugging
  session, `DECISIONS.md` for a choice or a deferral. A finding recorded only
  in a chat transcript is a finding that gets rediscovered.
