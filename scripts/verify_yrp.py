#!/usr/bin/env python3
"""Check that a .yrp we wrote actually replays in EDOPro's engine.

    python scripts/verify_yrp.py runs/duel-100.yrp

Opening the file in the EDOPro GUI is the end goal, but it is a bad test:
it needs a human at a screen, and a failure shows up as "the duel looks
wrong" with no detail. This does the same thing headlessly and says exactly
where it broke.

It is not a simulation of the client - it is the client's own code path.
EDOPro does not store a picture of the duel; `ReplayMode::StartDuel` in
`gframe/old_replay_mode.cpp` creates a fresh duel from the replay's seed,
deals the recorded decks in file order, and feeds the recorded responses
back into the core one at a time. So this loads EDOPro's *own* libocgcore,
its own cards.cdb and its own Lua scripts, and does exactly that.

That makes it a check on three separate things, which is the point:

  1. our byte layout, since a misread field desyncs everything after it;
  2. our core's behaviour against EDOPro's, which is a different build;
  3. our pinned card scripts against the ones EDOPro ships, which move.

A replay that desyncs shows up as MSG_RETRY - the engine rejecting a
response as illegal for the state it is in - or as responses left over when
the duel ends. Both are reported. A clean run means EDOPro will reach the
same final position we did.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.carddb import CardDB, ScriptProvider
from engine.constants import LOCATION_DECK, LOCATION_EXTRA, MSG_RETRY
from engine.duel import Duel
from engine.ocgapi import load, version
from viz.replay import REPLAY_YRP1, parse_yrp

#: EDOPRO_DIR if set, else the .pkg's per-user install location - the same lookup as
#: engine/puzzle.py, tests/test_yrp_edopro.py and scripts/install_deck.sh.
EDOPRO = Path(os.environ.get("EDOPRO_DIR",
                             Path.home() / "Applications" / "ProjectIgnis")).expanduser()


class Desync(RuntimeError):
    pass


class Chain:
    """Read a script from the first provider that has it.

    EDOPro ships a snapshot under `script/` and then updates on top of it by
    cloning `repositories/delta-bagooska`. Neither directory alone is what the
    client loads, and the difference is not cosmetic: the shipped snapshot was
    missing eight cards of the Sky Striker list outright."""

    def __init__(self, *providers):
        self.providers = providers

    def read(self, name: str):
        for p in self.providers:
            body = p.read(name)
            if body is not None:
                return body
        return None


def edopro_data(edo: Path):
    """Locate what a *running* EDOPro loads, not what its installer laid down.

    Returns (core, card databases, script provider), each preferring the
    updated repository over the bundled snapshot - which is the order EDOPro
    itself resolves them in."""
    delta = edo / "repositories" / "delta-bagooska"
    core = delta / "bin" / "libocgcore.dylib"
    if not core.exists():
        core = edo / "libocgcore.dylib"
    cdbs = [delta / n for n in ("cards.delta.cdb", "cards-unofficial.delta.cdb")]
    cdbs += [edo / "expansions" / n for n in
             ("cards.cdb", "cards-unofficial.cdb", "cards-unofficial-new.cdb")]
    scripts = [delta / "script", edo / "script"]
    return (core,
            [p for p in cdbs if p.exists()],
            Chain(*(ScriptProvider(d) for d in scripts if d.exists())))


class RecordedResponses:
    """Answers every decision from the log, in order - what EDOPro does."""

    def __init__(self, responses: list[bytes]):
        self.responses = responses
        self.i = 0

    def __call__(self, msg, duel) -> bytes:
        if any(m.id == MSG_RETRY for m in duel.last_batch):
            raise Desync(
                f"engine rejected response #{self.i - 1} of "
                f"{len(self.responses)} as illegal, on "
                f"{msg.name if msg else 'an unknown decision'}, at turn "
                f"{duel.turn_count}. The replay diverged here - every later "
                f"response answers a different question than the one it was "
                f"recorded for."
            )
        if self.i >= len(self.responses):
            raise Desync(
                f"ran out of responses at {msg.name if msg else '?'} - the "
                f"duel asked more questions than we recorded, so EDOPro's "
                f"engine took a different path than ours"
            )
        r = self.responses[self.i]
        self.i += 1
        return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("--edopro", default=str(EDOPRO),
                    help="EDOPro install directory (default: $EDOPRO_DIR, "
                         "else ~/Applications/ProjectIgnis)")
    ap.add_argument("--engine", default="edopro", choices=["edopro", "ours"],
                    help="whose core, cards and scripts to replay through. "
                         "'ours' is the control: it must pass, and if it does "
                         "while 'edopro' fails, the file is fine and the two "
                         "data sets have drifted apart")
    args = ap.parse_args()

    edo = Path(args.edopro).expanduser()
    if not (edo / "libocgcore.dylib").exists():
        print(f"no EDOPro install at {edo}", file=sys.stderr)
        return 2

    data = parse_yrp(Path(args.replay).read_bytes())
    if data["id"] != REPLAY_YRP1:
        print("not a yrp1 replay", file=sys.stderr)
        return 2

    if args.engine == "edopro":
        core, cdbs, sp = edopro_data(edo)
        lib = load(core)
        db = CardDB(cdbs)
        where = str(edo)
    else:
        lib, db, sp = load(), CardDB(), ScriptProvider()
        where = "ours"

    print(f"replay     {args.replay}")
    print(f"engine     {where}  core {version(lib)[0]}.{version(lib)[1]}")
    print(f"players    {data['names']}")
    print(f"seed       {data['seed']}")
    print(f"flags      0x{data['duel_flags']:x}   "
          f"lp {data['start_lp']} hand {data['start_hand']} "
          f"draw {data['draw_count']}")
    print(f"decks      " + ", ".join(
        f"{len(m)}+{len(e)}" for m, e in data["decks"]))
    print(f"responses  {len(data['responses'])}")

    policy = RecordedResponses(data["responses"])
    with Duel(tuple(data["seed"]), lib=lib, carddb=db, scripts=sp,
              flags=data["duel_flags"], starting_lp=data["start_lp"],
              starting_draw=data["start_hand"],
              draw_per_turn=data["draw_count"]) as d:
        for code in data["rule_cards"]:
            d.add_card(code, 0, LOCATION_DECK)
        for team, (main, extra) in enumerate(data["decks"]):
            for code in main:
                d.add_card(code, team, LOCATION_DECK)
            for code in extra:
                d.add_card(code, team, LOCATION_EXTRA)
        d.start()
        try:
            r = d.run(policy, max_steps=300_000, retry_limit=1)
        except Desync as e:
            print(f"\nFAIL  {e}")
            return 1

    left = len(data["responses"]) - policy.i
    print(f"\nreplayed   {policy.i} responses, {r['steps']} engine steps")
    print(f"winner     P{r['winner']}")
    if d.missing_scripts:
        print(f"WARNING    no script for: "
              f"{', '.join(sorted(d.missing_scripts))}")
    if left:
        print(f"\nFAIL  {left} responses never consumed - EDOPro's engine "
              f"ended the duel early, so its replay stops short of ours")
        return 1
    print("\nOK    the duel reproduces in EDOPro's engine, byte for byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
