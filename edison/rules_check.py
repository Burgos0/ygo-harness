"""How the engine handles each Edison-vs-modern rule, measured, not assumed.

    python -m edison.rules_check        # prints one line per rule; used by edison/RULES_2010.md

Source: edisonformat.net's Rulings compendium (/rules/compendium/*). Each check builds a small fixed
field (edison/tests/scenario.py) and runs it twice:
  harness  exactly how our duels run today: Master Rule 5 (engine.duel default MASTER_RULE_5)
  flagged  the same, plus the core duel flag that implements the 2010 rule, where one exists
Nothing here changes how duels run; it only reports.
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "edison" / "tests"))

from engine.board import read_board
from engine.carddb import CardDB, ScriptProvider
from engine.constants import (MASTER_RULE_5, MSG_CHAINING, MSG_SELECT_BATTLECMD, MSG_SELECT_CARD,
                              MSG_SELECT_OPTION, MSG_SELECT_POSITION, MSG_SORT_CHAIN)
from engine.deck import Deck
from engine.duel import Duel
from engine.messages import (BATTLE_ATTACK, IDLE_ACTIVATE, IDLE_SUMMON, IDLE_TO_BP, IDLE_TO_EP, BattleCmd,
                             IdleCmd, SelectCard, SelectChain, parse_select_battlecmd, parse_select_card)
from engine.ocgapi import load
from scenario import Scripted, Stop, field, run

SP = ScriptProvider()
F = {  # core flags (ocgapi_constants.h)
    "DUEL_OCG_OBSOLETE_IGNITION": 0x100, "DUEL_1ST_TURN_DRAW": 0x200, "DUEL_1_FACEUP_FIELD": 0x400,
    "DUEL_TRIGGER_ONLY_IN_LOCATION": 0x20000, "DUEL_0_ATK_DESTROYED": 0x10000000,
    "DUEL_CAN_REPOS_IF_NON_SUMPLAYER": 0x80000000, "DUEL_TCG_SEGOC_NONPUBLIC": 0x100000000,
    "DUEL_TCG_SEGOC_FIRSTTRIGGER": 0x200000000, "DUEL_TCG_FAST_EFFECT_IGNITION": 0x400000000,
}
ATTACK_T1 = "DUEL_ATTACK_FIRST_TURN"


def tmp() -> Path:
    return Path(tempfile.mkdtemp())


def card(code, player, where, pos="POS_FACEUP_ATTACK", seq=0):
    return f"Debug.AddCard({code},{player},{player},{where},{seq},{pos})"


def chainings(stream) -> list[tuple[int, int]]:
    """(code, controller) of each MSG_CHAINING, in order."""
    return [(struct.unpack_from("<I", p, 0)[0], p[4]) for mid, p in stream if mid == MSG_CHAINING]


def pick_idle(cmd, kind_list, code, kind):
    for i, c in enumerate(kind_list):
        if c.code == code:
            return IdleCmd.encode(kind, i)
    return None


# ------------------------------------------------------------------ First Turn Draw

def first_turn_draw(extra_flags: int) -> int:
    """Cards in player 0's hand at their first Main Phase decision, in a normal deck duel."""
    deck = Deck.from_ydk(ROOT / "data" / "decks" / "sky_striker_pulp6.ydk")
    seen = {}

    class P(Scripted):
        def idle(self, cmd, duel):
            seen["hand"] = sum(1 for c in read_board(duel, 0).hand if c)
            return None

    with Duel((1, 2, 3, 4), lib=load(), carddb=CardDB(), scripts=SP, flags=MASTER_RULE_5 | extra_flags) as d:
        d.load_deck(0, deck.main, deck.extra, shuffle_seed=1)
        d.load_deck(1, deck.main, deck.extra, shuffle_seed=2)
        d.start()
        try:
            d.run(P(), max_steps=500, policy1=P())
        except Stop:
            pass
    return seen["hand"]


# ------------------------------------------------------------------ Single Field Spell

YAMI, SOGEN = 59197169, 86318356


def single_field(flags: str) -> bool:
    """Opponent controls face-up Yami; player 0 activates Sogen. -> is Yami still on the field?"""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.done, s.yami = False, None

        def idle(s, cmd, duel):
            if cmd.player == 0 and not s.done:
                s.done = True
                return pick_idle(cmd, cmd.activatable, SOGEN, IDLE_ACTIVATE)
            s.yami = any(c and c.code == YAMI for c in read_board(duel, 1).spells)
            return None

    f = field(card(YAMI, 1, "LOCATION_SZONE", "POS_FACEUP", seq=5), card(SOGEN, 0, "LOCATION_HAND"),
              rule=5, flags=flags)
    return run(f, P(), SP, tmp()).yami


# ------------------------------------------------------------------ Paying Life Points

BRAIN_CONTROL, VORSE = 87910978, 14898066


def pay_all_lp(flags: str) -> bool:
    """Player 0 has exactly 800 LP and Brain Control (cost 800). -> is it offered?"""
    class P(Scripted):
        offered = None

        def idle(s, cmd, duel):
            s.offered = any(c.code == BRAIN_CONTROL for c in cmd.activatable)
            return None

    f = field(card(BRAIN_CONTROL, 0, "LOCATION_HAND"), card(VORSE, 1, "LOCATION_MZONE"), rule=5, flags=flags)
    f = f.replace("Debug.SetPlayerInfo(0,8000,0,0)", "Debug.SetPlayerInfo(0,800,0,0)")
    return run(f, P(), SP, tmp()).offered


# ------------------------------------------------------------------ Zero ATK monsters

IDOL = 27125110  # Thousand-Eyes Idol, 0 ATK / 0 DEF


def zero_atk(flags: str) -> tuple[int, int]:
    """Both players' 0-ATK Idols in Attack Position; player 0 attacks. -> Idols left (p0, p1)."""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.phase, s.left = 0, None

        def idle(s, cmd, duel):
            if cmd.player == 0 and s.phase == 0:
                s.phase = 1
                return IdleCmd.encode(IDLE_TO_BP)
            s.left = tuple(sum(1 for c in read_board(duel, p).monsters if c) for p in (0, 1))
            return None

        def other(s, msg, duel):
            if msg.id == MSG_SELECT_BATTLECMD:
                cmd = parse_select_battlecmd(msg.payload)
                attacks = [a for a in cmd.actions() if a[0] == BATTLE_ATTACK]
                if s.phase == 1 and attacks:
                    s.phase = 2
                    return BattleCmd.encode(attacks[0][0], attacks[0][1])
                s.left = tuple(sum(1 for c in read_board(duel, p).monsters if c) for p in (0, 1))
                raise Stop
            return None

    f = field(card(IDOL, 0, "LOCATION_MZONE"), card(IDOL, 1, "LOCATION_MZONE"), rule=5, flags=flags)
    return run(f, P(), SP, tmp()).left


# ------------------------------------------------------------------ Ignition Priority

EXILED, TRAP_HOLE = 74131780, 4206964


def ignition_priority(flags: str) -> str:
    """Player 0 Normal Summons Exiled Force (ignition effect); player 1 has Trap Hole set.
    -> who gets to act first after the Summon: 'p0 ignition' (priority) or 'p1 Trap Hole'."""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.summoned, s.first = False, None

        def idle(s, cmd, duel):
            if cmd.player == 0 and not s.summoned:
                s.summoned = True
                return pick_idle(cmd, cmd.summonable, EXILED, IDLE_SUMMON)
            if s.first is None and cmd.player == 0 and any(c.code == EXILED for c in cmd.activatable):
                s.first = "p0 ignition"
            return None

        def chain(s, ch, duel):
            # With the TCG flag the turn player's ignition effects are offered as fast effects in the
            # chain window right after the Summon, before the opponent's window.
            if s.summoned and s.first is None:
                if ch.player == 0 and any(o.code == EXILED for o in ch.options):
                    s.first = "p0 ignition"
                elif ch.player == 1 and any(o.code == TRAP_HOLE for o in ch.options):
                    s.first = "p1 Trap Hole"
            return None  # decline everything

    f = field(card(EXILED, 0, "LOCATION_HAND"), card(TRAP_HOLE, 1, "LOCATION_SZONE", "POS_FACEDOWN"),
              card(VORSE, 1, "LOCATION_MZONE"), rule=5, flags=flags)
    return run(f, P(), SP, tmp()).first


# ------------------------------------------------------------------ SEGOC / Early Trigger

CAIUS, SANGAN, ELF = 9748752, 26202165, 15025844


def early_trigger(flags: str) -> tuple[bool, list[str]]:
    """Sangan is Tributed for Caius: both mandatory triggers. 2010: Sangan (sent first) must be CL1.
    -> (was the player asked to order the chain, chain order by name)."""
    names = {CAIUS: "Caius", SANGAN: "Sangan"}

    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.summoned, s.sorted_offered = False, False

        def idle(s, cmd, duel):
            if cmd.player == 0 and not s.summoned:
                s.summoned = True
                return pick_idle(cmd, cmd.summonable, CAIUS, IDLE_SUMMON)
            return None

        def other(s, msg, duel):
            if msg.id == MSG_SORT_CHAIN:
                s.sorted_offered = True
            if msg.id == MSG_SELECT_CARD:  # Caius: banish the opponent's Vorse; Sangan: add the Elf
                sel = parse_select_card(msg.payload)
                for want in (VORSE, ELF):
                    if want in sel.codes:
                        return SelectCard.encode([sel.codes.index(want)])
            return None

    f = field(card(CAIUS, 0, "LOCATION_HAND"), card(SANGAN, 0, "LOCATION_MZONE"),
              card(ELF, 0, "LOCATION_DECK", "POS_FACEDOWN"), card(VORSE, 1, "LOCATION_MZONE"), rule=5, flags=flags)
    p = run(f, P(), SP, tmp())
    return p.sorted_offered, [names[c] for c, _ in chainings(p.stream) if c in names]


# ------------------------------------------------------------------ Phase Triggers

LYLA = 22624373


def phase_triggers(flags: str) -> int:
    """Two Lyla (mandatory "During your End Phase" mill) on player 0's field; go to the End Phase.
    -> longest chain built in that End Phase (2010: they do not chain to each other, so 1)."""
    from engine.constants import MSG_CHAIN_END

    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.ended = False

        def idle(s, cmd, duel):
            if cmd.player == 0 and not s.ended:
                s.ended = True
                return IdleCmd.encode(IDLE_TO_EP)
            return None

        def other(s, msg, duel):
            if msg.id == MSG_SELECT_BATTLECMD:
                from engine.messages import BATTLE_TO_EP
                return BattleCmd.encode(BATTLE_TO_EP)
            return None

    cards = [card(LYLA, 0, "LOCATION_MZONE", seq=0), card(LYLA, 0, "LOCATION_MZONE", seq=1)]
    cards += [card(ELF, 0, "LOCATION_DECK", "POS_FACEDOWN")] * 8 + [card(ELF, 1, "LOCATION_DECK", "POS_FACEDOWN")] * 3
    p = run(field(*cards, rule=5, flags=flags), P(), SP, tmp())
    longest = cur = 0
    for mid, pay in p.stream:
        if mid == MSG_CHAINING and struct.unpack_from("<I", pay, 0)[0] == LYLA:
            cur += 1
            longest = max(longest, cur)
        elif mid == MSG_CHAIN_END:
            cur = 0
    return longest


# ------------------------------------------------------------------ Changing Control

CALL = 97077563


def changing_control(flags: str) -> bool:
    """Player 1 revives Vorse Raider with Call of the Haunted during player 0's Standby Phase; player 0
    takes it with Brain Control. -> may player 0 change its battle position this turn?"""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.called = s.stolen = False
            s.can_repos = None

        def chain(s, ch, duel):
            if ch.player == 1 and not s.called:
                for i, o in enumerate(ch.options):
                    if o.code == CALL:
                        s.called = True
                        return SelectChain.encode(i)
            return None

        def idle(s, cmd, duel):
            if cmd.player != 0:
                return None
            if not s.stolen:
                s.stolen = True
                return pick_idle(cmd, cmd.activatable, BRAIN_CONTROL, IDLE_ACTIVATE)
            s.can_repos = any(c.code == VORSE for c in cmd.repositionable)
            return None

    f = field(card(BRAIN_CONTROL, 0, "LOCATION_HAND"), card(CALL, 1, "LOCATION_SZONE", "POS_FACEDOWN"),
              card(VORSE, 1, "LOCATION_GRAVE"), rule=5, flags=flags)
    p = run(f, P(), SP, tmp())
    return p.can_repos if p.called and p.stolen else f"scenario failed (called={p.called}, stolen={p.stolen})"


# ------------------------------------------------------------------ Trigger Locations

ENEMY_CONTROLLER, DD_CROW = 98045062, 24508238
MR5_FLAGS = 0x800 | 0x2000 | 0x4000 | 0x8000 | 0x20000  # DUEL_MODE_MR5


def trigger_location(flags: str, rule: int = 5) -> bool:
    """Sangan is Tributed for Enemy Controller; player 1 chains D.D. Crow to banish it from the GY.
    -> does Sangan's effect still activate after the chain? (2010: yes, location does not matter)"""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.used = s.crow = False

        def idle(s, cmd, duel):
            if cmd.player == 0 and not s.used:
                s.used = True
                return pick_idle(cmd, cmd.activatable, ENEMY_CONTROLLER, IDLE_ACTIVATE)
            return None

        def chain(s, ch, duel):
            if ch.player == 1 and not s.crow:
                for i, o in enumerate(ch.options):
                    if o.code == DD_CROW:
                        s.crow = True
                        return SelectChain.encode(i)
            return None

        def other(s, msg, duel):
            if msg.id == MSG_SELECT_OPTION:
                return struct.pack("<i", 1)  # Enemy Controller: Tribute 1 monster, take control
            if msg.id == MSG_SELECT_CARD:
                sel = parse_select_card(msg.payload)
                for want in (SANGAN, VORSE, ELF):
                    if want in sel.codes:
                        return SelectCard.encode([sel.codes.index(want)])
            return None

    f = field(card(ENEMY_CONTROLLER, 0, "LOCATION_HAND"), card(SANGAN, 0, "LOCATION_MZONE"),
              card(ELF, 0, "LOCATION_DECK", "POS_FACEDOWN"), card(VORSE, 1, "LOCATION_MZONE"),
              card(DD_CROW, 1, "LOCATION_HAND"), rule=rule, flags=flags)
    p = run(f, P(), SP, tmp())
    if not (p.used and p.crow):
        return f"scenario failed (used={p.used}, crow={p.crow})"
    return any(c == SANGAN for c, _ in chainings(p.stream))


# ------------------------------------------------------------------ End of turn discard

PETEN = 52624755


def end_of_turn_discard(flags: str) -> bool:
    """Player 0 ends the turn with 7 cards and discards Peten the Dark Clown for hand size.
    -> is Peten's optional GY effect offered? (2010: it cannot activate)"""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.ended, s.offered = False, False

        def idle(s, cmd, duel):
            if cmd.player == 0 and not s.ended:
                s.ended = True
                return IdleCmd.encode(IDLE_TO_EP)
            return None

        def chain(s, ch, duel):
            if any(o.code == PETEN for o in ch.options):
                s.offered = True
            return None

        def yesno(s, msg, duel):
            if struct.unpack_from("<I", msg.payload, 1)[0] == PETEN:
                s.offered = True
            return None

        def other(s, msg, duel):
            if msg.id == MSG_SELECT_BATTLECMD:
                from engine.messages import BATTLE_TO_EP
                return BattleCmd.encode(BATTLE_TO_EP)
            if msg.id == MSG_SELECT_CARD:
                sel = parse_select_card(msg.payload)
                if PETEN in sel.codes:
                    return SelectCard.encode([sel.codes.index(PETEN)])
            return None

    cards = [card(PETEN, 0, "LOCATION_HAND")] + [card(ELF, 0, "LOCATION_HAND")] * 6
    cards += [card(PETEN, 0, "LOCATION_DECK", "POS_FACEDOWN")]
    return run(field(*cards, rule=5, flags=flags), P(), SP, tmp()).offered


# ------------------------------------------------------------------ Union: Summoned in Attack Position

GEARFRAME, CYBER_DRAGON = 42940404, 70095154


def union_summon_position(scripts) -> str:
    """Equip Gearframe to Cyber Dragon on turn 1, unequip and Special Summon it on turn 3.
    -> 'asked' if a battle position was offered, else the position it arrived in."""
    class P(Scripted):
        def __init__(s):
            super().__init__()
            s.step, s.result = 0, None

        def idle(s, cmd, duel):
            if cmd.player == 1:
                return IdleCmd.encode(IDLE_TO_EP)
            if s.step == 0:
                s.step = 1
                return pick_idle(cmd, cmd.activatable, GEARFRAME, IDLE_ACTIVATE)
            if s.step == 1:
                s.step = 2
                return IdleCmd.encode(IDLE_TO_EP)
            if s.step == 2:
                s.step = 3
                return pick_idle(cmd, cmd.activatable, GEARFRAME, IDLE_ACTIVATE)
            if s.result is None:
                g = [c for c in read_board(duel, 0).monsters if c and c.code == GEARFRAME]
                s.result = f"summoned {'ATK' if g and g[0].position & 0x1 else 'DEF'}" if g else "not summoned"
            return None

        def other(s, msg, duel):
            if msg.id == MSG_SELECT_BATTLECMD:
                from engine.messages import BATTLE_TO_EP
                return BattleCmd.encode(BATTLE_TO_EP)
            if msg.id == MSG_SELECT_POSITION and s.step == 3:
                s.result = "asked"
            if msg.id == MSG_SELECT_CARD:
                sel = parse_select_card(msg.payload)
                if CYBER_DRAGON in sel.codes:
                    return SelectCard.encode([sel.codes.index(CYBER_DRAGON)])
            return None

    f = field(card(GEARFRAME, 0, "LOCATION_MZONE", seq=0), card(CYBER_DRAGON, 0, "LOCATION_MZONE", seq=1), rule=5, flags="0")
    return run(f, P(), scripts, tmp()).result


CHECKS = []


def main() -> int:
    print("First Turn Draw  hand at first Main Phase:", "harness", first_turn_draw(0),
          "| +1ST_TURN_DRAW", first_turn_draw(F["DUEL_1ST_TURN_DRAW"]))
    print("Single Field Spell  opponent's Yami survives our Sogen:", "harness", single_field("0"),
          "| +1_FACEUP_FIELD", single_field(str(F["DUEL_1_FACEUP_FIELD"])))
    print("Paying LP  Brain Control offered at exactly 800 LP:", "harness", pay_all_lp("0"))
    print("Zero ATK  Idols left (p0,p1) after 0 vs 0 battle:", "harness", zero_atk(ATTACK_T1),
          "| +0_ATK_DESTROYED", zero_atk(f"{ATTACK_T1}+{F['DUEL_0_ATK_DESTROYED']}"))
    for fl in ("DUEL_TCG_FAST_EFFECT_IGNITION", "DUEL_OCG_OBSOLETE_IGNITION"):
        print(f"Ignition Priority  first to act after the Summon: harness {ignition_priority('0')!r} | +{fl[5:]} "
              f"{ignition_priority(str(F[fl]))!r}")
    print("Early Trigger  (order prompt, chain order):", "harness", early_trigger("0"),
          "| +SEGOC_FIRSTTRIGGER", early_trigger(str(F["DUEL_TCG_SEGOC_FIRSTTRIGGER"])))
    print("Phase Triggers  longest Lyla chain in the End Phase:", "harness", phase_triggers("0"))
    print("Changing Control  may reposition a stolen, opponent-summoned monster:", "harness",
          changing_control("0"), "| +CAN_REPOS_IF_NON_SUMPLAYER", changing_control(str(F["DUEL_CAN_REPOS_IF_NON_SUMPLAYER"])))
    print("Trigger Locations  banished Sangan still activates:", "harness", trigger_location("0"),
          "| MR5 without TRIGGER_ONLY_IN_LOCATION", trigger_location(str(MR5_FLAGS & ~F["DUEL_TRIGGER_ONLY_IN_LOCATION"]), rule=0))
    print("End-of-turn discard  Peten's effect offered after a hand-size discard:", "harness", end_of_turn_discard("0"))
    from edison.provider import EdisonScriptProvider
    print("Union position  Gearframe unequipped and Summoned:", "official script", union_summon_position(SP),
          "| edison override", union_summon_position(EdisonScriptProvider()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
