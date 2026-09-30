"""Bo3 matches between two profile pilots under Edison rules, compared with the TopDeck.gg number.

    python -m edison.matchup --a lightsworn --b blackwing_dad [--matches 500] [--workers 8]

Who goes first: game 1 alternates by match (A in even matches, B in odd); in games 2-3 the loser of the
previous game goes first (the usual Bo3 choice; after a drawn game the side that went second goes first).
A drawn game counts as a game played; a match that ends 1-1 or 0-0 after three games is a drawn match.
Game g of match m has key 100000 + 10*m + g (seeds in edison/pilots.py). Every game - its key, seeds,
shuffles, who went first, winner, win reason, rejected answers - is logged to
runs/matchup-<a>-vs-<b>-<tag>/matches.jsonl. Match win rate = W/(W+L), Wilson 95%, the same statistic as
edison/topdeck/matchups.csv, and the report sits it beside the real-data cell for this pairing.
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from edison import pilots  # noqa: E402
from edison.topdeck.matchups import wilson  # noqa: E402

FLAG_POINTS = 15.0


def play_match(m: int, a: str, b: str, respond: bool = True) -> dict:
    first = a if m % 2 == 0 else b
    wins, games = Counter(), []
    for g in range(3):
        second = b if first == a else a
        r = pilots.play(100_000 + 10 * m + g, (first, second), (first, second), respond=respond)
        winner = {0: first, 1: second}.get(r["winner"])
        wins[winner] += winner is not None
        games.append({"game": g + 1, "key": r["key"], "seeds": r["seeds"], "shuffles": r["shuffles"],
                      "first": first, "winner": winner, "reason": r["reason"], "turns": r["turns"],
                      "retries": r["retries"], "rejected": r["rejected"], "seconds": round(r["seconds"], 2),
                      "windows": {({0: first, 1: second}[int(s)]): w for s, w in r["windows"].items()},
                      "forks": r["forks"], "t_copies": round(r["t_copies"], 3), "t_forks": round(r["t_forks"], 3),
                      "ca": {({0: first, 1: second}[int(s)]): c for s, c in r["ca"].items()},
                      "end_traps": {({0: first, 1: second}[s]): t for s, t in r["end_traps"].items()}})
        if max(wins[a], wins[b]) == 2:
            break
        first = second if winner == first else (first if winner == second else second)
    winner = a if wins[a] == 2 else b if wins[b] == 2 else None
    return {"match": m, "a": a, "b": b, "game1_first": games[0]["first"], "winner": winner,
            "score": [wins[a], wins[b]], "games": games}


def real_cell(a: str, b: str):
    from agents.profiles import PROFILES
    na, nb = PROFILES[a].name, PROFILES[b].name
    for r in csv.DictReader(open(ROOT / "edison" / "topdeck" / "matchups.csv")):
        if r["archetype"] == na and r["opponent"] == nb:
            return r
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="lightsworn")
    ap.add_argument("--b", default="blackwing_dad")
    ap.add_argument("--matches", type=int, default=500)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--tag", default="run")
    ap.add_argument("--no-respond", action="store_true", help="pilots without response search (the old fixed rule)")
    args = ap.parse_args()
    a, b = args.a, args.b
    out_dir = ROOT / "runs" / f"matchup-{a}-vs-{b}-{args.tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{a} vs {b}: {args.matches} Bo3 matches, {args.workers} workers -> {out_dir.relative_to(ROOT)}")

    results, duels = [], 0
    progress = pilots.Progress(args.matches, every=20, unit="matches")
    with ProcessPoolExecutor(args.workers, mp_context=mp.get_context("spawn"), initializer=pilots.init) as pool, \
            open(out_dir / "matches.jsonl", "w") as log:
        futures = [pool.submit(play_match, m, a, b, not args.no_respond) for m in range(args.matches)]
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
            duels += len(r["games"])
            log.write(json.dumps(r) + "\n")
            log.flush()
            aw = sum(1 for x in results if x["winner"] == a)
            el = max(1e-9, __import__("time").perf_counter() - progress.t)
            progress(len(results), f"{duels} duels ({duels / el:.2f} duels/s), {a} {aw}/{len(results)} matches")
    results.sort(key=lambda r: r["match"])

    def rate(rs):
        w = sum(1 for r in rs if r["winner"] == a)
        l = sum(1 for r in rs if r["winner"] == b)
        lo, hi = wilson(w, w + l)
        return w, l, len(rs) - w - l, (w / (w + l) if w + l else float("nan")), lo, hi

    games = [g for r in results for g in r["games"]]
    gw = sum(1 for g in games if g["winner"] == a)
    gl = sum(1 for g in games if g["winner"] == b)
    first_wins = sum(1 for g in games if g["winner"] == g["first"])
    decided = sum(1 for g in games if g["winner"])
    w, l, d, wr, lo, hi = rate(results)
    lines = [f"{a} vs {b}: {len(results)} Bo3 matches, {len(games)} games, "
             f"{progress.total and len(games) / (__import__('time').perf_counter() - progress.t):.2f} duels/s",
             f"simulated {a} match win {wr:.1%} [95% CI {lo:.1%}, {hi:.1%}]  ({w}-{l}-{d} W-L-D)"]
    cell = real_cell(a, b)
    if cell:
        real = float(cell["match_wr"])
        lines.append(f"real (TopDeck.gg) {a} match win {real:.1%} [95% CI {float(cell['match_lo']):.1%}, "
                     f"{float(cell['match_hi']):.1%}]  ({cell['wins']}-{cell['losses']}-{cell['draws']}, "
                     f"{cell['matches']} matches)")
        gap = 100 * (wr - real)
        lines.append(f"difference {gap:+.1f} points" + (f"  ** FLAG: more than {FLAG_POINTS:.0f} points **"
                                                         if abs(gap) > FLAG_POINTS else f" (within {FLAG_POINTS:.0f})"))
    for who in (a, b):
        w_, l_, d_, wr_, lo_, hi_ = rate([r for r in results if r["game1_first"] == who])
        lines.append(f"  {who} on the play in game 1: {a} {wr_:.1%} [{lo_:.1%}, {hi_:.1%}] ({w_}-{l_}-{d_})")
    lines.append(f"games: {a} {gw}-{gl} ({gw / max(1, gw + gl):.1%}), draws {len(games) - gw - gl}; "
                 f"player going first won {first_wins}/{decided} decided games ({first_wins / max(1, decided):.1%})")
    rej = Counter((side, mid) for g in games for side, mid in g["rejected"])
    lines.append(f"rejected answers (engine retries) {sum(g['retries'] for g in games)}; traced (seat, msg): "
                 f"{dict(rej) or 'none'}")
    lines.append(f"response search: forks/game {sum(g.get('forks', 0) for g in games) / len(games):.0f}")
    tg = sum(g["seconds"] for g in games)
    tc, tf = sum(g.get("t_copies", 0) for g in games), sum(g.get("t_forks", 0) for g in games)
    lines.append(f"time in games {tg:.0f}s (sum over workers): lookahead copies {tc / tg:.0%}, response forks "
                 f"{tf / tg:.0%}, real duel engine + policy {(tg - tc - tf) / tg:.0%}; "
                 f"{len(results) / (time.perf_counter() - progress.t) * 60:.1f} matches/min")
    for who in (a, b):   # card advantage at the start of turn 5, from each pilot's own view
        v = [g["ca"][who][5] for g in games if 5 in g.get("ca", {}).get(who, {})]
        if v:
            lines.append(f"card advantage at turn 5, {who}: {sum(v) / len(v):+.2f} cards (mean of {len(v)} games)")
    for who in (a, b):   # traps still set / in hand when the game ended
        for res, pick in (("lost", lambda g: g["winner"] not in (who, None)), ("won", lambda g: g["winner"] == who)):
            gs = [g for g in games if pick(g) and "end_traps" in g]
            if gs:
                st = sum(g["end_traps"][who]["set"] for g in gs) / len(gs)
                hd = sum(g["end_traps"][who]["hand"] for g in gs) / len(gs)
                unused = sum(1 for g in gs if g["end_traps"][who]["set"] + g["end_traps"][who]["hand"])
                lines.append(f"unused traps at game end, {who} {res} ({len(gs)} games): {st:.2f} set + {hd:.2f} in hand"
                             f" per game; {unused / len(gs):.0%} of these games ended with at least one")
    from engine.constants import WIN_REASON_DECKOUT, WIN_REASON_LP
    reasons = Counter({WIN_REASON_LP: "LP to 0", WIN_REASON_DECKOUT: "deck-out"}.get(g["reason"], f"other ({g['reason']})")
                      for g in games)
    lines.append("game endings: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()))
    print("\n".join(lines))
    (out_dir / "summary.txt").write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
