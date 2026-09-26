"""April 2010 card text: Edison plays some cards as they read then (edisonformat.net/rules/errata).

edison/errata_2010.csv lists the 18 cards the site names. For the 10 that the card database has as a
separate "<name> (Pre-Errata)" card, a deck that lists the normal passcode plays the pre-errata one:

    play_code(26202165)  -> 511002631   # Sangan -> Sangan (Pre-Errata), the 2010 text
    rules_code(511002631) -> 26202165   # the same card for the pool and copy limits

The other 8 have no pre-errata card; their 2010 behavior needs an override script in edison/scripts.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

CSV = Path(__file__).resolve().parent / "errata_2010.csv"


@lru_cache(maxsize=1)
def _to_2010() -> dict[int, int]:
    return {int(r["pool_passcode"]): int(r["pre_errata_passcode"])
            for r in csv.DictReader(open(CSV)) if r["pool_passcode"] and r["pre_errata_passcode"]}


@lru_cache(maxsize=1)
def _from_2010() -> dict[int, int]:
    return {pre: normal for normal, pre in _to_2010().items()}


def play_code(code: int) -> int:
    """The passcode to put in the duel: the 2010-text version where one exists."""
    return _to_2010().get(code, code)


def rules_code(code: int) -> int:
    """The passcode deck-building rules see: a pre-errata version counts as the normal card."""
    return _from_2010().get(code, code)
