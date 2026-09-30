"""Deck profiles for the generic lookahead pilot."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.lookahead import FILLER, PLACEHOLDER, LookaheadPilot
from agents.profiles import PROFILES
from agents.random_legal import RandomLegal
from edison.deck import load_ydk
from edison.duel import EdisonDuel
from engine.carddb import CardDB
from engine.constants import MSG_SELECT_IDLECMD

ADD = re.compile(r"Debug\.AddCard\((\d+),(\d),(\d),(\d+),(\d+),(\d+)")


def test_the_generic_pilot_names_no_card():
    src = (ROOT / "agents" / "lookahead.py").read_text()
    for p in PROFILES.values():
        for name in p.engine | set(p.discard_first):
            assert f'"{name}"' not in src, f"{name} belongs in a profile, not in lookahead.py"


@pytest.mark.parametrize("key", sorted(PROFILES))
def test_profile_names_are_cards_in_its_deck(key):
    p, db = PROFILES[key], CardDB()
    deck = load_ydk(ROOT / p.deck)
    names = {db.name(c) for c in deck.main + deck.extra}
    missing = (p.engine | set(p.discard_first)) - names
    assert not missing, f"{key}: named cards not in {p.deck}: {missing} - a typo would silently do nothing"


@pytest.mark.parametrize("key", sorted(PROFILES))
def test_copies_hide_the_opponent(key):
    """Same guarantee as tests/test_lightsworn_pilot.py, for every profile."""
    class Capture(LookaheadPilot):
        def __call__(self, msg, duel):
            if msg is not None and msg.id == MSG_SELECT_IDLECMD and not hasattr(self, "snap"):
                self._hook(duel)
                self.snap = self._snapshot(duel)
                raise StopIteration
            return super().__call__(msg, duel)

    mine = load_ydk(ROOT / PROFILES[key].deck)
    other = load_ydk(ROOT / PROFILES["lightsworn" if key != "lightsworn" else "blackwing_dad"].deck)
    p = Capture(PROFILES[key], seat=0, seed=3)
    with EdisonDuel((5, 6, 7, 8)) as d:
        d.load_deck(0, mine.main, mine.extra, shuffle_seed=3)
        d.load_deck(1, other.main, other.extra, shuffle_seed=4)
        p.attach(d)
        d.start()
        with pytest.raises(StopIteration):
            d.run(p, max_steps=2000, policy1=RandomLegal(seed=3))
    theirs = [tuple(map(int, m.groups())) for m in ADD.finditer(p.snap["lua"]) if m.group(2) == "1"]
    assert not any(loc == 0x02 for *_, loc, _, _ in theirs), "opponent's hand must not be in the copy"
    assert {c[0] for c in theirs if c[3] == 0x01} <= {FILLER}
    assert {c[0] for c in theirs if c[3] in (0x04, 0x08) and not c[5] & 0x5} <= {PLACEHOLDER}
