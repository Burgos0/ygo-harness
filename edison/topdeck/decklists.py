"""TopDeck.gg standings -> Edison decks, validated with edison/deck.py.

Form of each standing's decklist, in order of preference:
  deckObj  structured {"Deck"|"Extra"|"Side": {name: {"id": passcode, "count": n}}}; used when present
  text     the `decklist` string: "~~Deck~~", "~~Extra~~", "~~Side~~" headers and "N Card Name" lines.
           TopDeck ships the newlines as literal "\\n" sequences and apostrophes as "\\'"; both are undone.
           A name that is all digits is taken as a passcode. Names resolve through edison/cardpool.csv,
           then the harness card database.
  url      the decklist is only a link: counted, never fetched
  none     no decklist
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from edison.aliases import canonical
from edison.deck import EdisonDeck, Violation, validate

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = {"deck": "main", "main": "main", "mainboard": "main", "extra": "extra", "side": "side",
            "sideboard": "side"}
URL_ONLY = re.compile(r"\s*https?://\S+\s*")
LINE = re.compile(r"\s*(\d+)\s*x?\s+(.+?)\s*$")


@lru_cache(maxsize=1)
def _names() -> dict[str, int]:
    out = {}
    for r in csv.DictReader(open(ROOT / "edison" / "cardpool.csv")):
        if r["id"]:
            out[r["name"].casefold()] = canonical(r["id"])
    try:  # off-pool cards still resolve, so they fail as "not in the pool", not as unreadable
        from engine.carddb import CardDB
        for conn in CardDB().conns:
            for code, name in conn.execute("select d.id, t.name from datas d join texts t on d.id = t.id "
                                           "where d.alias = 0"):
                out.setdefault(name.casefold(), code)
    except Exception:
        pass
    return out


def _filled(obj) -> bool:
    return isinstance(obj, dict) and any(obj.get(k) for k in ("Deck", "Extra", "Side"))


def form_of(standing: dict) -> str:
    text = (standing.get("decklist") or "").strip()
    if _filled(standing.get("deckObj")):
        return "deckObj"
    if not text:
        return "none"
    return "url" if URL_ONLY.fullmatch(text) else "text"


def from_deckobj(obj: dict) -> tuple[EdisonDeck, list[str]]:
    deck = EdisonDeck()
    for section, cards in obj.items():
        target = SECTIONS.get(section.casefold())
        if target is None or not isinstance(cards, dict):
            continue
        for _name, entry in cards.items():
            getattr(deck, target).extend([canonical(int(entry["id"]))] * int(entry.get("count", 1)))
    return deck, []


def from_text(text: str) -> tuple[EdisonDeck, list[str]]:
    """(deck, names that did not resolve to a passcode)."""
    deck, target, unresolved = EdisonDeck(), "main", []
    for line in text.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"').splitlines():
        line = line.strip()
        if not line:
            continue
        header = re.fullmatch(r"~~\s*(.+?)\s*~~|#\s*(\w+)|!\s*(\w+)", line)
        if header:
            target = SECTIONS.get(next(g for g in header.groups() if g).casefold(), target)
            continue
        m = LINE.match(line)
        if not m:
            continue
        name = m.group(2)
        code = canonical(int(name)) if name.isdigit() else _names().get(name.casefold())
        if code is None:
            unresolved.append(m.group(2))
            continue
        getattr(deck, target).extend([code] * int(m.group(1)))
    return deck, unresolved


def parse(standing: dict) -> tuple[str, EdisonDeck | None, list[Violation]]:
    """(form, deck or None, violations). Unresolved text names become 'unreadable' violations."""
    form = form_of(standing)
    if form in ("none", "url"):
        return form, None, []
    deck, unresolved = (from_deckobj(standing["deckObj"]) if form == "deckObj"
                        else from_text(standing["decklist"]))
    found = [Violation("unreadable", n, f"{n}: card name not found") for n in unresolved]
    return form, deck, found + validate(deck)
