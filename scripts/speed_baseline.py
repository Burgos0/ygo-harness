"""Engine speed baseline: N random-legal duels, reports duels/sec.

Same setup as tests/test_random_legal.py (Sky Striker mirror, RandomLegal policy), one
distinct seed set per duel. Engine layer only: no LLM, no key.

    python scripts/speed_baseline.py                 # 1,000 duels, one process
    python scripts/speed_baseline.py --workers 4     # same duels split over 4 processes
    python scripts/speed_baseline.py --edison        # Edison mirror (edison/decks/blackwing_dad.ydk),
                                                     # EdisonDuel: 2010 rules preset + Edison scripts
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DECK = ROOT / "data" / "decks" / "sky_striker_pulp6.ydk"

EDISON_DECK = ROOT / "edison" / "decks" / "blackwing_dad.ydk"

_ctx = {}


def _init(edison: bool = False):
    from engine.carddb import CardDB, ScriptProvider
    from engine.deck import Deck
    from engine.ocgapi import load
    if edison:
        from edison.deck import load_ydk
        from edison.duel import EdisonDuel
        from edison.provider import EdisonScriptProvider
        _ctx.update(deck=load_ydk(EDISON_DECK), lib=load(), db=CardDB(), sp=EdisonScriptProvider(), cls=EdisonDuel)
    else:
        from engine.duel import Duel
        _ctx.update(deck=Deck.from_ydk(DECK), lib=load(), db=CardDB(), sp=ScriptProvider(), cls=Duel)


def play(i: int) -> dict:
    from agents.random_legal import RandomLegal
    c = _ctx
    with c["cls"]((i + 1, i + 7, i + 13, i + 29), lib=c["lib"], carddb=c["db"], scripts=c["sp"]) as d:
        d.load_deck(0, c["deck"].main, c["deck"].extra, shuffle_seed=i)
        d.load_deck(1, c["deck"].main, c["deck"].extra, shuffle_seed=i + 500)
        d.start()
        r = d.run(RandomLegal(seed=i), max_steps=300_000, retry_limit=300)
    return {"winner": r["winner"], "steps": r["steps"], "retries": r["retries"],
            "missing": len(r["missing_scripts"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duels", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--edison", action="store_true", help="Edison mirror with the 2010 rules preset")
    args = ap.parse_args()

    if args.workers == 1:
        _init(args.edison)  # setup (card DB, script provider, core) is excluded from the timing
        t = time.perf_counter()
        results = [play(i) for i in range(args.duels)]
        elapsed = time.perf_counter() - t
    else:
        with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.edison,)) as pool:
            list(pool.map(play, range(args.workers)))  # warm every worker before timing
            t = time.perf_counter()
            results = list(pool.map(play, range(args.duels), chunksize=8))
            elapsed = time.perf_counter() - t

    winners = Counter(r["winner"] for r in results)
    steps = sum(r["steps"] for r in results)
    print(f"duels            {len(results)}  (workers {args.workers}, "
          f"{'Edison mirror, 2010 preset' if args.edison else 'Sky Striker mirror, MR5'})")
    print(f"wall time        {elapsed:.2f} s")
    print(f"duels/sec        {len(results) / elapsed:.1f}")
    print(f"steps/sec        {steps / elapsed:,.0f}  (mean {steps / len(results):.0f} steps/duel)")
    print(f"unfinished       {winners.get(None, 0)}")
    print(f"winner p0/p1/draw {winners.get(0, 0)}/{winners.get(1, 0)}/{sum(v for k, v in winners.items() if k not in (0, 1, None))}")
    print(f"retries          {sum(r['retries'] for r in results)}")
    print(f"missing scripts  {sum(r['missing'] for r in results)}")
    return 0 if winners.get(None, 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
