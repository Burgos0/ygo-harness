"""Real-world Edison matchup matrix from TopDeck.gg results (data provided by https://topdeck.gg).

    python -m edison.topdeck.matchups       # reads decks.csv + matches.csv (committed, derived)

Only completed 1v1 matches where BOTH players' decklists are known are used. Labels come from
decks.csv `archetype_proposed`; for this analysis any label under POOL_BELOW of all decks is pooled
into "Other" (the data keeps the original labels).

Match win rate = wins / (wins + losses); draws are reported but excluded from the rate. 95% interval:
Wilson. Mirror matches (same pooled label, including Other vs Other) are left out of a deck's overall
rate: they are 50% by construction.
Game win rate = games won / games played, from winner_games/loser_games (drawn and unscored matches
have none). Games are clustered in matches, so its 95% interval is a percentile bootstrap over matches,
not a per-game Wilson interval (that would be too narrow).
Cells with fewer than FLAG_BELOW matches are flagged.

Writes matchups.csv (long form) and matchups.md.
"""
from __future__ import annotations

import csv
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
POOL_BELOW = 0.02
FLAG_BELOW = 100
BOOT = 2000
Z = 1.959964


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return (c - h, c + h)


def game_rate(pairs: list[tuple[int, int]], rng: random.Random) -> tuple[float, float, float, int]:
    """pairs: (games won, games lost) per match, from one side. -> rate, lo, hi, games."""
    if not pairs:
        return (math.nan, math.nan, math.nan, 0)
    won, total = sum(w for w, _ in pairs), sum(w + l for w, l in pairs)
    boots = []
    for _ in range(BOOT):
        s = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        t = sum(w + l for w, l in s)
        boots.append(sum(w for w, _ in s) / t if t else math.nan)
    boots.sort()
    return (won / total, boots[int(0.025 * BOOT)], boots[int(0.975 * BOOT) - 1], total)


def main() -> int:
    rng = random.Random(0)
    label = {}
    for r in csv.DictReader(open(HERE / "decks.csv")):
        label[(r["tid"], r["player"])] = r["archetype_proposed"]
    share = Counter(label.values())
    n_decks = len(label)
    pooled = {a for a, k in share.items() if k / n_decks < POOL_BELOW}
    group = lambda a: "Other" if a in pooled else a

    # per ordered pair (A, B): A's wins, losses, draws and game pairs
    cell = defaultdict(lambda: {"w": 0, "l": 0, "d": 0, "games": []})
    used = 0
    for r in csv.DictReader(open(HERE / "matches.csv")):
        if r["both_decklists"] != "True" or r["result"] not in ("p1", "p2", "draw"):
            continue
        a, b = group(label[(r["tid"], r["p1"])]), group(label[(r["tid"], r["p2"])])
        used += 1
        wg = int(r["winner_games"]) if r["winner_games"] not in ("", "None") else None
        lg = int(r["loser_games"]) if r["loser_games"] not in ("", "None") else None
        for me, them, i_won in ((a, b, r["result"] == "p1"), (b, a, r["result"] == "p2")):
            c = cell[(me, them)]
            if r["result"] == "draw":
                c["d"] += 1
                continue
            c["w" if i_won else "l"] += 1
            if wg is not None and lg is not None:
                c["games"].append((wg, lg) if i_won else (lg, wg))

    archetypes = sorted({a for a, _ in cell}, key=lambda a: (a in ("Other", "Unclassified"), -share.get(a, 0), a))
    rows, overall = [], {}
    for a in archetypes:
        agg = {"w": 0, "l": 0, "d": 0, "games": []}
        for b in archetypes:
            c = cell.get((a, b))
            if not c:
                continue
            n = c["w"] + c["l"] + c["d"]
            lo, hi = wilson(c["w"], c["w"] + c["l"])
            g, glo, ghi, games = game_rate(c["games"], rng)
            rows.append([a, b, n, c["w"], c["l"], c["d"], c["w"] / max(1, c["w"] + c["l"]), lo, hi,
                         g, glo, ghi, games, a == b, n < FLAG_BELOW])
            if a != b:
                for k in ("w", "l", "d"):
                    agg[k] += c[k]
                agg["games"] += c["games"]
        n = agg["w"] + agg["l"] + agg["d"]
        overall[a] = (n, agg["w"], agg["l"], agg["d"], agg["w"] / max(1, agg["w"] + agg["l"]),
                      *wilson(agg["w"], agg["w"] + agg["l"]), *game_rate(agg["games"], rng))

    with open(HERE / "matchups.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["archetype", "opponent", "matches", "wins", "losses", "draws", "match_wr", "match_lo",
                    "match_hi", "game_wr", "game_lo", "game_hi", "games", "mirror", "under_100"])
        w.writerows([[x if not isinstance(x, float) else round(x, 4) for x in r] for r in rows])

    pct = lambda x: "—" if x != x else f"{100 * x:.1f}"
    md = ["# Edison matchups (real-world, TopDeck.gg)", "",
          "Data provided by [TopDeck.gg](https://topdeck.gg). Completed 1v1 matches with both decklists "
          f"known: **{used}**. Archetype labels are the PROPOSED groupings; labels under "
          f"{100 * POOL_BELOW:.0f}% of decks are pooled into Other ({', '.join(sorted(pooled))}).", "",
          "Match win rate = W/(W+L), Wilson 95%; mirrors excluded from overall. Game win rate from game "
          "scores, 95% bootstrap over matches. `*` = fewer than 100 matches.", "",
          "## Overall", "", "| Archetype | Decks | Matches | W-L-D | Match win % [95% CI] | Game win % [95% CI] (games) |",
          "|---|---|---|---|---|---|"]
    for a in archetypes:
        n, w_, l, d, wr, lo, hi, g, glo, ghi, games = overall[a]
        decks = sum(k for x, k in share.items() if group(x) == a)
        md.append(f"| {a} | {decks} | {n}{'*' if n < FLAG_BELOW else ''} | {w_}-{l}-{d} | "
                  f"{pct(wr)} [{pct(lo)}, {pct(hi)}] | {pct(g)} [{pct(glo)}, {pct(ghi)}] ({games}) |")
    md += ["", "## Head to head (row's match win %, [95% CI], matches)", "",
           "| vs | " + " | ".join(archetypes) + " |", "|---|" + "---|" * len(archetypes)]
    by = {(r[0], r[1]): r for r in rows}
    for a in archetypes:
        cells = []
        for b in archetypes:
            r = by.get((a, b))
            if r is None:
                cells.append("—")
            elif a == b:
                cells.append(f"mirror ({r[2]})")
            else:
                cells.append(f"{pct(r[6])} [{pct(r[7])}, {pct(r[8])}] {r[2]}{'*' if r[14] else ''}")
        md.append(f"| **{a}** | " + " | ".join(cells) + " |")
    md += ["", "Per-cell game win rates and exact counts: `matchups.csv`.", ""]
    (HERE / "matchups.md").write_text("\n".join(md))

    flagged = sum(1 for r in rows if r[14] and not r[13])
    print(f"matches used {used}; pooled into Other: {sorted(pooled)}")
    for a in archetypes:
        n, w_, l, d, wr, lo, hi, g, glo, ghi, games = overall[a]
        print(f"  {a:18s} n={n:5d} match {pct(wr)}% [{pct(lo)},{pct(hi)}]  game {pct(g)}% [{pct(glo)},{pct(ghi)}]")
    print(f"head-to-head cells (non-mirror) {sum(1 for r in rows if not r[13])}, flagged <{FLAG_BELOW}: {flagged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
