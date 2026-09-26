"""Tiny fixed-field duels for rules tests: a puzzle script places the cards, a Scripted policy answers.

    s = run(FIELD, MyScript(), scripts, tmp_path)

FIELD is Lua between Debug.ReloadFieldBegin/End (see field()). Scripted answers every decision for
both players: subclasses override idle/chain/yesno/other hooks; anything a hook leaves as None goes to
a seeded RandomLegal, so reruns are identical. Raise Stop from a hook to end the duel there - the
duel is still open inside the hook, so read the board before raising.
"""
from __future__ import annotations

import struct
from pathlib import Path

from agents.random_legal import RandomLegal
from engine.carddb import CardDB
from engine.constants import MSG_SELECT_CHAIN, MSG_SELECT_EFFECTYN, MSG_SELECT_IDLECMD, MSG_SELECT_YESNO
from engine.duel import Duel
from engine.messages import SelectChain, parse_idlecmd, parse_select_chain
from engine.ocgapi import load
from engine.puzzle import Puzzle


class Stop(Exception):
    pass


def field(*cards: str, lp: int = 8000, rule: int = 3, flags: str = "DUEL_ATTACK_FIRST_TURN") -> str:
    """cards: Debug.AddCard(...) lines. `rule` is ReloadFieldBegin's Master Rule: the core ORs in
    DUEL_MODE_MR<rule> (libdebug.cpp), so rule=5, flags="0" is exactly the harness's MASTER_RULE_5 duel.
    No DUEL_SIMPLE_AI: that flag makes the core play player 1."""
    return "\n".join([
        f"Debug.ReloadFieldBegin({flags},{rule})",
        f"Debug.SetPlayerInfo(0,{lp},0,0)", f"Debug.SetPlayerInfo(1,{lp},0,0)",
        *cards, "Debug.ReloadFieldEnd()", ""])


class Scripted:
    def __init__(self):
        self.fallback = RandomLegal(seed=0)
        self.log: list[tuple] = []
        #: every engine message seen, in order: (id, payload). Chain order, draws, etc. are read from here.
        self.stream: list[tuple[int, bytes]] = []

    # hooks - return bytes to answer, None for the default
    def idle(self, cmd, duel):
        return None

    def chain(self, ch, duel):
        return None

    def yesno(self, msg, duel):
        return None

    def other(self, msg, duel):
        return None

    def __call__(self, msg, duel):
        if msg is None:
            return struct.pack("<i", 0)
        if msg.id == MSG_SELECT_IDLECMD:
            cmd = parse_idlecmd(msg.payload)
            self.log.append(("idle", cmd))
            r = self.idle(cmd, duel)
            if r is None:
                raise Stop  # default: the first free Main Phase decision ends the scenario
            return r
        if msg.id == MSG_SELECT_CHAIN:
            ch = parse_select_chain(msg.payload)
            self.log.append(("chain", ch.player, [o.code for o in ch.options]))
            r = self.chain(ch, duel)
            if r is None:
                return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)
            return r
        if msg.id in (MSG_SELECT_EFFECTYN, MSG_SELECT_YESNO):
            r = self.yesno(msg, duel)
            return struct.pack("<i", 1) if r is None else r
        r = self.other(msg, duel)
        return self.fallback(msg, duel) if r is None else r


def run(field_lua: str, policy: Scripted, scripts, tmp_path: Path, max_steps: int = 2000) -> Scripted:
    path = tmp_path / "field.lua"
    path.write_text(field_lua)
    duel = Duel.from_puzzle(Puzzle.load(path), lib=load(), carddb=CardDB(), scripts=scripts)
    with duel as d:
        read = d._messages  # record every engine message, not only the decisions the policy is asked

        def recording():
            batch = read()
            policy.stream.extend((m.id, m.payload) for m in batch)
            return batch
        d._messages = recording
        d.start()
        try:
            d.run(policy, max_steps=max_steps, policy1=policy)
        except Stop:
            pass
    return policy
