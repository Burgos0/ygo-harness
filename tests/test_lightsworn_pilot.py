"""The Lightsworn pilot's lookahead copies must not see hidden information."""
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.lightsworn import FILLER, PLACEHOLDER, LightswornPilot
from agents.random_legal import RandomLegal
from edison.deck import load_ydk
from edison.duel import EdisonDuel
from engine.board import read_board
from engine.constants import MSG_SELECT_IDLECMD

LS = load_ydk(ROOT / "edison" / "decks" / "lightsworn.ydk")
BW = load_ydk(ROOT / "edison" / "decks" / "blackwing_dad.ydk")
ADD = re.compile(r"Debug\.AddCard\((\d+),(\d),(\d),(\d+),(\d+),(\d+)")


class Capture(LightswornPilot):
    """Grabs the first snapshot and the real hidden state at that moment, then stops."""

    def __call__(self, msg, duel):
        if msg is not None and msg.id == MSG_SELECT_IDLECMD and not hasattr(self, "snap"):
            self._hook(duel)
            self.real_deck = [c.code for c in read_board(duel, self.me).deck if c]
            opp = read_board(duel, 1 - self.me)
            self.opp_hand = {c.code for c in opp.hand if c}
            self.opp_facedown = {c.code for c in opp.monsters + opp.spells if c and not c.position & 0x5}
            self.snap = self._snapshot(duel)
            raise StopIteration
        return super().__call__(msg, duel)


def snapshot():
    p = Capture(seat=0, seed=3)
    with EdisonDuel((5, 6, 7, 8)) as d:
        d.load_deck(0, LS.main, LS.extra, shuffle_seed=3)
        d.load_deck(1, BW.main, BW.extra, shuffle_seed=4)
        p.attach(d)
        d.start()
        try:
            d.run(p, max_steps=2000, policy1=RandomLegal(seed=3))
        except StopIteration:
            pass
    return p, [tuple(map(int, m.groups())) for m in ADD.finditer(p.snap["lua"])]


def test_copy_has_no_opponent_hand_and_no_hidden_identities():
    p, cards = snapshot()
    theirs = [c for c in cards if c[2] == 1]
    assert not any(loc == 0x02 for _, _, _, loc, _, _ in theirs), "opponent's hand must not be in the copy"
    assert {code for code, *_ in theirs if _[2] == 0x01} <= {FILLER}, "opponent's Deck is filler only"
    hidden = {code for code, _, _, loc, _, pos in theirs if loc in (0x04, 0x08) and not pos & 0x5}
    assert hidden <= {PLACEHOLDER}, "opponent's face-down cards must not keep their identity"
    assert p.opp_hand, "the opponent does hold cards - otherwise this proves nothing"


def test_our_deck_order_is_not_the_real_one():
    p, cards = snapshot()
    ours = [code for code, _, player, loc, _, _ in cards if player == 0 and loc == 0x01]
    assert sorted(ours) == sorted(p.real_deck), "same contents"
    assert ours != p.real_deck, "but not the real draw order"
