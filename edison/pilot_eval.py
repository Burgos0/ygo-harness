"""A profile pilot vs random-legal under Edison rules - the checkpoint every new pilot must pass.

    python -m edison.pilot_eval --profile lightsworn [--duels 200] [--workers 4] [--export 3]

Both sides play the profile's deck. The pilot sits in seat 0 (goes first) in even duels and seat 1 in odd
duels, so it goes first in exactly half. Duel i has key i (seeds in edison/pilots.py), so any duel can be
replayed. Prints progress every 50 duels, classifies every loss by the engine's win reason, traces every
rejected answer (MSG_RETRY) to its side, writes one JSON line per duel to runs/<profile>-<tag>/duels.jsonl,
and exports every loss (plus --export sample duels) as a replay verified against EDOPro's own engine and
copied to EDOPro's replay folder.
"""
from __future__ import annotations

import argparse
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


def _play(i: int, profile: str, export: bool = False, respond: bool = True) -> dict:
    specs = (profile, "random") if i % 2 == 0 else ("random", profile)
    r = pilots.play(i, specs, (profile, profile), export=export, respond=respond)
    r["i"], r["seat"] = i, i % 2
    r["rejected_by_pilot"] = sum(1 for side, _ in r["rejected"] if side == r["seat"])
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="lightsworn")
    ap.add_argument("--duels", type=int, default=200)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--tag", default="eval")
    ap.add_argument("--export", type=int, default=0, help="also export this many sample duels (wins or losses)")
    ap.add_argument("--no-respond", action="store_true", help="pilot without response search (the old fixed rule)")
    args = ap.parse_args()
    out_dir = ROOT / "runs" / f"{args.profile}-{args.tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{args.profile} pilot vs random-legal, {args.duels} duels, {args.workers} workers -> {out_dir.relative_to(ROOT)}")

    results = []
    progress = pilots.Progress(args.duels)
    with ProcessPoolExecutor(args.workers, mp_context=mp.get_context("spawn"), initializer=pilots.init) as pool, \
            open(out_dir / "duels.jsonl", "w") as log:
        futures = [pool.submit(_play, i, args.profile, False, not args.no_respond) for i in range(args.duels)]
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
            log.write(json.dumps(r) + "\n")
            log.flush()
            won = sum(1 for x in results if x["winner"] == x["seat"])
            progress(len(results), f"pilot {won}/{len(results)} won")
    results.sort(key=lambda r: r["i"])
    wall = time.perf_counter() - progress.t

    won = lambda r: r["winner"] == r["seat"]
    first = [r for r in results if r["seat"] == 0]
    second = [r for r in results if r["seat"] == 1]
    draws = sum(1 for r in results if r["winner"] not in (0, 1))
    n_won = sum(map(won, results))
    from edison.topdeck.matchups import wilson
    lo, hi = wilson(n_won, len(results))
    lines = [
        f"{args.profile} pilot vs random-legal: {len(results)} duels in {wall:.0f}s ({len(results) / wall:.2f} duels/s)",
        f"pilot win rate {n_won / len(results):.1%} [95% CI {lo:.1%}, {hi:.1%}] "
        f"(going first {sum(map(won, first))}/{len(first)}, going second {sum(map(won, second))}/{len(second)}, "
        f"draws/unfinished {draws})",
    ]
    from engine.constants import WIN_REASON_DECKOUT, WIN_REASON_LP
    losses = [r for r in results if r["winner"] in (0, 1) and not won(r)]
    kind = lambda r: {WIN_REASON_LP: "LP to 0", WIN_REASON_DECKOUT: "deck-out"}.get(r["reason"], f"other ({r['reason']})")
    by = Counter(kind(r) for r in losses)
    lines.append(f"losses {len(losses)}: " + ", ".join(f"{k} {v}" for k, v in by.most_common())
                 + f" | going first {sum(1 for r in losses if r['seat'] == 0)}, "
                   f"second {sum(1 for r in losses if r['seat'] == 1)}")
    rej = Counter(("pilot" if side == r["seat"] else "random", mid) for r in results for side, mid in r["rejected"])
    lines.append(f"rejected answers (engine retries) {sum(r['retries'] for r in results)}; "
                 f"by the pilot {sum(r['rejected_by_pilot'] for r in results)}; traced: {dict(rej) or 'none'}")
    ca5 = [r["ca"][r["seat"]][5] for r in results if 5 in r["ca"].get(r["seat"], {})]
    if ca5:
        lines.append(f"card advantage at turn 5: {sum(ca5) / len(ca5):+.2f} cards (mean of {len(ca5)} duels)")
    lines.append(f"response search: forks/duel {sum(r['forks'] for r in results) / len(results):.0f}, "
                 f"failed forks {sum(r.get('fork_failures', 0) for r in results)}")
    print("\n".join(lines))
    (out_dir / "summary.txt").write_text("\n".join(lines) + "\n")

    # Replays: every loss, plus --export sample duels (alternating seats, the first ones of the run).
    pilots.init()
    sample = [r for r in results if r not in losses][: args.export]
    ok, shown = 0, []
    for r in losses + sample:
        x = _play(r["i"], args.profile, export=True, respond=not args.no_respond)
        tag = "loss" if r in losses else ("win" if won(r) else "draw")
        name = (f"{args.profile}-{args.tag} duel{r['i']:03d} {'first' if r['seat'] == 0 else 'second'} "
                f"{tag}{'-' + kind(r).split()[0] if r in losses else ''}.yrp")
        good, dest = pilots.export_replay(x, out_dir / "replays" / name, edopro_subdir=f"{args.profile} {args.tag}")
        ok += good
        shown.append(str(dest or out_dir / "replays" / name))
    if shown:
        print(f"replays verified in EDOPro's engine: {ok}/{len(shown)}")
        for s in shown:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
