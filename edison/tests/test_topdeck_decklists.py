"""edison/topdeck/decklists.py on hand-built standings (no network, no API key)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from edison.aliases import canonical
from edison.topdeck.decklists import form_of, from_deckobj, from_text, parse

# TopDeck ships text with literal "\n" and escaped apostrophes.
TEXT = (r"~~Deck~~\n3 Vanity\'s Fiend\n1 Mirror Force\n2 70095155\n\n~~Side~~\n1 Mystical Space Typhoon"
        r"\n\n~~Extra~~\n1 Stardust Dragon\n")


def test_text_undoes_escapes_and_reads_passcode_names():
    deck, unresolved = from_text(TEXT)
    assert unresolved == []
    assert len(deck.main) == 6 and deck.main.count(canonical(70095155)) == 2  # passcodes are canonicalized too
    assert len(deck.side) == 1 and len(deck.extra) == 1


def test_deckobj_uses_canonical_passcodes():
    obj = {"Deck": {"Barrel Dragon": {"id": "81480461", "count": 2}}, "Side": {}, "Extra": {},
           "metadata": {"game": "Yu-Gi-Oh", "format": "Edison"}}
    deck, _ = from_deckobj(obj)
    assert deck.main == [81480460, 81480460]  # alternate art -> canonical (edison/aliases.csv)


def test_forms_and_url_is_counted_not_fetched():
    assert form_of({"decklist": "https://example.com/deck/123"}) == "url"
    assert form_of({"decklist": ""}) == "none"
    assert form_of({"decklist": TEXT}) == "text"
    assert form_of({"decklist": TEXT, "deckObj": {"Deck": {"Mirror Force": {"id": "44095762", "count": 1}}}}) \
        == "deckObj"
    assert parse({"decklist": "https://example.com/deck/123"})[1] is None


def test_unknown_name_is_reported_not_dropped():
    _, deck, violations = parse({"decklist": r"~~Deck~~\n1 Not A Real Card Name\n"})
    assert any(v.rule == "unreadable" and v.card == "Not A Real Card Name" for v in violations)
