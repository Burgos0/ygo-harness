"""Deck profiles for the generic lookahead pilot."""
import re
import struct
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


def test_hold_scale_follows_the_board():
    from agents.lookahead import Weights, hold_scale
    w = Weights()
    mon = lambda atk, status=0: NS(code=1, position=0x1, attack=atk, status=status)
    side = lambda *m: NS(monsters=list(m))
    assert hold_scale(side(mon(2000)), side(mon(1000)), w) == 1.0, "ahead: full value"
    assert hold_scale(side(mon(1000)), side(mon(2500)), w) == 0.5, "1500 behind of 3000: half"
    assert hold_scale(side(), side(mon(1500), mon(1500)), w) == 0.0, "3000 behind: none"
    assert hold_scale(side(mon(2800)), side(mon(2700, 0x40000000)), w) == 1.0, "new monster, but ours is bigger"
    assert hold_scale(side(mon(2500), mon(2000)), side(mon(2700, 0x40000000)), w) == 0.0, "new bigger threat: none"


def test_threat_counts_extra_deck_bosses_and_field_effects():
    from agents.lookahead import Weights, threat
    w, gy = Weights(), GraveResources(EdisonScriptProvider())
    THOUGHT_RULER, CHAOS_SORCERER, PLAGUESPREADER = 70780151, 9596126, 33420078
    mon = lambda code, atk, typ, lv: NS(code=code, attack=atk, type=typ, level=lv)
    tra = threat(mon(THOUGHT_RULER, 2700, 0x2021, 8), w, gy)
    cs = threat(mon(CHAOS_SORCERER, 2300, 0x21, 6), w, gy)
    assert tra == 2700 + w.threat_extra + w.threat_field_effect, "Synchro with an on-field effect"
    assert cs == 2300 + w.threat_field_effect, "Main Deck, an ignition effect on the field, not a boss by level"
    assert threat(mon(PLAGUESPREADER, 400, 0x1021, 2), w, gy) == 400, "its effect is used from the GY"


def test_reveals_hand_reads_confirm_cards():
    from agents.lookahead import reveals_hand
    msg = lambda cards: NS(id=31, payload=bytes([0]) + struct.pack("<I", len(cards))
                           + b"".join(struct.pack("<IBBI", c, con, loc, 0) for c, con, loc in cards))
    assert reveals_hand(msg([(1, 1, 0x02)]), 1), "one of player 1's hand cards shown"
    assert not reveals_hand(msg([(1, 1, 0x04)]), 1), "a monster zone card is not the hand"
    assert not reveals_hand(msg([(1, 0, 0x02)]), 1), "the other player's hand"


def test_lp_cost_is_cheap_far_from_lethal_and_dear_near_it():
    import math
    from agents.lookahead import Weights
    w = Weights()
    v = lambda lp, dmg: w.lp_value * (1 - math.exp(-(lp / max(w.lp_floor_damage, dmg)) / w.lp_tau))
    far = v(8000, 1000) - v(4000, 1000)
    near = v(3000, 2700) - v(1500, 2700)
    assert far < 10 < 60 < near, (far, near)
