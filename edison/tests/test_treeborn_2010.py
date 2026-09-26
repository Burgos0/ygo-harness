"""Treeborn Frog, April 2010 text (edison/scripts/c12538374.lua) vs the current once-per-turn text.

Scenario, built as a puzzle field so every card is placed exactly (turn 1, player 0):
  player 0: Treeborn Frog in the GY; Reload + Dark Magician in hand; 3 cards in the Deck; no Spells/Traps
Standby Phase: Frog's effect activates -> player 0 chains Reload (a Quick-Play Spell) -> when Frog's
effect resolves, player 0 controls a Spell (Reload stays on the field until the chain ends), so the
Summon fails and Frog stays in the GY. After the chain Reload is in the GY: no Spells/Traps again.
  2010 text: nothing limits the effect - it is offered again and this time Frog is Summoned.
  current text ("Once per turn"): its one use is spent - it is not offered again; Frog stays in the GY.
The Frog never leaves the GY between the two attempts. That matters: a soft once-per-turn resets when a
card changes location, so a scenario where Frog is Summoned, destroyed and revives again shows no
difference at all (checked: the current script revives twice in that case too).
Both player-0 choices are fixed (take Frog's effect, chain Reload once); zone/position picks go to a
seeded RandomLegal. The run stops at the first Main Phase decision, i.e. after the Standby Phase.
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.random_legal import RandomLegal
from engine.carddb import CardDB, ScriptProvider
from engine.constants import MSG_SELECT_CHAIN, MSG_SELECT_EFFECTYN, MSG_SELECT_IDLECMD, MSG_SELECT_YESNO
from engine.board import read_board
from engine.duel import Duel
from engine.messages import SelectChain, parse_select_chain
from engine.ocgapi import load
from engine.puzzle import Puzzle
from edison.provider import EdisonScriptProvider

FROG, RELOAD, DARK_MAGICIAN = 12538374, 22589918, 46986414

FIELD = f"""
Debug.ReloadFieldBegin(DUEL_ATTACK_FIRST_TURN,3)
Debug.SetPlayerInfo(0,8000,0,0)
Debug.SetPlayerInfo(1,8000,0,0)
Debug.AddCard({FROG},0,0,LOCATION_GRAVE,0,POS_FACEUP_ATTACK)
Debug.AddCard({RELOAD},0,0,LOCATION_HAND,0,POS_FACEDOWN)
Debug.AddCard({DARK_MAGICIAN},0,0,LOCATION_HAND,0,POS_FACEDOWN)
for i=1,3 do Debug.AddCard({DARK_MAGICIAN},0,0,LOCATION_DECK,0,POS_FACEDOWN) end
Debug.ReloadFieldEnd()
"""


class StandbyOver(Exception):
    pass


class Script:
    """Answers for both players by fixed rules and counts what happened."""

    def __init__(self):
        self.frog = self.reload = 0
        self.frog_on_chain = False  # Reload is chained only in the window right after Frog's activation
        self.other = RandomLegal(seed=0)  # zone/position picks: irrelevant here, seeded so reruns match

    def __call__(self, msg, duel):
        if msg is None:
            return struct.pack("<i", 0)
        if msg.id == MSG_SELECT_IDLECMD:
            raise StandbyOver
        if msg.id == MSG_SELECT_CHAIN:
            ch = parse_select_chain(msg.payload)
            if ch.player != 0:  # player 1 has nothing; its windows must not disturb player 0's plan
                return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)
            for i, o in enumerate(ch.options):
                if o.code == FROG:
                    self.frog += 1
                    self.frog_on_chain = True
                    return SelectChain.encode(i)
                if o.code == RELOAD and self.frog_on_chain and not self.reload:
                    self.reload += 1
                    self.frog_on_chain = False
                    return SelectChain.encode(i)
            self.frog_on_chain = False
            return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)
        if msg.id in (MSG_SELECT_EFFECTYN, MSG_SELECT_YESNO):
            if struct.unpack_from("<I", msg.payload, 1)[0] == FROG:
                self.frog += 1
                self.frog_on_chain = True
            return struct.pack("<i", 1)
        return self.other(msg, duel)


def standby(scripts, tmp_path) -> tuple[Script, bool]:
    """-> (what happened, whether Frog ended the Standby Phase on the field)."""
    path = tmp_path / "treeborn.lua"
    path.write_text(FIELD)
    policy = Script()
    duel = Duel.from_puzzle(Puzzle.load(path), lib=load(), carddb=CardDB(), scripts=scripts)
    with duel as d:
        d.start()
        try:
            d.run(policy, max_steps=500, policy1=policy)
        except StandbyOver:
            pass
        on_field = any(c and c.code == FROG for c in read_board(d, 0).monsters)
    return policy, on_field


def test_2010_text_can_try_again_in_the_same_standby_phase(tmp_path):
    s, on_field = standby(EdisonScriptProvider(), tmp_path)
    assert s.reload == 1, "Reload must be chained, or the first attempt was never made to fail"
    assert s.frog == 2 and on_field, f"2010 text: offered {s.frog}x, on field {on_field}; expected 2x, on field"


def test_current_text_is_once_per_turn(tmp_path):
    s, on_field = standby(ScriptProvider(), tmp_path)
    assert s.reload == 1
    assert s.frog == 1 and not on_field, f"current text: offered {s.frog}x, on field {on_field}; expected 1x, in GY"
