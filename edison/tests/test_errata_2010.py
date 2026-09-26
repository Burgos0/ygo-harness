"""April 2010 text (edisonformat.net/rules/errata): pre-errata cards and edison/scripts overrides.

Each behavior test runs one fixed field (edison/tests/scenario.py) twice - with the 2010 script and with
the current official one - and asserts the one thing the texts disagree on.
"""
import csv
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.board import read_board
from engine.carddb import CardDB, ScriptProvider
from engine.constants import MSG_SELECT_CARD, MSG_SELECT_TRIBUTE, MSG_SELECT_UNSELECT_CARD
from engine.duel import Duel
from engine.messages import (IDLE_ACTIVATE, IDLE_SUMMON, IdleCmd, SelectCard, SelectChain,
                             parse_select_card, parse_select_tribute)
from engine.ocgapi import load
from edison.deck import load_ydk
from edison.provider import EdisonScriptProvider
from scenario import Scripted, Stop, field, run
from test_deck import EXTRA, MAIN, SIDE, ydk

OFFICIAL = ScriptProvider()


def edison():
    return EdisonScriptProvider()


def card(code, player, where, pos="POS_FACEUP_ATTACK", seq=0):
    return f"Debug.AddCard({code},{player},{player},{where},{seq},{pos})"


def pick(msg, want):
    """Answer a card selection with the first option whose code is in `want`."""
    sel = (parse_select_tribute if msg.id == MSG_SELECT_TRIBUTE else parse_select_card)(msg.payload)
    for i, c in enumerate(sel.codes):
        if c in want:
            return SelectCard.encode([i])
    return None


# ---------------------------------------------------------------- 1. pre-errata cards are what runs

PRE = [r for r in csv.DictReader(open(ROOT / "edison" / "errata_2010.csv")) if r["pre_errata_passcode"]]


class Recording(ScriptProvider):
    def __init__(self):
        super().__init__()
        self.requested: list[str] = []

    def read(self, name):
        self.requested.append(Path(name).name)
        return super().read(name)


@pytest.mark.parametrize("row", PRE, ids=[r["name"] for r in PRE])
def test_normal_passcode_runs_the_pre_errata_script(row, tmp_path):
    normal, pre = int(row["pool_passcode"]), int(row["pre_errata_passcode"])
    is_extra = CardDB().row(normal)[4] & (0x40 | 0x2000)
    main = MAIN if is_extra else MAIN[:-1] + [normal]
    extra = EXTRA[:-1] + [normal] if is_extra else EXTRA
    deck = load_ydk(ydk(tmp_path, main=main, extra=extra, side=SIDE))
    assert pre in deck.main + deck.extra and normal not in deck.main + deck.extra
    sp = Recording()
    with Duel((1, 2, 3, 4), lib=load(), carddb=CardDB(), scripts=sp) as d:
        d.load_deck(0, deck.main, deck.extra, shuffle_seed=1)
        d.load_deck(1, deck.main, deck.extra, shuffle_seed=2)
        d.start()
    assert f"c{pre}.lua" in sp.requested, f"{row['name']}: the (Pre-Errata) script was never loaded"
    assert f"c{normal}.lua" not in sp.requested, f"{row['name']}: the current script was loaded"


# ---------------------------------------------------------------- 2. Brain Control (Pre-Errata)

BRAIN_CONTROL, BRAIN_CONTROL_2010, STARDUST = 87910978, 511002995, 44508094


class Offered(Scripted):
    def __init__(self, code):
        super().__init__()
        self.code, self.offered = code, None

    def idle(self, cmd, duel):
        if cmd.player == 0 and self.offered is None:
            self.offered = any(c.code == self.code for c in cmd.activatable)
        return None


@pytest.mark.parametrize("code,expected", [(BRAIN_CONTROL_2010, True), (BRAIN_CONTROL, False)])
def test_brain_control_2010_can_take_a_synchro_monster(code, expected, tmp_path):
    """2010: "target 1 face-up monster your opponent controls" - any monster. Current: only one that can
    be Normal Summoned/Set, so Stardust Dragon (Synchro) is not a legal target."""
    f = field(card(code, 0, "LOCATION_HAND"), card(STARDUST, 1, "LOCATION_MZONE"))
    assert run(f, Offered(code), OFFICIAL, tmp_path).offered is expected


# ---------------------------------------------------------------- 3a. Soul Exchange

SOUL_EXCHANGE, SUMMONED_SKULL, MYSTICAL_ELF = 68005187, 70781052, 15025844


class SoulExchange(Scripted):
    """Activate Soul Exchange on the opponent's Elf, then Tribute Summon Skull; record the choices."""

    def __init__(self):
        super().__init__()
        self.step, self.tribute_choices = 0, None

    def idle(self, cmd, duel):
        if cmd.player != 0:
            return None
        if self.step == 0:
            self.step = 1
            i = next(i for i, c in enumerate(cmd.activatable) if c.code == SOUL_EXCHANGE)
            return IdleCmd.encode(IDLE_ACTIVATE, i)
        if self.step == 1:
            self.step = 2
            i = next(i for i, c in enumerate(cmd.summonable) if c.code == SUMMONED_SKULL)
            return IdleCmd.encode(IDLE_SUMMON, i)
        return None

    def other(self, msg, duel):
        # Controllers of the monsters offered as the Tribute. The core asks with MSG_SELECT_TRIBUTE when
        # the target is on its mandatory list (current), and with MSG_SELECT_UNSELECT_CARD when an
        # optional one-of Tribute is involved (2010) - layout per playerop.cpp: u8 player, u8 finishable,
        # u8 cancelable, u32 min, u32 max, u32 n, then n x (u32 code, u8 controller, u8 loc, u32 seq, u32 pos).
        if msg.id == MSG_SELECT_TRIBUTE:
            self.tribute_choices = sorted(p[0] for p in parse_select_tribute(msg.payload).places)
            raise Stop
        if msg.id == MSG_SELECT_UNSELECT_CARD:
            (n,) = struct.unpack_from("<I", msg.payload, 11)
            self.tribute_choices = sorted(msg.payload[15 + 14 * i + 4] for i in range(n))
            raise Stop
        return None


def test_soul_exchange_2010_tribute_is_optional(tmp_path):
    f = field(card(SOUL_EXCHANGE, 0, "LOCATION_HAND"), card(SUMMONED_SKULL, 0, "LOCATION_HAND"),
              card(MYSTICAL_ELF, 0, "LOCATION_MZONE"), card(MYSTICAL_ELF, 1, "LOCATION_MZONE"))
    assert run(f, SoulExchange(), edison(), tmp_path).tribute_choices == [0, 1], \
        "2010: either your own monster or the targeted one may be Tributed"
    assert run(f, SoulExchange(), OFFICIAL, tmp_path).tribute_choices == [1], \
        "current: the targeted monster must be the Tribute"


# ---------------------------------------------------------------- 3b. Machina Gearframe

GEARFRAME, CYBER_DRAGON = 42940404, 70095154


class Gearframe(Scripted):
    """Equip the first Gearframe to Cyber Dragon, then see whether the second may equip to it too."""

    def __init__(self):
        super().__init__()
        self.equipped, self.second_can_equip = False, None

    def idle(self, cmd, duel):
        if cmd.player != 0:
            return None
        frames = [i for i, c in enumerate(cmd.activatable) if c.code == GEARFRAME]
        if not self.equipped:
            self.equipped = True
            return IdleCmd.encode(IDLE_ACTIVATE, frames[0])
        # Cyber Dragon now carries one Gearframe; the other Gearframe's only Machine target is Cyber Dragon.
        self.second_can_equip = bool(frames)
        return None

    def other(self, msg, duel):
        if msg.id == MSG_SELECT_CARD:
            return pick(msg, {CYBER_DRAGON})
        return None


def test_gearframe_2010_one_union_per_monster(tmp_path):
    f = field(card(GEARFRAME, 0, "LOCATION_MZONE", seq=0), card(GEARFRAME, 0, "LOCATION_MZONE", seq=1),
              card(CYBER_DRAGON, 0, "LOCATION_MZONE", seq=2))
    assert run(f, Gearframe(), edison(), tmp_path).second_can_equip is False
    assert run(f, Gearframe(), OFFICIAL, tmp_path).second_can_equip is True


# ---------------------------------------------------------------- 3c. Elemental HERO Prisma

PRISMA, FLAME_WINGMAN, AVIAN = 89312388, 35809262, 21844576


class Prisma(Scripted):
    """Activate Prisma; at the first response window (before it resolves) look at the GY."""

    def __init__(self):
        super().__init__()
        self.activated, self.avian_in_gy_before, self.avian_in_gy_after = False, None, None

    def idle(self, cmd, duel):
        if cmd.player != 0:
            return None
        if not self.activated:
            self.activated = True
            i = next(i for i, c in enumerate(cmd.activatable) if c.code == PRISMA)
            return IdleCmd.encode(IDLE_ACTIVATE, i)
        self.avian_in_gy_after = any(c and c.code == AVIAN for c in read_board(duel, 0).grave)
        return None

    def chain(self, ch, duel):
        if self.activated and self.avian_in_gy_before is None:
            self.avian_in_gy_before = any(c and c.code == AVIAN for c in read_board(duel, 0).grave)
        return None


def test_prisma_2010_sends_at_resolution_not_as_cost(tmp_path):
    f = field(card(PRISMA, 0, "LOCATION_MZONE"), card(FLAME_WINGMAN, 0, "LOCATION_EXTRA", "POS_FACEDOWN"),
              card(AVIAN, 0, "LOCATION_DECK", "POS_FACEDOWN"))
    new = run(f, Prisma(), edison(), tmp_path)
    old = run(f, Prisma(), OFFICIAL, tmp_path)
    assert new.avian_in_gy_before is False and new.avian_in_gy_after is True, "2010: no cost, sent on resolution"
    assert old.avian_in_gy_before is True, "current: sent as the cost, before anyone can respond"


# ---------------------------------------------------------------- 3d. Quickdraw Synchron

QUICKDRAW = 20932152


class Quickdraw(Scripted):
    def __init__(self):
        super().__init__()
        self.menu = None

    def idle(self, cmd, duel):
        if cmd.player == 0 and self.menu is None:
            self.menu = ("activate" if any(c.code == QUICKDRAW for c in cmd.activatable) else
                         "spsummon" if any(c.code == QUICKDRAW for c in cmd.spsummonable) else None)
        return None


def test_quickdraw_2010_is_an_ignition_effect(tmp_path):
    f = field(card(QUICKDRAW, 0, "LOCATION_HAND"), card(MYSTICAL_ELF, 0, "LOCATION_HAND"))
    assert run(f, Quickdraw(), edison(), tmp_path).menu == "activate", "2010: an effect that starts a chain"
    assert run(f, Quickdraw(), OFFICIAL, tmp_path).menu == "spsummon", "current: a Special Summon procedure"


# ---------------------------------------------------------------- 3e. Mausoleum of the Emperor

MAUSOLEUM, SOLEMN = 80921533, 41420027


class Mausoleum(Scripted):
    def __init__(self):
        super().__init__()
        self.used, self.solemn_offered, self.skull_on_field = False, 0, None

    def idle(self, cmd, duel):
        if cmd.player != 0:
            return None
        if not self.used:
            self.used = True
            i = next(i for i, c in enumerate(cmd.activatable) if c.code == MAUSOLEUM)
            return IdleCmd.encode(IDLE_ACTIVATE, i)
        self.skull_on_field = any(c and c.code == SUMMONED_SKULL for c in read_board(duel, 0).monsters)
        return None

    def chain(self, ch, duel):
        for i, o in enumerate(ch.options):
            if o.code == SOLEMN:
                self.solemn_offered += 1
                return SelectChain.encode(i)
        return None


def test_mausoleum_2010_summon_cannot_be_negated(tmp_path):
    f = field(card(MAUSOLEUM, 0, "LOCATION_SZONE", "POS_FACEUP", seq=5), card(SUMMONED_SKULL, 0, "LOCATION_HAND"),
              card(SOLEMN, 1, "LOCATION_SZONE", "POS_FACEDOWN"))
    new = run(f, Mausoleum(), edison(), tmp_path)
    old = run(f, Mausoleum(), OFFICIAL, tmp_path)
    assert new.solemn_offered == 0 and new.skull_on_field, "2010: no window to negate the Summon"
    assert old.solemn_offered == 1 and not old.skull_on_field, "current: Solemn Judgment negates it"
