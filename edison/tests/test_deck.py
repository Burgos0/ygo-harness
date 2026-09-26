"""edison/deck.py: one legal deck, one test per rejection rule."""
import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.carddb import CardDB
from edison.deck import DeckError, load_ydk

POOL = {r["name"]: r for r in csv.DictReader(open(ROOT / "edison" / "cardpool.csv"))}
EXTRA_TYPES = 0x40 | 0x2000  # Fusion | Synchro (no Xyz/Link in Edison)


def pid(name: str) -> int:
    return int(POOL[name]["id"])


def _unlimited(extra: bool, n: int) -> list[int]:
    """n distinct unlimited pool cards of the main-deck or extra-deck kind, in a stable order."""
    db, out = CardDB(), []
    for name in sorted(POOL):
        r = POOL[name]
        row = db.row(int(r["id"])) if r["id"] else None
        if r["copies"] == "3" and row and bool(row[4] & EXTRA_TYPES) == extra and row[2] == 0:
            out.append(int(r["id"]))
            if len(out) == n:
                return out
    raise AssertionError("pool too small")


MAIN = [c for c in _unlimited(False, 14) for _ in range(3)][:40]   # 40 cards, 3 each
EXTRA = [c for c in _unlimited(True, 5) for _ in range(3)]         # 15 cards
SIDE = _unlimited(False, 19)[14:] * 3                               # 15 cards not in the main


def ydk(tmp_path, main=MAIN, extra=EXTRA, side=SIDE) -> Path:
    p = tmp_path / "deck.ydk"
    p.write_text("\n".join(["#main", *map(str, main), "#extra", *map(str, extra), "!side", *map(str, side)]) + "\n")
    return p


def rejected(path) -> list:
    with pytest.raises(DeckError) as e:
        load_ydk(path)
    return e.value.violations


def test_legal_deck_loads_and_resolves_aliases(tmp_path):
    main = MAIN[:-1] + [81480461]  # Barrel Dragon's alternate-art passcode
    deck = load_ydk(ydk(tmp_path, main=main))
    assert (len(deck.main), len(deck.extra), len(deck.side)) == (40, 15, 15)
    assert 81480460 in deck.main and 81480461 not in deck.main


def test_card_outside_the_pool(tmp_path):
    pot_of_desires = 35261759  # released 2013
    (v,) = rejected(ydk(tmp_path, main=MAIN[:-1] + [pot_of_desires]))
    assert v.rule == "pool" and v.card == "Pot of Desires"
    assert "Pot of Desires" in v.message and "not in the Edison card pool" in v.message


def test_banlist_counts_main_extra_and_side_together(tmp_path):
    mirror_force = pid("Mirror Force")  # Limited
    assert POOL["Mirror Force"]["copies"] == "1"
    (v,) = rejected(ydk(tmp_path, main=MAIN[:-1] + [mirror_force], side=SIDE[:-1] + [mirror_force]))
    assert v.rule == "banlist" and v.card == "Mirror Force"
    assert "2 copies across main+extra+side" in v.message and "allows 1 (Limited)" in v.message


def test_main_deck_size(tmp_path):
    (small,) = rejected(ydk(tmp_path, main=MAIN[:39]))
    assert small.rule == "main_size" and "39 cards" in small.message and "40-60" in small.message
    big = MAIN + [c for c in _unlimited(False, 21)[14:] for _ in range(3)]  # 40 + 21
    (large,) = rejected(ydk(tmp_path, main=big, side=[]))
    assert large.rule == "main_size" and "61 cards" in large.message


def test_extra_deck_size(tmp_path):
    (v,) = rejected(ydk(tmp_path, extra=EXTRA + _unlimited(True, 6)[5:]))
    assert v.rule == "extra_size" and v.card == "extra deck" and "16 cards" in v.message and "at most 15" in v.message


def test_side_deck_size(tmp_path):
    (v,) = rejected(ydk(tmp_path, side=SIDE + _unlimited(False, 20)[19:]))
    assert v.rule == "side_size" and v.card == "side deck" and "16 cards" in v.message and "at most 15" in v.message
