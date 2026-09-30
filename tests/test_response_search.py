"""Response search: forks of the real duel must be scrubbed of what the pilot may not know."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.lookahead import INERT, EndOfTurn, Fork, LookaheadPilot
from agents.profiles import PROFILES
from agents.random_legal import RandomLegal
from edison.deck import load_ydk
from edison.duel import EdisonDuel
from engine.board import read_board
from engine.constants import MSG_SELECT_CHAIN

LS = load_ydk(ROOT / "edison" / "decks" / "lightsworn.ydk")
BW = load_ydk(ROOT / "edison" / "decks" / "blackwing_dad.ydk")


class Peek(Fork):
    """Stops right after the scrub and records what the fork then holds."""

    def __call__(self, msg, duel):
        was = self.applied
        r = super().__call__(msg, duel)
        if self.applied and not was:
            me, op = self.pilot.me, 1 - self.pilot.me
            b_me, b_op = read_board(duel, me), read_board(duel, op)
            self.seen = {"deck": [c.code for c in b_me.deck if c],
                         "op_hidden": [c.code for c in b_op.hand + b_op.deck if c]
                         + [c.code for c in b_op.monsters if c and not c.position & 0x5]}
            raise EndOfTurn
        return r


class Grab(LookaheadPilot):
    """The first opponent-turn chain window with options: fork it, and keep the real hidden state."""

    def __call__(self, msg, duel):
        if (msg is not None and msg.id == MSG_SELECT_CHAIN and msg.player == self.me
                and duel.turn_player != self.me and not hasattr(self, "fork")):
            me, op = self.me, 1 - self.me
            self.real = {"deck": [c.code for c in read_board(duel, me).deck if c],
                         "op_hidden": [c.code for c in read_board(duel, op).hand + read_board(duel, op).deck if c]}
            self.fork = Peek(self, duel, msg)
            self.fork.evaluate(b"\xff\xff\xff\xff")
            raise StopIteration
        return super().__call__(msg, duel)


def test_fork_reaches_the_prompt_and_scrubs_hidden_information():
    p = Grab(PROFILES["blackwing_dad"], seat=0, seed=5, respond_search=False)
    with EdisonDuel((3, 4, 5, 6)) as d:
        d.load_deck(0, BW.main, BW.extra, shuffle_seed=3)
        d.load_deck(1, LS.main, LS.extra, shuffle_seed=4)
        p.attach(d)
        d.start()
        try:
            d.run(p, max_steps=20000, policy1=RandomLegal(seed=5))
        except StopIteration:
            pass
    f = p.fork
    assert f.applied and not f.desync, "the replay must reach the very same prompt"
    assert set(f.seen["op_hidden"]) == {INERT}, "opponent's hand, Deck and face-down monsters are scrubbed"
    assert len(f.seen["op_hidden"]) >= len(p.real["op_hidden"]), "counts are kept"
    assert sorted(f.seen["deck"]) == sorted(p.real["deck"]), "our Deck keeps its contents"
    assert f.seen["deck"] != p.real["deck"], "but not its real order"


def test_generic_pilot_still_names_no_card():
    src = (ROOT / "agents" / "lookahead.py").read_text()
    names = set().union(*(p.engine | set(p.discard_first) for p in PROFILES.values()))
    assert not any(f'"{n}"' in src for n in names)
