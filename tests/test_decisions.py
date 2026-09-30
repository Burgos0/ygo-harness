"""Decision tests: real positions from recorded games, and the answer the pilot must give there.

Each fixture in tests/fixtures/decisions/ is a duel's seeds, dealt decks and response log up to one or
more prompts (captured with scripts/capture_positions.py). The test replays the log to each prompt and
asks the pilot - the full response search, not a single score call - what it does.

match137_game2_turn14: Blackwing-DAD has Solemn Judgment set on Lightsworn's turn 14. Negating Chaos
Sorcerer and the Synchro Thought Ruler Archfiend is right; spending Solemn on Plaguespreader Zombie (400
ATK) is not. Before tuning round 1 (b087ef6) the pilot passed on all three.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.lookahead import LookaheadPilot
from agents.profiles import PROFILES
from edison.duel import EdisonDuel
from engine.carddb import CardDB
from engine.constants import MSG_SELECT_CHAIN
from engine.messages import parse_select_chain

FIXTURES = ROOT / "tests" / "fixtures" / "decisions"
DB = CardDB()


class _Reached(Exception):
    pass


def _replay_to(fx: dict, n: int):
    """Replay the first n responses; return (duel, pilot, prompt). The pilot observes the whole replay."""
    log = [bytes.fromhex(r) for r in fx["responses"][:n]]
    pilot = LookaheadPilot(PROFILES[fx["profile"]], seat=fx["seat"], seed=1)
    duel = EdisonDuel(tuple(fx["seed"]))
    for team, (main, extra) in enumerate(fx["dealt"]):
        duel.load_deck(team, main, extra)
    pilot.attach(duel)
    fed = [0]

    def feed(msg, d):
        if fed[0] == len(log):
            raise _Reached(msg)
        fed[0] += 1
        return log[fed[0] - 1]
    duel.start()
    try:
        duel.run(feed, max_steps=10 ** 6, retry_limit=10 ** 6)
    except _Reached as e:
        return duel, pilot, e.args[0]
    raise AssertionError("the log ended the duel before reaching the prompt")


def _cases():
    for path in sorted(FIXTURES.glob("*.json")):
        fx = json.loads(path.read_text())
        for w in fx["windows"]:
            yield pytest.param(fx, w, id=f"{path.stem}-{w['summon']}-{w['expect']}")


@pytest.mark.parametrize("fx,window", list(_cases()))
def test_pilot_decision(fx, window):
    duel, pilot, msg = _replay_to(fx, window["n"])
    try:
        assert msg.id == MSG_SELECT_CHAIN and msg.payload.hex() == window["payload"], \
            "the replay no longer reaches the recorded prompt (engine, scripts or deck data changed?)"
        ch = parse_select_chain(msg.payload)
        answer = struct.unpack("<i", pilot(msg, duel))[0]
        took = DB.name(ch.options[answer].code) if answer >= 0 else "pass"
        want = "Solemn Judgment" if window["expect"] == "negate" else "pass"
        assert took == want, f"on {window['summon']}'s summon the pilot chose {took!r}, expected {want!r}"
    finally:
        duel.close()
