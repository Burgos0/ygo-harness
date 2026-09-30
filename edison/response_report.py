"""How a pilot uses its responses: chain windows available, taken, passed - and trap timing.

    python -m edison.response_report runs/blackwing_dad-v1-respond/duels.jsonl [--profile blackwing_dad]
    python -m edison.response_report runs/matchup-.../matches.jsonl --profile blackwing_dad

Reads the per-duel window logs written by edison.pilot_eval (duels.jsonl) or edison.matchup
(matches.jsonl). A window is one chain prompt to the pilot with at least one option. "Trap window" = at
least one option was a Trap. Timing is whose turn, which phase, and what the window answered (an attack
declaration, a summon, a chain link, or just a phase change).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def windows(path: Path, profile: str | None) -> tuple[int, list[dict]]:
    duels, out = 0, []
    for line in open(path):
        r = json.loads(line)
        if "games" in r:                                   # matchup: one line per match
            for g in r["games"]:
                duels += 1
                out += g["windows"].get(profile, [])
        else:                                              # pilot_eval: one line per duel
            duels += 1
            out += r["windows"].get(str(r["seat"]), [])
    return duels, out


def report(path: Path, profile: str | None) -> str:
    n, ws = windows(path, profile)
    trap = [w for w in ws if w["trap_options"]]
    act = [w for w in trap if w["taken_trap"]]
    lines = [f"{path}: {n} duels, {len(ws)} chain windows with options ({len(ws) / n:.1f}/duel), "
             f"taken {sum(1 for w in ws if w['taken'] is not None)}, passed {sum(1 for w in ws if w['taken'] is None)}, "
             f"searched {sum(1 for w in ws if w['searched'])}",
             f"trap windows {len(trap)} ({len(trap) / n:.1f}/duel); traps activated {len(act)} "
             f"({len(act) / n:.2f}/duel) = {len(act) / max(1, len(trap)):.1%} of trap windows"]
    for label, key in (("turn", lambda w: "opponent's turn" if not w["own_turn"] else "own turn"),
                       ("event", lambda w: w["event"]), ("phase", lambda w: w["phase"])):
        c = Counter(map(key, act))
        lines.append(f"  activations by {label}: " + ", ".join(f"{k} {v} ({v / max(1, len(act)):.0%})"
                                                              for k, v in c.most_common()))
    from engine.carddb import CardDB
    db = CardDB()
    c = Counter(db.name(w["taken"]) for w in act)
    lines.append("  activations by card: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    avail = Counter(w["event"] for w in trap)
    took = Counter(w["event"] for w in act)
    lines.append("  activation rate by event: " + ", ".join(
        f"{e} {took[e]}/{avail[e]} ({took[e] / avail[e]:.0%})" for e, _ in avail.most_common()))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--profile", default="blackwing_dad")
    args = ap.parse_args()
    for p in args.paths:
        print(report(p, args.profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
