"""Edison duels run with the 2010 preset; everything else keeps modern rules."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import constants as K
from engine.board import read_board
from engine.duel import Duel
from edison.duel import EDISON_FLAGS, EdisonDuel
from edison.deck import load_ydk
from scenario import Scripted, Stop

DECK = ROOT / "edison" / "decks" / "blackwing_dad.ydk"
SEVEN = (K.DUEL_1ST_TURN_DRAW, K.DUEL_TCG_FAST_EFFECT_IGNITION, K.DUEL_TCG_SEGOC_FIRSTTRIGGER,
         K.DUEL_1_FACEUP_FIELD, K.DUEL_CAN_REPOS_IF_NON_SUMPLAYER, K.DUEL_0_ATK_DESTROYED)


def test_preset_is_mr5_with_the_seven_2010_rules():
    assert all(EDISON_FLAGS & f for f in SEVEN)
    assert not EDISON_FLAGS & K.DUEL_TRIGGER_ONLY_IN_LOCATION
    assert not EDISON_FLAGS & K.DUEL_OCG_OBSOLETE_IGNITION
    assert EDISON_FLAGS & ~(K.DUEL_MODE_MR5 | sum(SEVEN)) == 0, "nothing beyond MR5 and the seven"


def test_other_duels_keep_modern_rules():
    assert Duel((1, 2, 3, 4)).flags == K.MASTER_RULE_5


def test_edison_duel_refuses_other_flags():
    with pytest.raises(ValueError):
        EdisonDuel((1, 2, 3, 4), flags=K.MASTER_RULE_5)
    d = EdisonDuel((1, 2, 3, 4))
    d.flags = K.MASTER_RULE_5
    with pytest.raises(RuntimeError):
        d.start()


class Hand(Scripted):
    hand = None

    def idle(self, cmd, duel):
        self.hand = sum(1 for c in read_board(duel, 0).hand if c)
        return None


def first_hand(duel) -> int:
    deck = load_ydk(DECK)
    p = Hand()
    with duel as d:
        d.load_deck(0, deck.main, deck.extra, shuffle_seed=1)
        d.load_deck(1, deck.main, deck.extra, shuffle_seed=2)
        d.start()
        try:
            d.run(p, max_steps=500, policy1=p)
        except Stop:
            pass
    return p.hand


def test_edison_duel_actually_plays_with_the_preset():
    """Fails if an Edison duel runs without the preset: 2010 first-turn draw gives 6 cards, modern 5."""
    assert first_hand(EdisonDuel((1, 2, 3, 4))) == 6
    assert first_hand(Duel((1, 2, 3, 4))) == 5
