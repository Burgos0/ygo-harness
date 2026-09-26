"""Which Edison-legal cards the harness engine cannot fully load.

    python -m edison.check_engine

For every card in edison/cardpool.csv with a passcode, resolved through edison/aliases.csv:
  missing_cdb     no row in the harness card databases (data/BabelCDB)
  missing_script  a non-Normal card whose c<passcode>.lua (or its alias's) is found neither in
                  edison/scripts nor in data/CardScripts - it would load with no effects (trap 1).
                  Normal monsters have no script by design (trap 22) and are not counted.
Writes edison/engine_gaps.csv.
"""
from __future__ import annotations

import csv
from pathlib import Path

from engine.carddb import CardDB
from edison.aliases import canonical
from edison.provider import EdisonScriptProvider

HERE = Path(__file__).resolve().parent
TYPE_MONSTER, TYPE_NORMAL, TYPE_TOKEN = 0x1, 0x10, 0x4000


def main() -> int:
    db, sp = CardDB(), EdisonScriptProvider()
    gaps = []
    for r in csv.DictReader(open(HERE / "cardpool.csv")):
        if not r["id"]:
            continue
        row = db.row(canonical(r["id"]))
        if row is None:
            gaps.append((r["id"], r["name"], "missing_cdb"))
            continue
        code, alias, type_ = row[0], row[2], row[4]
        vanilla = type_ & TYPE_MONSTER and type_ & TYPE_NORMAL or type_ & TYPE_TOKEN
        if not vanilla and sp.read(f"c{code}.lua") is None and not (alias and sp.read(f"c{alias}.lua")):
            gaps.append((r["id"], r["name"], "missing_script"))
    with open(HERE / "engine_gaps.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "gap"])
        w.writerows(gaps)
    for kind in ("missing_cdb", "missing_script"):
        names = [g[1] for g in gaps if g[2] == kind]
        print(f"{kind} {len(names)}{': ' + ', '.join(names[:8]) if names else ''}{' ...' if len(names) > 8 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
