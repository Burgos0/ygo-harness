"""Load a .ydk as an Edison deck: resolve alternate-art passcodes, then enforce the format.

    from edison.deck import load_ydk, DeckError
    deck = load_ydk("my.ydk")          # raises DeckError listing every violation

Rules (each Violation names the card or section and the rule):
  pool       every card must be in the Edison card pool (edison/cardpool.csv)
  banlist    copies of a card, counted across main + extra + side, must not exceed the March 2010
             banlist (0 Forbidden / 1 Limited / 2 Semi-Limited / 3 otherwise). Alternate artworks
             count as the same card (edison/aliases.csv).
  main_size  main deck 40-60 cards
  extra_size extra deck at most 15
  side_size  side deck at most 15
Passcodes in the returned deck are canonical, so they match the harness card database.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from edison.aliases import canonical

HERE = Path(__file__).resolve().parent
MAIN_MIN, MAIN_MAX, EXTRA_MAX, SIDE_MAX = 40, 60, 15, 15
STATUS = {0: "Forbidden", 1: "Limited", 2: "Semi-Limited", 3: "Unlimited"}


@dataclass(frozen=True)
class Violation:
    rule: str
    card: str  # card name, or the deck section for size rules
    message: str


class DeckError(ValueError):
    def __init__(self, path: Path, violations: list[Violation]):
        self.path, self.violations = path, violations
        super().__init__(f"{path.name}: not Edison-legal:\n" + "\n".join(f"  - {v.message}" for v in violations))


@dataclass
class EdisonDeck:
    main: list[int] = field(default_factory=list)
    extra: list[int] = field(default_factory=list)
    side: list[int] = field(default_factory=list)


@lru_cache(maxsize=1)
def pool() -> dict[int, tuple[str, int]]:
    """canonical passcode -> (name, copies allowed)."""
    out = {}
    for r in csv.DictReader(open(HERE / "cardpool.csv")):
        if r["id"]:
            out[canonical(r["id"])] = (r["name"], int(r["copies"]))
    return out


def _name(code: int) -> str:
    if code in pool():
        return pool()[code][0]
    try:
        from engine.carddb import CardDB
        return CardDB().name(code) or f"unknown card"
    except Exception:
        return "unknown card"


def parse_ydk(path: Path) -> EdisonDeck:
    deck, section = EdisonDeck(), None
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line in ("#main", "#extra", "!side"):
            section = {"#main": deck.main, "#extra": deck.extra, "!side": deck.side}[line]
        elif line and line[0].isdigit() and section is not None:
            section.append(canonical(int(line.split()[0])))
    return deck


def validate(deck: EdisonDeck) -> list[Violation]:
    found: list[Violation] = []
    for label, cards, lo, hi, rule in (("main deck", deck.main, MAIN_MIN, MAIN_MAX, "main_size"),
                                       ("extra deck", deck.extra, 0, EXTRA_MAX, "extra_size"),
                                       ("side deck", deck.side, 0, SIDE_MAX, "side_size")):
        if not lo <= len(cards) <= hi:
            bound = f"{lo}-{hi}" if lo else f"at most {hi}"
            found.append(Violation(rule, label, f"{label}: {len(cards)} cards, the rule is {bound}"))
    counts = Counter(deck.main + deck.extra + deck.side)
    for code in sorted(counts, key=_name):
        name = _name(code)
        if code not in pool():
            found.append(Violation("pool", name, f"{name} ({code}): not in the Edison card pool"))
            continue
        allowed = pool()[code][1]
        if counts[code] > allowed:
            found.append(Violation("banlist", name,
                                   f"{name} ({code}): {counts[code]} copies across main+extra+side, the "
                                   f"March 2010 banlist allows {allowed} ({STATUS[allowed]})"))
    return found


def load_ydk(path: str | Path) -> EdisonDeck:
    path = Path(path)
    deck = parse_ydk(path)
    violations = validate(deck)
    if violations:
        raise DeckError(path, violations)
    return deck
