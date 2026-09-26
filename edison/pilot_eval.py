"""Lightsworn pilot v0 vs random-legal, Edison rules (EdisonDuel), Lightsworn mirror.

    python -m edison.pilot_eval [--duels 500] [--workers 4]

The pilot sits in seat 0 (goes first) in even duels and seat 1 in odd duels, so it goes first in exactly
half. Both sides play edison/decks/lightsworn.ydk. Duel i uses seeds (i+1, i+7, i+13, i+29) and deck
shuffles i / i+500, so any duel can be replayed. Reports progress with an ETA, classifies every loss by
the engine's win reason (LP to 0 / deck-out / other), traces every rejected answer (MSG_RETRY) to the
side and decision type that gave it, and exports every loss as a replay (runs/lightsworn-<tag>-losses/,
and EDOPro's replay folder), each verified against EDOPro's own engine.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DECK = ROOT / "edison" / "decks" / "lightsworn.ydk"
_ctx: dict = {}


def _init():
    from edison.deck import load_ydk
    from engine.carddb import CardDB
    from engine.ocgapi import load
    _ctx.update(lib=load(), db=CardDB(), deck=load_ydk(DECK))


class _Traced:
    """Wraps a policy: a decision handed back unchanged means the previous answer to it was rejected."""

    def __init__(self, inner, side, log):
        self.inner, self.side, self.log, self.last = inner, side, log, None

    def attach(self, duel):
        self.inner.attach(duel)

    def __call__(self, msg, duel):
        if msg is not None and self.last is not None and msg is self.last:
            self.log.append((self.side, msg.id))
        r = self.inner(msg, duel)
        self.last = msg
        return r


def _win_reason(messages) -> int:
    from engine.constants import MSG_WIN
    wins = [m for m in messages if m.id == MSG_WIN]
    return wins[-1].payload[1] if wins else -1


def play(i: int, export: bool = False) -> dict:
    from agents.lightsworn import LightswornPilot
    from agents.random_legal import RandomLegal
    from edison.duel import EdisonDuel
    c = _ctx
    seat = i % 2
    rejected: list = []
    pilot = _Traced(LightswornPilot(seat=seat, seed=i, lib=c["lib"], carddb=c["db"]), "pilot", rejected)
    rnd = _Traced(RandomLegal(seed=i), "random", rejected)
    t = time.perf_counter()
    with EdisonDuel((i + 1, i + 7, i + 13, i + 29), lib=c["lib"], carddb=c["db"]) as d:
        d.load_deck(0, c["deck"].main, c["deck"].extra, shuffle_seed=i)
        d.load_deck(1, c["deck"].main, c["deck"].extra, shuffle_seed=i + 500)
        pilot.attach(d)
        d.start()
        r = d.run(pilot if seat == 0 else rnd, max_steps=300_000, retry_limit=300,
                  policy1=rnd if seat == 0 else pilot)
        out = {"i": i, "seat": seat, "winner": r["winner"], "reason": _win_reason(r["messages"]),
               "turns": pilot.inner.turn.number, "steps": r["steps"], "retries": r["retries"],
               "rejected": rejected, "searches": pilot.inner.searches, "copies": pilot.inner.copies,
               "seconds": time.perf_counter() - t}
        if export:
            from viz.replay import build_yrp
            names = ("Lightsworn pilot v0", "random-legal") if seat == 0 else ("random-legal", "Lightsworn pilot v0")
            out["yrp"] = build_yrp(seed=(i + 1, i + 7, i + 13, i + 29), decks=d.dealt, responses=d.responses,
                                   duel_flags=d.flags, names=names, start_lp=d.starting_lp,
                                   start_hand=d.starting_draw, draw_count=d.draw_per_turn)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duels", type=int, default=500)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="v1")
    args = ap.parse_args()

    t = time.perf_counter()
    results = []
    with ProcessPoolExecutor(args.workers, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        futures = [pool.submit(play, i) for i in range(args.duels)]
        for f in as_completed(futures):
            results.append(f.result())
            n = len(results)
            if n % 25 == 0 or n == args.duels:
                el = time.perf_counter() - t
                wins = sum(1 for r in results if r["winner"] == r["seat"])
                print(f"  {n}/{args.duels} duels, {el:.0f}s elapsed, ETA {el / n * (args.duels - n):.0f}s, "
                      f"pilot {wins}/{n} won so far", flush=True)
    results.sort(key=lambda r: r["i"])
    wall = time.perf_counter() - t

    won = lambda r: r["winner"] == r["seat"]
    first = [r for r in results if r["seat"] == 0]
    second = [r for r in results if r["seat"] == 1]
    draws = sum(1 for r in results if r["winner"] not in (0, 1))
    print(f"duels {len(results)} in {wall:.0f}s with {args.workers} workers = {len(results) / wall:.2f} duels/s "
          f"(one process: {sum(r['seconds'] for r in results) / len(results):.2f} s/duel)")
    print(f"pilot win rate {sum(map(won, results)) / len(results):.1%} "
          f"(going first {sum(map(won, first))}/{len(first)}, going second {sum(map(won, second))}/{len(second)}, "
          f"draws/unfinished {draws})")
    print(f"mean turns {sum(r['turns'] for r in results) / len(results):.1f}, retries {sum(r['retries'] for r in results)}, "
          f"searches/duel {sum(r['searches'] for r in results) / len(results):.1f}, "
          f"copies/duel {sum(r['copies'] for r in results) / len(results):.0f}")

    from engine.constants import WIN_REASON_DECKOUT, WIN_REASON_LP
    losses = [r for r in results if r["winner"] in (0, 1) and not won(r)]
    kind = lambda r: {WIN_REASON_LP: "LP to 0", WIN_REASON_DECKOUT: "deck-out"}.get(r["reason"], f"other ({r['reason']})")
    by = Counter(kind(r) for r in losses)
    print(f"losses {len(losses)}: " + ", ".join(f"{k} {v}" for k, v in by.most_common())
          + f" | going first {sum(1 for r in losses if r['seat'] == 0)}, second {sum(1 for r in losses if r['seat'] == 1)}")
    rej = Counter((side, mid) for r in results for side, mid in r["rejected"])
    print(f"rejected answers (engine retries) {sum(r['retries'] for r in results)}; traced by side/decision: "
          f"{dict(rej) or 'none'}")

    _init()
    out_dir = ROOT / "runs" / f"lightsworn-{args.tag}-losses"
    out_dir.mkdir(parents=True, exist_ok=True)
    edopro = Path("/Applications/ProjectIgnis/replay")
    edopro_dir = edopro / f"Lightsworn {args.tag} losses" if edopro.is_dir() else None
    if edopro_dir:
        edopro_dir.mkdir(exist_ok=True)
    ok = 0
    for r in losses:
        x = play(r["i"], export=True)
        path = out_dir / f"duel{r['i']:03d}-{'first' if r['seat'] == 0 else 'second'}-{kind(r).split()[0]}.yrp"
        path.write_bytes(x["yrp"])
        v = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_yrp.py"), str(path)],
                           capture_output=True, text=True)
        if "reproduces in EDOPro" in v.stdout:
            ok += 1
        else:
            print(f"  {path.name}: NOT verified - {(v.stdout.strip() or v.stderr.strip()).splitlines()[-1:]}")
        if edopro_dir:
            shutil.copy(path, edopro_dir / path.name)
    print(f"loss replays: {len(losses)} in {out_dir.relative_to(ROOT)}"
          + (f" and EDOPro replay/{edopro_dir.name}/" if edopro_dir else "")
          + f"; verified in EDOPro's engine: {ok}/{len(losses)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
