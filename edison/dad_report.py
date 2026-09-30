"""Blackwing-DAD guide metrics from edison.matchup logs (docs/guides/blackwing-dad.md).

    python -m edison.dad_report runs/matchup-lightsworn-vs-blackwing_dad-<tag>/matches.jsonl [...]

Per game, for the Blackwing-DAD pilot: Vayu GY activations (Main Phase menu), Icarus Attack activations
split into "in response to removal" (a chain window where one of our monsters was targeted) and plain
trades, and Return from the Different Dimension activations with how many were lethal (Blackwing-DAD
won the game on the turn it was activated). Chain-window data exists in every run; the Main Phase
activation log ("actions") only from tuning round 2 on.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.carddb import CardDB  # noqa: E402

DB = CardDB()
SIDE = "blackwing_dad"


def report(path: Path) -> str:
    games = [g for line in open(path) for g in json.loads(line)["games"]]
    n = len(games)
    name = DB.name
    has_actions = any("actions" in g for g in games)
    vayu = icarus_resp = icarus_trade_chain = icarus_idle = rftdd = rftdd_lethal = 0
    for g in games:
        acts = g.get("actions", {}).get(SIDE, [])
        wins = g["windows"].get(SIDE, [])
        vayu += sum(1 for a in acts if name(a["code"]) == "Blackwing - Vayu the Emblem of Honor")
        for w in wins:
            if w["taken"] and name(w["taken"]) == "Icarus Attack":
                if w.get("mine_targeted", 0) > 0:
                    icarus_resp += 1
                else:
                    icarus_trade_chain += 1
        icarus_idle += sum(1 for a in acts if name(a["code"]) == "Icarus Attack")
        turns = [w["turn"] for w in wins if w["taken"] and name(w["taken"]) == "Return from the Different Dimension"]
        turns += [a["turn"] for a in acts if name(a["code"]) == "Return from the Different Dimension"]
        rftdd += len(turns)
        rftdd_lethal += sum(1 for t in turns if g["winner"] == SIDE and t == g["turns"])
    lines = [f"{path}: {n} games"]
    if has_actions:
        lines.append(f"  Vayu activations: {vayu} ({vayu / n:.2f}/game)")
    else:
        lines.append("  Vayu activations: not logged in this run (no Main Phase action log)")
    lines.append(f"  Icarus Attack: in response to removal {icarus_resp} ({icarus_resp / n:.2f}/game), plain trades "
                 f"{icarus_trade_chain + icarus_idle} ({(icarus_trade_chain + icarus_idle) / n:.2f}/game: "
                 f"{icarus_trade_chain} in chain windows"
                 + (f", {icarus_idle} from the Main Phase menu)" if has_actions else ", Main Phase not logged)"))
    lines.append(f"  RftDD activations: {rftdd} ({rftdd / n:.2f}/game), lethal {rftdd_lethal}"
                 + ("" if has_actions else " (chain windows only)"))
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    for p in ap.parse_args().paths:
        print(report(p))
