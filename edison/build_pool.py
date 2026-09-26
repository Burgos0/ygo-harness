"""Build the Edison-legal card pool and cross-check it against YGOPRODeck release dates.

    python -m edison.build_pool [--refresh]

Writes (all derived: ids, names, statuses - no card text):
  edison/cardpool.csv       every card edisonformat.net lists, minus the ones it marks "Illegal"
  edison/disagreements.csv  where YGOPRODeck's first TCG release date disagrees. Recorded, not resolved.

Disagreement categories:
  edison_not_in_ygoprodeck  legal on edisonformat.net, no YGOPRODeck card with that id or name
  edison_after_cutoff       legal on edisonformat.net, YGOPRODeck's TCG date is after the cutoff
  edison_no_tcg_date        legal on edisonformat.net, YGOPRODeck has no TCG date (not released in the TCG)
  edison_illegal_but_dated  marked Illegal on edisonformat.net, YGOPRODeck dates it on/before the cutoff
  ygoprodeck_only           YGOPRODeck TCG date on/before the cutoff, not listed by edisonformat.net
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from edison import sources

HERE = Path(__file__).resolve().parent
STATUS = {"Forbidden": 0, "Limited": 1, "Semi-Limited": 2}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download the sources")
    args = ap.parse_args()

    cutoff = sources.cutoff_date(args.refresh)
    edison = sources.edison_cards(args.refresh)
    ygo = sources.ygoprodeck_cards(args.refresh)

    by_id, by_name = {}, {}
    for c in ygo:
        misc = (c.get("misc_info") or [{}])[0]
        rec = {"id": c["id"], "name": c["name"], "type": c.get("type", ""), "tcg_date": misc.get("tcg_date", "")}
        by_name[c["name"]] = rec
        for img in c.get("card_images", []):  # alternate artworks carry their own passcodes
            by_id[img["id"]] = rec
        by_id[c["id"]] = rec

    legal, illegal, rows = [], [], []
    for c in edison:
        status = c.get("Banlist")
        (illegal if status == "Illegal" else legal).append(c)
    legal.sort(key=lambda c: (c["Name"]))

    with open(HERE / "cardpool.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "copies"])  # copies: 3 unless the Edison banlist says 0/1/2
        for c in legal:
            w.writerow([c.get("id") or "", c["Name"], STATUS.get(c.get("Banlist"), 3)])

    seen = set()
    for c in legal + illegal:
        rec = by_id.get(c.get("id")) or by_name.get(c["Name"])
        if rec:
            seen.add(rec["name"])
        edison_state = "Illegal" if c in illegal else "legal"
        if c in illegal:
            if rec and rec["tcg_date"] and rec["tcg_date"] <= cutoff:
                rows.append([c.get("id") or "", c["Name"], "edison_illegal_but_dated", edison_state,
                             rec["tcg_date"], rec["type"]])
            continue
        if rec is None:
            rows.append([c.get("id") or "", c["Name"], "edison_not_in_ygoprodeck", edison_state, "", ""])
        elif not rec["tcg_date"]:
            rows.append([c.get("id") or "", c["Name"], "edison_no_tcg_date", edison_state, "", rec["type"]])
        elif rec["tcg_date"] > cutoff:
            rows.append([c.get("id") or "", c["Name"], "edison_after_cutoff", edison_state,
                         rec["tcg_date"], rec["type"]])
    for rec in by_name.values():
        if rec["tcg_date"] and rec["tcg_date"] <= cutoff and rec["name"] not in seen:
            rows.append([rec["id"], rec["name"], "ygoprodeck_only", "not listed", rec["tcg_date"], rec["type"]])

    rows.sort(key=lambda r: (r[2], r[1]))
    with open(HERE / "disagreements.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "category", "edisonformat_net", "ygoprodeck_tcg_date", "ygoprodeck_type"])
        w.writerows(rows)

    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(f"cutoff {cutoff} ({sources.CUTOFF_SET})")
    print(f"legal {len(legal)} (playable {sum(STATUS.get(c.get('Banlist'), 3) > 0 for c in legal)}), "
          f"illegal-marked {len(illegal)}")
    print(f"disagreements {len(rows)} {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
