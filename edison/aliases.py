"""Alternate-artwork passcodes -> canonical passcode, from edison/aliases.csv.

    from edison.aliases import canonical
    canonical(81480461)  # -> 81480460 (Barrel Dragon)

Only alternate artworks of the *same* card are folded. Name aliases ("always treated as
Harpie Lady", "treated as Umi") are different cards and are deliberately not in the file.

    python -m edison.aliases        # rebuild aliases.csv (run edison.build_pool first)

Sources, in the `source` column:
  ygoprodeck  YGOPRODeck lists every artwork passcode of a card under card_images
  cdb         a BabelCDB row whose `alias` points at a passcode within ARTWORK_OFFSET
              (EDOPro's artwork-version spacing; name aliases are far apart)
  manual      MANUAL below
The canonical passcode is the one present in BabelCDB as a non-alias row. A card where that
is not exactly one passcode is reported and left out rather than guessed.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV = HERE / "aliases.csv"
ARTWORK_OFFSET = 20

#: (alternate, canonical, name) - known cases, kept even if a source changes.
MANUAL = [(81480461, 81480460, "Barrel Dragon")]


@lru_cache(maxsize=1)
def table() -> dict[int, int]:
    if not CSV.exists():
        return {}
    return {int(r["alt_passcode"]): int(r["canonical_passcode"]) for r in csv.DictReader(open(CSV))}


def canonical(code: int) -> int:
    return table().get(int(code), int(code))


def build() -> int:
    import sys
    sys.path.insert(0, str(HERE.parent))
    from engine.carddb import CardDB
    from edison import sources

    db = CardDB()
    pool = [r for r in csv.DictReader(open(HERE / "cardpool.csv")) if r["id"]]
    pool_ids = {int(r["id"]) for r in pool}
    pool_names = {r["name"] for r in pool}

    def is_base(code: int) -> bool:
        row = db.row(code)
        return row is not None and row[2] == 0

    rows: dict[int, tuple[int, str, str]] = {}
    unresolved = []
    for c in sources.ygoprodeck_cards():
        if c["name"] not in pool_names:
            continue
        codes = sorted({c["id"], *(i["id"] for i in c.get("card_images", []))})
        if len(codes) < 2:
            continue
        bases = [x for x in codes if is_base(x)]
        if len(bases) != 1:
            unresolved.append((c["name"], codes, bases))
            continue
        for x in codes:
            if x != bases[0]:
                rows[x] = (bases[0], c["name"], "ygoprodeck")
    names = {int(r["id"]): r["name"] for r in pool}
    for conn in db.conns:
        for code, alias in conn.execute("select id, alias from datas where alias != 0"):
            if abs(code - alias) <= ARTWORK_OFFSET and (alias in pool_ids or code in pool_ids) \
                    and code not in rows and is_base(alias):
                rows[code] = (alias, names.get(code) or names.get(alias) or db.name(alias), "cdb")
    for alt, base, name in MANUAL:
        rows[alt] = (base, name, "manual")

    with open(CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["alt_passcode", "canonical_passcode", "name", "source"])
        for alt in sorted(rows, key=lambda a: (rows[a][1], a)):
            w.writerow([alt, *rows[alt]])
    table.cache_clear()
    print(f"aliases {len(rows)} ({', '.join(f'{s} {sum(1 for v in rows.values() if v[2] == s)}' for s in ('ygoprodeck', 'cdb', 'manual'))}); "
          f"unresolved {len(unresolved)}{': ' + str(unresolved[:5]) if unresolved else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
