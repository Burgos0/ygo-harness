"""Export games from an edison.matchup run as replays, verified in EDOPro and copied to its replay folder.

    python -m edison.export_games runs/matchup-lightsworn-vs-blackwing_dad-v1-respond/matches.jsonl \
        --loser blackwing_dad --n 3

Each game is replayed from its logged key (seeds and shuffles follow from it) with the same pilots, so
the exported file is the logged game. --no-respond for a run made without response search.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from edison import pilots  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--loser", required=True, help="profile whose lost games to export")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--no-respond", action="store_true")
    args = ap.parse_args()
    games = []
    for line in open(args.log):
        m = json.loads(line)
        for g in m["games"]:
            if g["winner"] and g["winner"] != args.loser and args.loser in (m["a"], m["b"]):
                second = m["b"] if g["first"] == m["a"] else m["a"]
                games.append((m["match"], g, (g["first"], second)))
    pilots.init()
    run = args.log.parent
    ok = 0
    for match, g, specs in games[: args.n]:
        r = pilots.play(g["key"], specs, specs, export=True, respond=not args.no_respond)
        assert r["winner"] in (0, 1) and specs[r["winner"]] == g["winner"], f"game {g['key']} did not reproduce"
        side = "first" if g["first"] == args.loser else "second"
        name = f"{run.name} match{match:03d} game{g['game']} {args.loser} {side} loss.yrp"
        good, dest = pilots.export_replay(r, run / "replays" / name, edopro_subdir=run.name)
        ok += good
        print(f"  {dest or run / 'replays' / name}  (key {g['key']}, {g['turns']} turns)")
    print(f"verified in EDOPro's engine: {ok}/{min(args.n, len(games))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
