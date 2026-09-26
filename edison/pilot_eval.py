"""Lightsworn pilot v0 vs random-legal, Edison rules (EdisonDuel), Lightsworn mirror.

    python -m edison.pilot_eval [--duels 500] [--workers 4]

The pilot sits in seat 0 (goes first) in even duels and seat 1 in odd duels, so it goes first in exactly
half. Both sides play edison/decks/lightsworn.ydk. Duel i uses seeds (i+1, i+7, i+13, i+29) and deck
shuffles i / i+500, so any duel can be replayed. Exports three replays to runs/ (a win going first, a
win going second, and a loss if there is one) and verifies each against EDOPro's own engine.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
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


def play(i: int, export: bool = False) -> dict:
    from agents.lightsworn import LightswornPilot
    from agents.random_legal import RandomLegal
    from edison.duel import EdisonDuel
    c = _ctx
    seat = i % 2
    pilot = LightswornPilot(seat=seat, seed=i, lib=c["lib"], carddb=c["db"])
    rnd = RandomLegal(seed=i)
    t = time.perf_counter()
    with EdisonDuel((i + 1, i + 7, i + 13, i + 29), lib=c["lib"], carddb=c["db"]) as d:
        d.load_deck(0, c["deck"].main, c["deck"].extra, shuffle_seed=i)
        d.load_deck(1, c["deck"].main, c["deck"].extra, shuffle_seed=i + 500)
        pilot.attach(d)
        d.start()
        r = d.run(pilot if seat == 0 else rnd, max_steps=300_000, retry_limit=300,
                  policy1=rnd if seat == 0 else pilot)
        out = {"i": i, "seat": seat, "winner": r["winner"], "turns": pilot.turn.number, "steps": r["steps"],
               "retries": r["retries"], "searches": pilot.searches, "copies": pilot.copies,
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
    args = ap.parse_args()

    t = time.perf_counter()
    with ProcessPoolExecutor(args.workers, mp_context=mp.get_context("spawn"), initializer=_init) as pool:
        results = list(pool.map(play, range(args.duels), chunksize=4))
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

    picks = [next((r for r in first if won(r)), None), next((r for r in second if won(r)), None),
             next((r for r in results if r["winner"] in (0, 1) and not won(r)), None)]
    _init()
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    edopro_replays = Path("/Applications/ProjectIgnis/replay")
    for label, r in zip(("win-going-first", "win-going-second", "loss"), picks):
        if r is None:
            print(f"replay {label}: none in this run")
            continue
        x = play(r["i"], export=True)
        path = runs / f"lightsworn-v0-{label}-duel{r['i']}.yrp"
        path.write_bytes(x["yrp"])
        v = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_yrp.py"), str(path)],
                           capture_output=True, text=True)
        verdict = (v.stdout.strip().splitlines() or ["?"])[-1]
        dest = ""
        if edopro_replays.is_dir():
            shutil.copy(path, edopro_replays / f"Lightsworn v0 - {label} - duel {r['i']}.yrp")
            dest = f" -> EDOPro replay/Lightsworn v0 - {label} - duel {r['i']}.yrp"
        print(f"replay {label}: duel {r['i']} ({x['turns']} turns) {path.relative_to(ROOT)}{dest}\n    {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
