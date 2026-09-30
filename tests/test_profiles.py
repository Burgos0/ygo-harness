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
    missing = (p.engine | set(p.discard_first) | p.key_cards) - names
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


# ---------------------------------------------------------------- evaluation terms

from types import SimpleNamespace as NS  # noqa: E402

from agents.lookahead import GraveResources, card_advantage  # noqa: E402
from edison.provider import EdisonScriptProvider  # noqa: E402

NECRO_GARDNA, SANGAN = 4906301, 26202165
DB = CardDB()


def board(grave=(), hand=(), monsters=(), spells=()):
    card = lambda c: NS(code=c, position=0x1, attack=0)
    return NS(grave=[card(c) for c in grave], hand=[card(c) for c in hand],
              monsters=[card(c) for c in monsters], spells=[card(c) for c in spells])


def test_grave_resources_come_from_the_cards_own_script():
    gy = GraveResources(EdisonScriptProvider())
    assert gy(NECRO_GARDNA), "Necro Gardna is used from the GY"
    assert not gy(SANGAN), "Sangan fires on the way to the GY, it is not a GY resource"


def test_card_advantage_counts_usable_gy_as_half_a_card():
    gy = GraveResources(EdisonScriptProvider())
    assert card_advantage(board(hand=[1, 2], grave=[NECRO_GARDNA]), board(hand=[1, 2]), gy) == 0.5
    assert card_advantage(board(), board(), gy, hidden_opp_hand=3, hidden_opp_set=1) == -4


def names(deck, pred):
    d = load_ydk(ROOT / deck)
    return list(dict.fromkeys(c for c in d.main if pred(c)))


def test_lightsworn_progress_counts_distinct_names_toward_four():
    prog = PROFILES["lightsworn"].progress
    ls = names(PROFILES["lightsworn"].deck, lambda c: "Lightsworn" in DB.archetypes(c) and DB.row(c)[4] & 0x1)
    assert len(ls) >= 5
    three, four, five = (prog(board(grave=ls[:k]), board(), DB) for k in (3, 4, 5))
    assert three < four == five, "progress stops at 4 names"
    assert prog(board(grave=[ls[0]] * 4), board(), DB) == prog(board(grave=ls[:1]), board(), DB), "copies are one name"


def test_dad_progress_wants_exactly_three_darks():
    prog = PROFILES["blackwing_dad"].progress
    darks = [c for c in load_ydk(ROOT / PROFILES["blackwing_dad"].deck).main
             if DB.row(c)[4] & 0x1 and DB.row(c)[9] & 0x20]
    two, three, four = (prog(board(grave=darks[:k]), board(), DB) for k in (2, 3, 4))
    assert two < three and four < three, "exactly 3 is best; a 4th DARK is penalized"
