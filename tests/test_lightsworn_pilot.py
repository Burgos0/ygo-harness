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


# ---------------------------------------------------------------- behaviour on fixed game states

sys.path.insert(0, str(ROOT / "edison" / "tests"))
from engine.constants import DUEL_ATTACK_FIRST_TURN, MSG_SELECT_BATTLECMD  # noqa: E402
from engine.messages import BATTLE_ATTACK, IDLE_ACTIVATE  # noqa: E402
from edison.duel import EDISON_FLAGS  # noqa: E402
from edison.provider import EdisonScriptProvider  # noqa: E402
from scenario import Scripted, run  # noqa: E402

LUMINA, EHREN, WULF, GAROTH, JAIN, LYLA, SANGAN, ELF = (95503687, 44178886, 58996430, 59019082,
                                                        96235275, 22624373, 26202165, 15025844)


class PilotVsPassive(Scripted):
    """Player 0's decisions go to the pilot, player 1 passes; stops when the pilot's turn is over."""

    def __init__(self):
        super().__init__()
        self.pilot = LightswornPilot(seat=0, seed=11)
        self.attacks = 0
        self.activated = []
        self.attached = False

    def __call__(self, msg, duel):
        if not self.attached:
            self.attached = True
            self.pilot._hook(duel)
        if msg is not None and msg.payload[:1] == b"\x00" and msg.id != MSG_SELECT_IDLECMD or \
                (msg is not None and msg.id == MSG_SELECT_IDLECMD and msg.payload[0] == 0):
            r = self.pilot(msg, duel)
            if msg.id not in (MSG_SELECT_BATTLECMD, MSG_SELECT_IDLECMD):
                return r
            v = struct.unpack("<i", r[:4])[0]
            if msg.id == MSG_SELECT_BATTLECMD and v & 0xFFFF == BATTLE_ATTACK:
                self.attacks += 1
            if msg.id == MSG_SELECT_IDLECMD and v & 0xFFFF == IDLE_ACTIVATE:
                from engine.messages import parse_idlecmd
                self.activated.append(parse_idlecmd(msg.payload).activatable[v >> 16].code)
            return r
        return super().__call__(msg, duel)  # player 1: passive; its first Main Phase ends the test


def pilot_turn(cards, tmp_path):
    def add(code, p, loc, pos="POS_FACEUP_ATTACK", seq=0):
        return f"Debug.AddCard({code},{p},{p},{loc},{seq},{pos},true)"
    lines = [add(*c) for c in cards]
    lines += [add(ELF, p, "LOCATION_DECK", "POS_FACEDOWN") for p in (0, 1) for _ in range(20)]
    lua = "\n".join([f"Debug.ReloadFieldBegin({EDISON_FLAGS | DUEL_ATTACK_FIRST_TURN},0)",
                     "Debug.SetPlayerInfo(0,8000,0,0)", "Debug.SetPlayerInfo(1,8000,0,0)",
                     *lines, "Debug.ReloadFieldEnd()", ""])
    return run(lua, PilotVsPassive(), EdisonScriptProvider(), tmp_path)


ALLURE, JUDGMENT_DRAGON = 1475311, 57774843


def test_a_open_field_it_attacks(tmp_path):
    """Open field, two monsters. Allure of Darkness with no other DARK in hand would banish the hand: v1's
    copies fired it after every Battle Phase, which made "attack" look worse than "end turn"."""
    p = pilot_turn([(GAROTH, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 0),
                    (JAIN, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 1),
                    (ALLURE, 0, "LOCATION_HAND", "POS_FACEDOWN", 0), (EHREN, 0, "LOCATION_HAND", "POS_FACEDOWN", 0)],
                   tmp_path)
    assert p.attacks >= 2, f"two monsters, empty opposing field: expected attacks, got {p.attacks}"
    assert ALLURE not in p.activated, "Allure with no other DARK in hand throws the hand away"


def test_b_lumina_is_summoned_and_uses_her_effect(tmp_path):
    p = pilot_turn([(LUMINA, 0, "LOCATION_HAND", "POS_FACEDOWN", 0),
                    (EHREN, 0, "LOCATION_HAND", "POS_FACEDOWN", 0),
                    (GAROTH, 0, "LOCATION_GRAVE", "POS_FACEUP", 0)], tmp_path)
    assert LUMINA in p.activated, "Lumina in hand, a Lightsworn to discard and one to revive: summon and use her"


def test_c_four_monsters_against_one_face_down_it_attacks(tmp_path):
    p = pilot_turn([(WULF, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 0),
                    (GAROTH, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 1),
                    (JAIN, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 2),
                    (LYLA, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 3),
                    (SANGAN, 1, "LOCATION_MZONE", "POS_FACEDOWN_DEFENSE", 0),
                    (ALLURE, 0, "LOCATION_HAND", "POS_FACEDOWN", 0), (EHREN, 0, "LOCATION_HAND", "POS_FACEDOWN", 0)],
                   tmp_path)
    assert p.attacks >= 2, f"4 monsters vs 1 face-down: expected the face-down attacked, then damage; got {p.attacks}"
    assert ALLURE not in p.activated


def test_copies_keep_this_turns_constraints(tmp_path):
    """Copies used to reset the turn on start-up, forgetting which monsters had attacked: after both attacked,
    a copy let Judgment Dragon attack again, so wiping our own board with its effect looked winning."""
    p = pilot_turn([(JUDGMENT_DRAGON, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 0),
                    (GAROTH, 0, "LOCATION_MZONE", "POS_FACEUP_ATTACK", 1)], tmp_path)
    assert p.attacks == 2
    assert JUDGMENT_DRAGON not in p.activated, "nothing of theirs to destroy: the effect only costs our Garoth"
