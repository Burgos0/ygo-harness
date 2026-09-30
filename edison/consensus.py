"""Consensus decklists: one rule for every archetype, so matchups compare decks rather than list picks.

    python -m edison.consensus lightsworn "Lightsworn" blackwing_dad "Blackwing-DAD" blackwing "Blackwing"

Rule. Take the archetype's legal lists (edison/topdeck/decks.csv) whose player finished that event with
a winning record (more wins than losses, from the TopDeck standings); require at least MIN_LISTS. For
each section (main / extra / side) and each card, the copy count is the most common count across those
lists, counting 0 for lists without it (ties go to the lower count). Then fill or trim the section to
exactly 40 / 15 / 15: the k-th copy of a card has frequency = share of lists running at least k copies;
add the most frequent missing copies, or drop the least frequent included ones. Copies across all
three sections must respect the March 2010 banlist: excess copies come out of the side first, then the
extra, then the main, each refilled by frequency. The result is validated by edison/deck.py and written
to edison/decks/<stem>_consensus.ydk.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MIN_LISTS = 20
SIZES = {"main": 40, "extra": 15, "side": 15}


def winning_lists(archetype: str) -> list[dict]:
    from edison.topdeck.analyze import load_all, pkey
    events, _ = load_all()
    record = {}
    for e in events:
        for s in e.get("standings", []):
            record[(e["TID"], pkey(s.get("id")))] = (s.get("wins") or 0, s.get("losses") or 0)
    out = []
    for r in csv.DictReader(open(ROOT / "edison" / "topdeck" / "decks.csv")):
        w, l = record.get((r["tid"], r["player"]), (0, 0))
        if r["archetype_proposed"] == archetype and r["legal"] == "True" and w > l:
            out.append(r)
    return out


def unpack(s: str) -> Counter:
    c = Counter()
    for tok in s.split():
        code, n = tok.split("x")
        c[int(code)] += int(n)
    return c


def section(lists: list[Counter], size: int, cap: dict[int, int]) -> Counter:
    """Modal counts, then fill/trim to `size` by per-copy frequency, never above cap[card]."""
    cards = set().union(*lists)
    n = len(lists)
    freq = lambda c, k: sum(1 for l in lists if l[c] >= k) / n
    out = Counter()
    for c in cards:
        counts = Counter(l[c] for l in lists)
        best = max(counts.values())
        out[c] = min(k for k, v in counts.items() if v == best)
        out[c] = min(out[c], cap.get(c, 3))
    out += Counter()                                   # drop zeros
    while sum(out.values()) < size:
        c = max((c for c in cards if out[c] < cap.get(c, 3)), key=lambda c: (freq(c, out[c] + 1), -c))
        out[c] += 1
    while sum(out.values()) > size:
        c = min(out, key=lambda c: (freq(c, out[c]), c))
        out[c] -= 1
        out += Counter()
    return out


def build(archetype: str) -> tuple[dict[str, Counter], int]:
    from edison.aliases import canonical
    from edison.deck import pool
    lists = winning_lists(archetype)
    if len(lists) < MIN_LISTS:
        raise SystemExit(f"{archetype}: only {len(lists)} winning lists (need {MIN_LISTS})")
    parsed = {sec: [Counter({canonical(c): n for c, n in unpack(r[sec]).items()}) for r in lists]
              for sec in SIZES}
    limit = {c: copies for c, (_, copies) in pool().items()}   # March 2010 banlist, via the card pool
    deck: dict[str, Counter] = {}
    used = Counter()
    for sec in ("main", "extra", "side"):          # main first: it matters most when copies collide
        cap = {c: max(0, limit.get(c, 3) - used[c]) for c in set().union(*parsed[sec])}
        deck[sec] = section(parsed[sec], SIZES[sec], cap)
        used.update(deck[sec])
    return deck, len(lists)


def write(stem: str, archetype: str) -> Path:
    deck, n = build(archetype)
    path = ROOT / "edison" / "decks" / f"{stem}_consensus.ydk"
    lines = [f"#created by edison/consensus.py: {archetype} consensus of the {n} legal lists with a winning record",
             "#(TopDeck.gg, https://topdeck.gg): modal copy count per card, filled to 40/15/15 by copy frequency",
             "#main"]
    for sec, head in (("main", None), ("extra", "#extra"), ("side", "!side")):
        if head:
            lines.append(head)
        for code, k in sorted(deck[sec].items()):
            lines += [str(code)] * k
    path.write_text("\n".join(lines) + "\n")
    from edison.deck import load_ydk
    load_ydk(path)                                  # raises DeckError listing every violation
    return path


if __name__ == "__main__":
    args = sys.argv[1:]
    for stem, arch in zip(args[::2], args[1::2]):
        print(write(stem, arch))
