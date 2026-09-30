"""Generic deck pilot: one-ply lookahead to the end of our own turn, plus a scoring function.

    from agents.lookahead import LookaheadPilot
    from agents.profiles import LIGHTSWORN
    d.run(LookaheadPilot(LIGHTSWORN, seat=0, seed=7), policy1=RandomLegal(seed=7))

Everything deck-specific - score weights, which cards are the engine, what to discard first, what to
hold, a deck's own score terms - is a Profile (agents/profiles.py). This file knows no card names.

Response search (respond_search=True): every prompt we answer on the opponent's turn, and every chain
window / yes-no during any Battle Phase, is searched the same way - pass vs each legal response, and
then each legal target (single-card choices). A puzzle copy cannot hold a pending attack or chain, so
these copies are *forks*: the real duel replayed from its seeds and response log up to this prompt,
then scrubbed of what we may not know before anything is played (see Fork). Every such prompt is
logged in `self.windows` (available options, taken or passed, turn, phase, triggering event).

Searched decisions: our Main Phase menu (summon / set / activate / change phase) and our Battle
Phase menu (attack / activate / change phase). For each candidate the pilot builds a *copy* of the
position, plays the candidate, lets fixed rules finish the turn, and scores the result. Everything
else (chain windows, yes/no, positions, card choices) uses fixed rules.

No cheating - a copy is rebuilt from what this player may know, never from the real duel's state:
  * our Deck: its contents are known, its order is not -> shuffled with the pilot's own RNG
  * the opponent's hand: count only; not in the copy (the opponent never acts in a copy)
  * the opponent's face-down cards: identity hidden -> face-down monsters become a placeholder
    (a vanilla 800/2000), face-down Spells/Traps are left out and only counted
  * the opponent's Deck: count only (filler cards)
Known v0 simplifications (a copy starts fresh at our turn's Main Phase 1): what we already did this
turn is carried as constraints (Normal Summon used, monster effects used, monsters that attacked,
Battle Phase over); equips, counters and temporary ATK changes are not reconstructed; Standby
Phase triggers may fire again in the copy; the opponent is passive in every copy.
"""
from __future__ import annotations

import math
import random
import re
import struct
import time
from dataclasses import dataclass, field
from typing import Callable
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from agents.random_legal import RandomLegal
from engine.board import query_field, read_board
from engine.carddb import CardDB
from engine.constants import (LOCATION_DECK, LOCATION_HAND, LOCATION_MZONE, LOCATION_SZONE, MSG_ATTACK,
                              MSG_CHAINING, MSG_FLIPSUMMONING, MSG_NEW_PHASE, MSG_NEW_TURN,
                              MSG_SELECT_BATTLECMD, MSG_SELECT_CARD, MSG_SELECT_CHAIN,
                              MSG_SELECT_EFFECTYN, MSG_SELECT_IDLECMD, MSG_SELECT_POSITION,
                              MSG_SELECT_YESNO, MSG_SPSUMMONING, MSG_SUMMONING, MSG_WIN, PHASE_END,
                              MSG_BECOME_TARGET, MSG_CHAIN_END, MSG_CONFIRM_CARDS,
                              MSG_SELECT_UNSELECT_CARD, PHASE_MAIN2, PHASE_NAMES, TYPE_FUSION, TYPE_LINK,
                              TYPE_MONSTER, TYPE_NORMAL, TYPE_QUICKPLAY, TYPE_SYNCHRO, TYPE_TRAP, TYPE_TUNER,
                              TYPE_XYZ)
from engine.duel import Duel
from engine.messages import (BATTLE_ACTIVATE, BATTLE_ATTACK, BATTLE_TO_EP, BATTLE_TO_M2, IDLE_ACTIVATE,
                             IDLE_MSET, IDLE_SPSUMMON, IDLE_SSET, IDLE_SUMMON, IDLE_TO_BP, IDLE_TO_EP,
                             BattleCmd, IdleCmd, SelectCard, SelectChain, SelectUnselect, parse_idlecmd,
                             parse_select_battlecmd, parse_select_card, parse_select_chain)

#: A face-down monster we cannot see is treated as the format's typical small monster: DEF 500 is the
#: median DEF of the 46,580 level 1-4 main-deck monster copies in the TopDeck Edison lists (quartiles
#: 200 / 500 / 1200, mean 765). Worst-case (2000) made the pilot never attack face-downs and deck out.
TYPICAL_FACEDOWN_DEF = 500
PLACEHOLDER = 59053232     # Turu-Purun, vanilla 450/500: stands in for an unknown face-down monster
FILLER = 15025844          # opponent's unknown Deck cards
#: In a fork, the opponent's hidden cards become this card. It must be an *effect* monster - the core
#: will not replace effects with a Normal monster's (card::replace_effect returns early), so a vanilla
#: filler would keep the hidden card's own effects. Dark Grepher's only effects are a Special Summon
#: procedure and an ignition effect, which a passive opponent never uses.
INERT = 14536035
BATTLE_PHASES = 0x08 | 0x10 | 0x20 | 0x40 | 0x80
EVENTS = {MSG_ATTACK: "attack", MSG_CHAINING: "chain", MSG_SUMMONING: "summon", MSG_SPSUMMONING: "spsummon",
          MSG_FLIPSUMMONING: "flipsummon"}


@dataclass(frozen=True)
class Weights:
    """Score terms. Card advantage is the unit: 100 = one card."""
    card: float = 100.0              # per card of advantage (hand + field + set, ours minus theirs)
    gy_resource: float = 50.0        # per GY card with an effect usable from the GY, both sides
    hold: float = 40.0               # per unused set card / quick-play / trap in hand, both sides (theirs:
                                     # set cards only) - what spending one must beat on top of the card
    key_card: float = 60.0           # per profile key card in our hand, while unused
    hold_behind_atk: float = 3000.0  # our holding value shrinks linearly to 0 as we fall this far behind on
                                     # board (face-up ATK; a face-down monster counts TYPICAL_FACEDOWN_DEF)
    threat_atk: int = 2000           # a monster the opponent Summoned this turn with at least this ATK, and
    threat_hold: float = 0.0         # more than our best face-up monster, multiplies our holding value by this
    op_board_atk: float = 1 / 40     # per point of the opponent's face-up ATK (subtracted): so removing a
                                     # strong monster 1-for-1 is a gain and a weak one is not
    lethal_threat: float = 250.0     # the opponent's face-up ATK already reaches our LP
    low_lp: float = 0.0              # per 1000 LP below low_lp_line - superseded by lp_curve, kept for v1
    low_lp_line: int = 2000
    my_lp: float = 0.03              # per LP of ours, when lp_curve is off (v1)
    # Our LP as a nonlinear resource: worth lp_value * (1 - exp(-t / lp_tau)), t = LP / the opponent's
    # visible damage per turn (their face-up ATK, at least lp_floor_damage). Paying LP far from lethal
    # costs little; near lethal it costs a lot.
    lp_curve: bool = True
    lp_value: float = 300.0
    lp_tau: float = 1.0
    lp_floor_damage: int = 1000
    # Hidden cards: each unknown card in the opponent's hand is worth this on top of `card` (what it
    # might be - a hand trap, a key card - the same as our own holding value), so removing or shuffling
    # one away is not a neutral 1-for-1. Seeing their hand is worth `reveal`.
    hidden_hand: float = 40.0
    reveal: float = 20.0
    # Threat of an opposing monster, in ATK points on top of its ATK (scored at op_board_atk):
    threat_extra: float = 800.0      # Summoned from the Extra Deck (Synchro, Fusion, Xyz, Link)
    threat_field_effect: float = 600.0   # has an effect that works on the field (script: an MZONE range)
    threat_boss: float = 400.0       # Main Deck monster of level >= boss_level
    boss_level: int = 7
    op_lp: float = 0.06              # per LP of theirs (subtracted): 1000 LP = 60 ~ a 1600 direct attack
    board_atk: float = 1 / 40        # per point of face-up ATK: 1000 = 25
    per_monster: float = 15.0        # per monster we control, up to monster_cap
    monster_cap: int = 3
    overcommit: float = 10.0         # per monster beyond monster_cap (mass removal)
    set_risk_monster: float = 12.0   # per opposing set card, per extra monster we commit
    set_risk_attack: float = 6.0     # per opposing set card, per attack we make
    synchro_ready: float = 20.0      # a tuner + non-tuners that add up to a Synchro level in our Extra
    urgency_deck: int = 30           # LP terms scale up (to 4x) as our Deck drops below this; 0 = never
    low_deck: int = 10               # below this many Deck cards ...
    low_deck_penalty: float = 5.0    # ... lose this much per missing card


@dataclass(frozen=True)
class Profile:
    name: str
    deck: str = ""                           # .ydk the profile is written for, relative to the repo root
    weights: Weights = Weights()
    engine: frozenset = frozenset()          # card names: activated first by the rules, Summoned first,
                                             # kept first when the candidate list is cut
    discard_first: tuple = ()                # card names to pay hand costs with before the lowest ATK
    search_archetype: str | None = None      # choosing a card of ours: this archetype is worth +500 ATK
    hold: frozenset = frozenset()            # passcodes never activated by the pilot (e.g. D.D. Crow)
    attack_position_atk: int = 1600          # Summon in Attack Position at this ATK or more
    key_cards: frozenset = frozenset()       # card names worth holding in hand (Weights.key_card each)
    progress: Callable | None = None         # progress(mine, theirs, db, ctx) -> score for win-condition setup
                                             # that shows no immediate board change (a slow deck's turns);
                                             # ctx has my_lp, op_lp
    always_consider: frozenset = frozenset() # card names never cut from the Main Phase candidate list (unlike
                                             # `engine`, not auto-activated inside copies)
    hold_factor: tuple = ()                  # (card name, multiplier) pairs on that card's holding value


class EndOfTurn(Exception):
    pass


# ------------------------------------------------------------------ what we know about the turn

@dataclass
class Turn:
    number: int = 0
    player: int = 0
    phase: int = 0
    normal_summoned: bool = False
    monster_effects_used: set = field(default_factory=set)   # codes whose on-field effect we used
    attacked: set = field(default_factory=set)               # zone sequences that attacked

    def observe(self, mid: int, payload: bytes) -> None:
        if mid == MSG_NEW_TURN:
            self.number += 1
            self.player = payload[0]
            self.phase = 0
            self.normal_summoned = False
            self.monster_effects_used = set()
            self.attacked = set()
        elif mid == MSG_NEW_PHASE:
            self.phase = struct.unpack_from("<H", payload, 0)[0]

    @property
    def battle_over(self) -> bool:
        return self.phase in (PHASE_MAIN2, PHASE_END)


# ------------------------------------------------------------------ fixed rules

class Rules:
    """Cheap decisions: all of them inside copies, and the non-searched ones in the real duel."""

    def __init__(self, me: int, db: CardDB, rng: random.Random, profile: Profile):
        self.me, self.db, self.rng, self.profile = me, db, rng, profile
        self.fallback = RandomLegal(seed=rng.randrange(1 << 30))
        self.attack_pending = False  # the next card choice is an attack target
        self.doomed: set = set()     # (controller, location, sequence) targeted by the current chain

    def name(self, code: int) -> str:
        return self.db.name(code) or ""

    def idle(self, cmd: IdleCmd, turn: Turn, allow_bp: bool) -> bytes:
        for i, c in enumerate(cmd.activatable):          # the engine first
            if self.name(c.code) in self.profile.engine and not self._used(c, turn):
                return IdleCmd.encode(IDLE_ACTIVATE, i)
        if not turn.normal_summoned and cmd.summonable:  # an engine card first, else the biggest
            i = max(range(len(cmd.summonable)), key=lambda k: (self.name(cmd.summonable[k].code) in self.profile.engine,
                                                                self._atk(cmd.summonable[k].code)))
            return IdleCmd.encode(IDLE_SUMMON, i)
        # No other activations here. These rules finish a turn inside a lookahead copy; firing "anything
        # activatable" there used Judgment Dragon's wipe, Brionac's discard, Gorz... on our own board after
        # every Battle Phase, so "attack" always scored below "end turn". Other plays are the search's job.
        if cmd.to_bp and allow_bp:
            return IdleCmd.encode(IDLE_TO_BP)
        return IdleCmd.encode(IDLE_TO_EP)

    def battle(self, cmd: BattleCmd, turn: Turn, duel) -> bytes:
        opp = read_board(duel, 1 - self.me).monsters
        weakest = min((self._def_value(c) for c in opp if c), default=None)
        for i, c in enumerate(cmd.attackable):
            if c.sequence in turn.attacked:
                continue
            if weakest is None or self._atk(c.code, duel, c) > weakest:
                self.attack_pending = True
                return BattleCmd.encode(BATTLE_ATTACK, i)
        return BattleCmd.encode(BATTLE_TO_M2 if cmd.to_m2 else BATTLE_TO_EP)

    def chain(self, ch, my_turn: bool) -> bytes:
        if ch.player == self.me and not my_turn:
            for i, o in enumerate(ch.options):   # defend on the opponent's turn: traps, Necro Gardna...
                if o.code not in self.profile.hold:
                    return SelectChain.encode(i)
        return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)

    def select_card(self, msg, duel) -> bytes | None:
        sel = parse_select_card(msg.payload)
        if sel.max < 1 or not sel.codes:
            return None
        is_target = (self.attack_pending and sel.min == 1 and sel.max == 1 and sel.places
                     and all(con != self.me and loc == LOCATION_MZONE for con, loc, _ in sel.places))
        self.attack_pending = False
        if is_target:  # attack target: the weakest thing to run into
            opp = {(c_seq): c for c_seq, c in enumerate(read_board(duel, 1 - self.me).monsters) if c}
            def target_cost(i):
                info = opp.get(sel.places[i][2]) if sel.places else None
                return self._def_value(info) if info else 0
            return SelectCard.encode([min(range(len(sel.codes)), key=target_cost)])
        mine = [i for i in range(len(sel.codes)) if not sel.places or sel.places[i][0] == self.me]
        if mine and len(mine) == len(sel.codes) and all(sel.places[i][1] == LOCATION_HAND for i in mine):
            # A discard/cost from our hand: the profile's discard_first cards (Wulf Special Summons itself
            # when discarded), else the lowest-ATK card - never our best one.
            first = self.profile.discard_first
            order = sorted(mine, key=lambda i: (first.index(self.name(sel.codes[i])) if self.name(sel.codes[i])
                                                 in first else len(first), self._atk(sel.codes[i])))
            return SelectCard.encode(sorted(order[:max(1, sel.min)]))
        # Prefer the opponent's strongest card, else our best monster to revive / archetype card to search.
        def value(i):
            con = sel.places[i][0] if sel.places else self.me
            atk = self._atk(sel.codes[i])
            return (1, atk) if con != self.me else (0, atk + (500 if self._archetype(sel.codes[i]) else 0))
        order = sorted(range(len(sel.codes)), key=value, reverse=True)
        return SelectCard.encode(sorted(order[:max(1, sel.min)]))

    def respond(self, msg, duel, turn: Turn) -> bytes:
        if msg.id != MSG_SELECT_CARD:
            self.attack_pending = False  # an attack that needed no target choice
        if msg.id == MSG_SELECT_CHAIN:
            return self.chain(parse_select_chain(msg.payload), turn.player == self.me)
        if msg.id in (MSG_SELECT_EFFECTYN, MSG_SELECT_YESNO):
            return struct.pack("<i", 1)
        if msg.id == MSG_SELECT_POSITION:
            code, mask = struct.unpack_from("<I", msg.payload, 1)[0], msg.payload[5]
            want = 0x1 if self._atk(code) >= self.profile.attack_position_atk else 0x4
            for p in (want, 0x1, 0x4, 0x8, 0x2):
                if mask & p:
                    return struct.pack("<i", p)
        if msg.id == MSG_SELECT_CARD:
            r = self.select_card(msg, duel)
            if r is not None:
                return r
        if msg.id == MSG_SELECT_UNSELECT_CARD:
            r = self.select_unselect(msg)
            if r is not None:
                return r
        return self.fallback(msg, duel)

    def select_unselect(self, msg) -> bytes | None:
        """A cost paid with our own monsters (a Tribute, say) while one of them is already targeted by the
        opponent's chain: pay with the doomed one - it is lost either way. Otherwise None (the fallback)."""
        opts = parse_unselect_options(msg.payload)
        doomed = [i for i, (_, con, loc, seq) in enumerate(opts) if (con, loc, seq) in self.doomed]
        if doomed and all(con == self.me and loc == LOCATION_MZONE for _, con, loc, _ in opts):
            return SelectUnselect.encode(doomed[0])
        return None

    # helpers
    def _used(self, c, turn: Turn) -> bool:
        return c.location == LOCATION_MZONE and c.code in turn.monster_effects_used

    def _atk(self, code: int, duel=None, ref=None) -> int:
        row = self.db.row(code)
        return row[5] if row and row[4] & TYPE_MONSTER else 0

    def _def_value(self, info) -> int:
        """What an attacker must beat: ATK in Attack Position, DEF in face-up Defense, a typical DEF if unknown."""
        if info.position & 0x1:
            return info.attack
        if info.position & 0x4:
            return info.defense
        return TYPICAL_FACEDOWN_DEF

    @lru_cache(maxsize=None)
    def _archetype(self, code: int) -> bool:
        a = self.profile.search_archetype
        return bool(a) and a in self.db.archetypes(code)


# ------------------------------------------------------------------ scoring

class GraveResources:
    """Whether a card does something *from* the GY: its script registers an effect with a GY range.

    Read from the card's own script, so no card list: Necro Gardna, Plaguespreader Zombie, Glow-Up Bulb
    qualify; Sangan (fires on the way to the GY) does not.
    """
    GY_RANGE = re.compile(rb"SetRange\([^)]*LOCATION_GRAVE")
    FIELD_RANGE = re.compile(rb"SetRange\([^)]*LOCATION_MZONE")

    def __init__(self, scripts):
        self.scripts, self.cache, self.field_cache = scripts, {}, {}

    def _body(self, code: int) -> bytes:
        read = getattr(self.scripts, "source", self.scripts.read)   # source text, not compiled bytecode
        return read(f"c{code}.lua") or b""

    def __call__(self, code: int) -> bool:
        if code not in self.cache:
            self.cache[code] = bool(self.GY_RANGE.search(self._body(code)))
        return self.cache[code]

    def field_effect(self, code: int) -> bool:
        """Has an effect that works while it is on the field (ignition, quick or continuous, MZONE range)."""
        if code not in self.field_cache:
            self.field_cache[code] = bool(self.FIELD_RANGE.search(self._body(code)))
        return self.field_cache[code]


STATUS_SUMMONED_THIS_TURN = 0x800 | 0x40000000     # STATUS_SUMMON_TURN | STATUS_SPSUMMON_TURN
EXTRA_DECK_TYPES = TYPE_SYNCHRO | TYPE_FUSION | TYPE_XYZ | TYPE_LINK


def parse_unselect_options(payload: bytes) -> list[tuple[int, int, int, int]]:
    """MSG_SELECT_UNSELECT_CARD's selectable cards: (code, controller, location, sequence) each (playerop.cpp:
    u8 player, u8 finishable, u8 cancelable, u32 min, u32 max, u32 n, n x (u32 code + 10-byte loc_info))."""
    (n,) = struct.unpack_from("<I", payload, 11)
    out = []
    for i in range(n):
        off = 15 + 14 * i
        code, con, loc, seq = struct.unpack_from("<IBBI", payload, off)
        out.append((code, con, loc, seq))
    return out


def track_targets(m, doomed: set) -> None:
    """Keep `doomed` = cards targeted by the chain being built (MSG_BECOME_TARGET), until it resolves."""
    if m.id == MSG_BECOME_TARGET:
        (n,) = struct.unpack_from("<I", m.payload, 0)
        for i in range(n):
            con, loc, seq = struct.unpack_from("<BBI", m.payload, 4 + 10 * i)
            doomed.add((con, loc, seq))
    elif m.id == MSG_CHAIN_END:
        doomed.clear()


def reveals_hand(m, player: int) -> bool:
    """MSG_CONFIRM_CARDS showing at least one card from `player`'s hand."""
    if m.id != MSG_CONFIRM_CARDS or len(m.payload) < 5:
        return False
    (n,) = struct.unpack_from("<I", m.payload, 1)
    return any(m.payload[5 + 10 * i + 4] == player and m.payload[5 + 10 * i + 5] == LOCATION_HAND
               for i in range(n) if 5 + 10 * i + 10 <= len(m.payload))


def threat(c, w: Weights, gy) -> float:
    """An opposing face-up monster's threat in ATK points: its ATK, plus what it is beyond a body - an
    Extra Deck boss, an effect that works on the field, a high-level Main Deck boss."""
    t = c.attack
    if c.type & EXTRA_DECK_TYPES:
        t += w.threat_extra
    elif c.level >= w.boss_level:
        t += w.threat_boss
    if getattr(gy, "field_effect", None) and gy.field_effect(c.code):
        t += w.threat_field_effect
    return t


def hold_scale(mine, theirs, w: Weights) -> float:
    """How much our unused cards are worth holding, 0..1. Full when even or ahead on board; shrinking to 0
    as we fall behind by w.hold_behind_atk; times w.threat_hold while facing a monster the opponent Summoned
    this turn that is big (>= w.threat_atk) and bigger than anything of ours. Holding is for later, and
    behind on board or under a new threat there may be no later."""
    def board(b):
        return sum(c.attack if c.position & 0x5 else TYPICAL_FACEDOWN_DEF for c in b.monsters if c)
    scale = min(1.0, max(0.0, 1.0 + (board(mine) - board(theirs)) / w.hold_behind_atk)) if w.hold_behind_atk else 1.0
    best = max((c.attack for c in mine.monsters if c and c.position & 0x5), default=0)
    if any(c and c.position & 0x5 and c.status & STATUS_SUMMONED_THIS_TURN and c.attack >= w.threat_atk
           and c.attack > best for c in theirs.monsters):
        scale *= w.threat_hold
    return scale


def card_advantage(mine, theirs, gy, hidden_opp_hand: int = 0, hidden_opp_set: int = 0) -> float:
    """Cards: hand + field for both sides, plus half a card per usable GY resource. Ours minus theirs."""
    def side(b, hidden):
        cards = (sum(1 for c in b.hand if c) + sum(1 for c in b.monsters if c)
                 + sum(1 for c in b.spells if c) + hidden)
        return cards + 0.5 * sum(1 for c in b.grave if c and gy(c.code))
    return side(mine, 0) - side(theirs, hidden_opp_hand + hidden_opp_set)


def score(duel, me: int, db: CardDB, profile: Profile, hidden_opp_hand: int, hidden_opp_set: int,
          extra_levels: tuple, attacks: int = 0, gy=lambda code: False, revealed: bool = False) -> float:
    w = profile.weights
    fi = query_field(duel)
    mine, theirs = read_board(duel, me), read_board(duel, 1 - me)
    my_lp, op_lp = fi.lp[me], fi.lp[1 - me]
    if op_lp <= 0 and my_lp > 0:
        return 1e6
    if my_lp <= 0:
        return -1e6
    my_mons = [c for c in mine.monsters if c]
    # Card advantage, heaviest. GY resources count for both sides (both GYs are public).
    s = w.card * card_advantage(mine, theirs, lambda c: False, hidden_opp_hand, hidden_opp_set)
    s += w.gy_resource * (sum(1 for c in mine.grave if c and gy(c.code))
                          - sum(1 for c in theirs.grave if c and gy(c.code)))
    # Holding value: an unused set card, quick-play or trap in hand is worth more than its card count, so
    # spending one has to gain more than it (a 2-for-1, a stronger card, a stopped lethal) - not fire on
    # sight. The opponent's set cards carry the same value as a threat, which is what removing them gains.
    def is_quick(code):
        t = (db.row(code) or (0,) * 5)[4]
        return bool(t & TYPE_TRAP or t & TYPE_QUICKPLAY)
    factor = dict(profile.hold_factor)
    f = lambda c: factor.get(db.name(c.code), 1.0)
    held = (sum(f(c) for c in mine.spells if c and not c.position & 0x5)
            + sum(f(c) for c in mine.hand if c and is_quick(c.code)))
    op_set = hidden_opp_set + sum(1 for c in theirs.spells if c and not c.position & 0x5)
    scale = hold_scale(mine, theirs, w)
    s += w.hold * (scale * held - op_set)
    s += scale * w.key_card * sum(1 for c in mine.hand if c and db.name(c.code) in profile.key_cards)
    # Unknown cards in their hand are worth more than a card count; seeing them is worth something too.
    s -= w.hidden_hand * (hidden_opp_hand + sum(1 for c in theirs.hand if c))
    if revealed:
        s += w.reveal
    deck = mine.deck_count or sum(1 for c in mine.deck if c)
    # LP terms grow up to 4x as our Deck runs out (urgency_deck=30: from 30 cards down) - a deck that mills
    # itself must close the game before it decks out, so damage and attacking matter more late.
    urgency = 1.0 + max(0, w.urgency_deck - deck) / (w.urgency_deck / 3.0) if w.urgency_deck else 1.0
    their_atk = sum(c.attack for c in theirs.monsters if c and c.position & 0x5)
    if w.lp_curve:   # LP measured in turns of the opponent's visible damage: cheap far from lethal
        turns = my_lp / max(w.lp_floor_damage, their_atk)
        my_lp_value = w.lp_value * (1.0 - math.exp(-turns / w.lp_tau))
    else:
        my_lp_value = w.my_lp * my_lp
    s += urgency * (my_lp_value - w.op_lp * op_lp)
    face_up = [c for c in my_mons if c.position & 0x5]
    s += sum(c.attack for c in face_up) * w.board_atk + w.per_monster * min(len(my_mons), w.monster_cap)
    s -= w.overcommit * max(0, len(my_mons) - w.monster_cap)   # don't overcommit into mass removal
    # Their board, threat-weighted: removing or negating a boss is worth more than its ATK alone.
    s -= sum(threat(c, w, gy) for c in theirs.monsters if c and c.position & 0x5) * w.op_board_atk
    # Lethal / near-lethal: their visible attackers already reach our LP, or our LP is low.
    if their_atk >= my_lp:
        s -= w.lethal_threat
    s -= w.low_lp * max(0, w.low_lp_line - my_lp) / 1000.0
    # Risk of committing into set Spells/Traps (Mirror Force, Torrential, Bottomless...): each face-down
    # card the opponent controls threatens every extra monster we put out, and every attack we make.
    s -= op_set * (w.set_risk_monster * max(0, len(my_mons) - 1) + w.set_risk_attack * attacks)
    tuners = [c.level for c in face_up if c.type & TYPE_TUNER]
    others = [c.level for c in face_up if not c.type & TYPE_TUNER]
    if any(t + o in extra_levels or t + o + o2 in extra_levels
           for t in tuners for i, o in enumerate(others) for o2 in [0] + others[i + 1:]):
        s += w.synchro_ready                               # a Synchro play is on the board
    if deck < w.low_deck:
        s -= w.low_deck_penalty * (w.low_deck - deck)
    if profile.progress:                                   # win-condition setup (slow decks)
        s += profile.progress(mine, theirs, db, SimpleNamespace(my_lp=my_lp, op_lp=op_lp))
    return s


# ------------------------------------------------------------------ the pilot

class LookaheadPilot:
    def __init__(self, profile: Profile, seat: int, seed: int = 0, max_candidates: int = 8, lib=None,
                 carddb=None, scripts=None, flags: int | None = None, respond_search: bool = True):
        from edison.duel import EDISON_FLAGS
        from edison.provider import EdisonScriptProvider
        self.me, self.profile = seat, profile
        self.rng = random.Random(seed)
        self.db = carddb or CardDB()
        self.lib, self.scripts = lib, scripts or EdisonScriptProvider()
        self.flags = EDISON_FLAGS if flags is None else flags
        self.max_candidates = max_candidates
        self.rules = Rules(seat, self.db, self.rng, profile)
        self.turn = Turn()
        self._hooked = None
        self.searches = self.copies = 0
        self._can_bp = False
        self.plan = None   # the last searched Main/Battle Phase action: its snapshot, key and card picks
        self.respond_search = respond_search
        self.responding = False   # we just took a searched response: its target choices are searched too
        self.windows: list[dict] = []   # every response prompt: options, taken/passed, timing
        self.forks = self.fork_failures = 0
        self.actions: list[dict] = []   # our Main Phase activations: turn, code, location
        self.t_copies = self.t_forks = 0.0   # wall time in lookahead copies / response-search forks
        self.gy = GraveResources(self.scripts)
        self.ca_log: dict[int, float] = {}   # turn number -> card advantage at its start (our view)
        self.event = "phase"

    def attach(self, duel) -> None:
        """Call before duel.start() so turn 1 is observed too (lazy hooking may miss it)."""
        self._hook(duel)

    # -- message tracking
    def _hook(self, duel) -> None:
        if self._hooked is duel:
            return
        self._hooked = duel
        for m in getattr(duel, "last_batch", []) or []:
            self.turn.observe(m.id, m.payload)
        read = duel._messages

        def observed():
            batch = read()
            for m in batch:
                self.turn.observe(m.id, m.payload)
                if m.id == MSG_NEW_TURN:   # card advantage at the start of each turn (public + own info)
                    try:
                        self.ca_log[self.turn.number] = card_advantage(
                            read_board(duel, self.me), read_board(duel, 1 - self.me), self.gy)
                    except Exception:
                        pass
                # What a response window answers: the last attack / summon / chain link, until the turn
                # player next gets a free menu or the phase changes. Tracked here, not from the duel's
                # since_last_decision - the turn player's own prompt (it has priority) clears that first.
                if m.id in EVENTS:
                    self.event = EVENTS[m.id]
                elif m.id in (MSG_NEW_PHASE, MSG_NEW_TURN, MSG_SELECT_IDLECMD, MSG_SELECT_BATTLECMD):
                    self.event = "phase"
                track_targets(m, self.rules.doomed)
            return batch
        duel._messages = observed

    # -- entry point
    def __call__(self, msg, duel):
        self._hook(duel)
        if msg is None:
            return struct.pack("<i", 0)
        if msg.id == MSG_SELECT_IDLECMD:
            cmd = parse_idlecmd(msg.payload)
            if cmd.player == self.me:
                self._can_bp = cmd.to_bp  # the engine knows whether we may still battle this turn
                self._in_battle = False
                return self._remember(self._search("idle", cmd, duel), cmd, None)
        if msg.id == MSG_SELECT_BATTLECMD:
            cmd = parse_select_battlecmd(msg.payload)
            if cmd.player == self.me:
                self._in_battle, self._can_bp = True, False
                return self._remember(self._search("battle", cmd, duel), None, cmd)
        self._in_battle = False
        if msg.id in (MSG_SELECT_CHAIN, MSG_SELECT_EFFECTYN, MSG_SELECT_YESNO, MSG_SELECT_CARD) \
                and msg.player == self.me:
            r = self._response(msg, duel)
            if r is not None:
                return r
        if msg.id == MSG_SELECT_CARD and self.plan and self.turn.player == self.me:
            return self._choose_card(msg, duel)
        return self.rules.respond(msg, duel, self.turn)

    # -- response prompts (opponent's turn, any Battle Phase)
    def _response(self, msg, duel) -> bytes | None:
        """Search a response prompt; None leaves it to the usual path. Logs every chain window."""
        opp_turn = self.turn.player != self.me
        battle = bool((duel.phase or 0) & BATTLE_PHASES)
        if msg.id != MSG_SELECT_CARD:
            self.responding = False
        if msg.id != MSG_SELECT_CHAIN and not self.respond_search:
            return None
        if msg.id == MSG_SELECT_CARD:
            if not (opp_turn or self.responding) or self.rules.attack_pending:
                return None
            sel = parse_select_card(msg.payload)
            if not (sel.min == sel.max == 1 and 2 <= len(sel.codes) <= 12):
                return None
            cands = [(SelectCard.encode([i]), ("card", c, *(sel.places[i][:3] if sel.places else ())))
                     for i, c in enumerate(sel.codes)]
        elif msg.id == MSG_SELECT_CHAIN:
            ch = parse_select_chain(msg.payload)
            if not ch.options:
                return None
            cands, seen = [], set()
            for i, o in enumerate(ch.options):
                key = ("activate", o.code, o.location, o.sequence, o.description)
                if o.code in self.profile.hold or key in seen:
                    continue
                seen.add(key)
                cands.append((SelectChain.encode(i), key))
            if ch.can_decline():
                cands.append((SelectChain.decline(), ("pass",)))
            if not (opp_turn or battle) or not self.respond_search or len(cands) < 2:
                r = self.rules.chain(ch, not opp_turn)       # the fixed rule, as before response search
                self._log_window(msg, duel, ch, r, searched=False)
                return r
        else:
            if not (opp_turn or battle):
                return None
            cands = [(struct.pack("<i", 1), ("yes",)), (struct.pack("<i", 0), ("no",))]
        self.searches += 1
        best, best_score = None, float("-inf")
        for response, key in cands:
            sc = Fork(self, duel, msg).evaluate(response)
            self.fork_failures += sc == float("-inf")
            if sc > best_score:
                best, best_score = response, sc
        if best is None:   # every fork failed: the fixed rule
            best = (self.rules.chain(parse_select_chain(msg.payload), not opp_turn) if msg.id == MSG_SELECT_CHAIN
                    else self.rules.respond(msg, duel, self.turn))
        r = best
        if msg.id == MSG_SELECT_CHAIN:
            self._log_window(msg, duel, parse_select_chain(msg.payload), r, searched=True)
            self.responding = struct.unpack("<i", r)[0] >= 0
        return r

    def _log_window(self, msg, duel, ch, r: bytes, searched: bool) -> None:
        i = struct.unpack("<i", r)[0]
        event = self.event
        types = [(self.db.row(o.code) or (0,) * 5)[4] for o in ch.options]
        self.windows.append({
            "turn": self.turn.number, "own_turn": self.turn.player == self.me,
            "phase": PHASE_NAMES.get(duel.phase, str(duel.phase)), "event": event, "forced": ch.forced,
            "options": [o.code for o in ch.options], "trap_options": sum(1 for t in types if t & TYPE_TRAP),
            "taken": ch.options[i].code if 0 <= i < len(ch.options) else None,
            "taken_trap": bool(0 <= i < len(ch.options) and types[i] & TYPE_TRAP), "searched": searched,
            "mine_targeted": sum(1 for con, loc, _ in self.rules.doomed if con == self.me and loc == LOCATION_MZONE)})

    def _choose_card(self, msg, duel) -> bytes:
        """A card choice during our turn (search, discard, revive target...): lookahead over the options.
        The copy restarts from the snapshot of the Main/Battle Phase decision that led here, replays that
        action and our earlier choices in it, then plays this option."""
        sel = parse_select_card(msg.payload)
        options = sorted({(c, *sel.places[i][:2]) for i, c in enumerate(sel.codes)}) if sel.places else []
        plan = self.plan
        if self.rules.attack_pending or not (sel.min == sel.max == 1 and 2 <= len(options) <= 12):
            r = self.rules.respond(msg, duel, self.turn)
        else:
            self.searches += 1
            best, best_score = None, float("-inf")
            for opt in options:
                sc = self._evaluate(plan["snap"], plan["kind"], plan["key"], picks=plan["picks"], choice=opt)
                if sc > best_score:
                    best, best_score = opt, sc
            if best is None:  # every copy failed: fall back to the fixed rule
                r = self.rules.respond(msg, duel, self.turn)
            else:
                r = SelectCard.encode([next(i for i, c in enumerate(sel.codes) if (c, *sel.places[i][:2]) == best)])
        _, n = struct.unpack_from("<iI", r, 0)
        idx = struct.unpack_from(f"<{n}I", r, 8)
        plan["picks"].append([(sel.codes[i], *sel.places[i][:2]) for i in idx if i < len(sel.codes)])
        return r

    def _remember(self, response: bytes, idle, battle) -> bytes:
        kind, index = struct.unpack("<i", response)[0] & 0xFFFF, struct.unpack("<i", response)[0] >> 16
        if idle is not None:
            if kind in (IDLE_SUMMON, IDLE_MSET):
                self.turn.normal_summoned = True
            if kind == IDLE_ACTIVATE and idle.activatable[index].location == LOCATION_MZONE:
                self.turn.monster_effects_used.add(idle.activatable[index].code)
            if kind == IDLE_ACTIVATE:
                c = idle.activatable[index]
                self.actions.append({"turn": self.turn.number, "code": c.code, "location": c.location})
        if battle is not None:
            k, i = struct.unpack("<i", response)[0] & 0xFFFF, struct.unpack("<i", response)[0] >> 16
            if k == BATTLE_ATTACK:
                self.turn.attacked.add(battle.attackable[i].sequence)
                self.rules.attack_pending = True
        return response

    # -- search
    def _candidates(self, kind: str, cmd) -> list[tuple]:
        """(response bytes, key) - key identifies the same action in a copy."""
        out = []
        if kind == "idle":
            for t, lst in ((IDLE_ACTIVATE, cmd.activatable), (IDLE_SUMMON, cmd.summonable),
                           (IDLE_SPSUMMON, cmd.spsummonable), (IDLE_MSET, cmd.msetable),
                           (IDLE_SSET, cmd.ssetable)):
                seen = set()
                for i, c in enumerate(lst):
                    key = (t, c.code, c.location, c.sequence if c.location != LOCATION_HAND else 0, c.description)
                    if key in seen or c.code in self.profile.hold:
                        continue
                    if t in (IDLE_SUMMON, IDLE_MSET) and self.turn.normal_summoned:
                        continue
                    seen.add(key)
                    out.append((IdleCmd.encode(t, i), key))
            # engine cards first when the candidate list must be cut
            keep = self.profile.engine | self.profile.always_consider
            out.sort(key=lambda x: x[1][1] and self.db.name(x[1][1]) not in keep)
            out = out[: self.max_candidates]
            if cmd.to_bp:
                out.append((IdleCmd.encode(IDLE_TO_BP), ("to_bp",)))
            out.append((IdleCmd.encode(IDLE_TO_EP), ("to_ep",)))
        else:
            for i, c in enumerate(cmd.attackable):
                if c.sequence not in self.turn.attacked:
                    out.append((BattleCmd.encode(BATTLE_ATTACK, i), ("attack", c.code, c.sequence)))
            for i, c in enumerate(cmd.activatable):
                out.append((BattleCmd.encode(BATTLE_ACTIVATE, i), ("bact", c.code, c.location, c.description)))
            out.append((BattleCmd.encode(BATTLE_TO_M2 if cmd.to_m2 else BATTLE_TO_EP), ("leave",)))
        return out

    def _search(self, kind: str, cmd, duel) -> bytes:
        cands = self._candidates(kind, cmd)
        if len(cands) == 1:
            self.plan = None
            return cands[0][0]
        self.searches += 1
        snap = self._snapshot(duel)
        (best, best_key), best_score = cands[-1], float("-inf")
        for response, key in cands:
            s = self._evaluate(snap, kind, key)
            if s > best_score:
                best, best_key, best_score = response, key, s
        self.plan = {"snap": snap, "kind": kind, "key": best_key, "picks": []}
        return best

    # -- copies
    def _snapshot(self, duel) -> dict:
        me, op = self.me, 1 - self.me
        fi = query_field(duel)
        b_me, b_op = read_board(duel, me), read_board(duel, op)
        deck = [c.code for c in b_me.deck if c]
        self.rng.shuffle(deck)                                   # order unknown to us
        lines = []

        def add(code, player, loc, seq, pos, proc=False):
            lines.append(f"Debug.AddCard({code},{player},{player},{loc},{seq},{pos},{'true' if proc else 'false'})")

        for seq, c in enumerate(b_me.monsters):
            if c:
                add(c.code, 0, LOCATION_MZONE, seq, c.position, True)
        for seq, c in enumerate(b_me.spells):
            if c and not c.equip_target:                        # equips are not reconstructed (v0)
                add(c.code, 0, LOCATION_SZONE, seq, c.position)
        for c in b_me.hand:
            if c:
                add(c.code, 0, LOCATION_HAND, 0, 0x8)
        for loc, cards in ((0x10, b_me.grave), (0x20, b_me.banished), (0x40, b_me.extra)):
            for c in cards:
                if c:
                    add(c.code, 0, loc, 0, 0x5 if loc != 0x40 else 0x8)
        for code in deck:
            add(code, 0, 0x01, 0, 0x8)
        hidden_set = 0
        for seq, c in enumerate(b_op.monsters):
            if c:
                if c.position & 0x5:                               # face-up: public
                    add(c.code, 1, LOCATION_MZONE, seq, c.position, True)
                else:                                              # face-down: identity hidden
                    add(PLACEHOLDER, 1, LOCATION_MZONE, seq, 0x8, True)
        for seq, c in enumerate(b_op.spells):
            if c:
                if c.position & 0x5 and not c.equip_target:
                    add(c.code, 1, LOCATION_SZONE, seq, c.position)
                else:
                    hidden_set += 1
        for loc, cards in ((0x10, b_op.grave), (0x20, b_op.banished)):
            for c in cards:
                if c:
                    add(c.code, 1, loc, 0, 0x5)
        for _ in range(min(20, b_op.deck_count or 20)):
            add(FILLER, 1, 0x01, 0, 0x8)
        extra_levels = tuple(sorted({self.db.row(c.code)[7] & 0xFF for c in b_me.extra
                                     if c and self.db.row(c.code) and self.db.row(c.code)[4] & TYPE_SYNCHRO}))
        from engine.constants import DUEL_ATTACK_FIRST_TURN
        can_attack = self._can_bp or getattr(self, "_in_battle", False)
        flags = self.flags | (DUEL_ATTACK_FIRST_TURN if can_attack else 0)
        lua = "\n".join([f"Debug.ReloadFieldBegin({flags},0)",
                         f"Debug.SetPlayerInfo(0,{max(1, fi.lp[me])},0,0)",
                         f"Debug.SetPlayerInfo(1,{max(1, fi.lp[op])},0,0)",
                         *lines, "Debug.ReloadFieldEnd()", ""])
        return {"lua": lua, "hidden_hand": sum(1 for c in b_op.hand if c), "hidden_set": hidden_set,
                "extra_levels": extra_levels, "can_attack": can_attack,
                "turn": self.turn}

    def _evaluate(self, snap: dict, kind: str, key: tuple, picks=(), choice=None) -> float:
        t = time.perf_counter()
        try:
            return self._evaluate_copy(snap, kind, key, picks, choice)
        finally:
            self.t_copies += time.perf_counter() - t

    def _evaluate_copy(self, snap: dict, kind: str, key: tuple, picks=(), choice=None) -> float:
        self.copies += 1
        # Duel.load_puzzle needs only the source and a chunk name - no temp file, no Puzzle.load parse.
        field = SimpleNamespace(path=Path(f"lookahead_copy_{id(self)}.lua"), source=snap["lua"].encode())
        copy = Duel.from_puzzle(field, lib=self.lib, carddb=self.db, scripts=self.scripts)
        roll = _Rollout(self, snap, kind, key, picks, choice)
        with copy as d:
            read = d._messages

            def watched():
                batch = read()
                for m in batch:
                    if m.id == MSG_NEW_TURN and roll.turn.number == 0:
                        # The copy's own start. Do NOT reset the turn: the constraints carried in from the
                        # real duel (Normal Summon used, attackers used, effects used) must survive it -
                        # resetting here let every copy Summon and attack a second time.
                        roll.turn.number, roll.turn.player = 1, m.payload[0]
                        continue
                    roll.turn.observe(m.id, m.payload)
                    roll.revealed = roll.revealed or reveals_hand(m, 1)
                    if m.id == MSG_WIN or (m.id == MSG_NEW_TURN and roll.turn.number > 1):
                        roll.done = True
                return batch
            d._messages = watched
            d.start()
            try:
                d.run(roll, max_steps=800, policy1=roll)
            except EndOfTurn:
                pass
            except Exception:
                return float("-inf")
            if not roll.applied or roll.missed_choice:
                return float("-inf")
            return score(d, 0, self.db, self.profile, snap["hidden_hand"], snap["hidden_set"], snap["extra_levels"],
                         attacks=roll.attacks, gy=self.gy, revealed=roll.revealed)


class _Rollout:
    """Plays a copy: reach the matching decision, apply the candidate, finish the turn by fixed rules."""

    def __init__(self, pilot: LookaheadPilot, snap: dict, kind: str, key: tuple, picks=(), choice=None):
        self.pilot, self.kind, self.key = pilot, kind, key
        self.picks, self.choice, self.prompts = list(picks), choice, 0
        self.attacks, self.missed_choice = 0, False
        self.revealed = False   # the opponent's hand was shown during this line
        real = snap["turn"]
        self.turn = Turn(normal_summoned=real.normal_summoned,
                         monster_effects_used=set(real.monster_effects_used), attacked=set(real.attacked))
        self.can_attack = snap["can_attack"]
        self.rules = Rules(0, pilot.db, random.Random(pilot.rng.randrange(1 << 30)), pilot.profile)
        self.applied = self.done = False

    def __call__(self, msg, duel):
        if self.done:
            raise EndOfTurn
        if msg is None:
            return struct.pack("<i", 0)
        if msg.id == MSG_SELECT_IDLECMD:
            cmd = parse_idlecmd(msg.payload)
            if cmd.player != 0:
                raise EndOfTurn
            if not self.applied:
                if self.kind == "battle":
                    return IdleCmd.encode(IDLE_TO_BP) if cmd.to_bp else self._fail()
                return self._apply_idle(cmd)
            r = self.rules.idle(cmd, self.turn, allow_bp=self.can_attack)
            return self._track_idle(r, cmd)
        if msg.id == MSG_SELECT_BATTLECMD:
            cmd = parse_select_battlecmd(msg.payload)
            if not self.applied and self.kind == "battle":
                return self._apply_battle(cmd)
            r = self.rules.battle(cmd, self.turn, duel)
            k, i = struct.unpack("<i", r)[0] & 0xFFFF, struct.unpack("<i", r)[0] >> 16
            if k == BATTLE_ATTACK:
                self.turn.attacked.add(cmd.attackable[i].sequence)
                self.attacks += 1
            return r
        if msg.id == MSG_SELECT_CARD and self.applied and not self.rules.attack_pending and \
                self.prompts <= len(self.picks) and (self.prompts < len(self.picks) or self.choice):
            return self._replay_pick(msg, duel)
        if msg.id == MSG_SELECT_CHAIN:
            ch = parse_select_chain(msg.payload)
            if ch.player != 0:
                return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)  # passive opponent
        return self.rules.respond(msg, duel, self.turn)

    def _replay_pick(self, msg, duel) -> bytes:
        sel = parse_select_card(msg.payload)
        want = self.picks[self.prompts] if self.prompts < len(self.picks) else [self.choice]
        self.prompts += 1
        places = [(c, *sel.places[i][:2]) for i, c in enumerate(sel.codes)] if sel.places else []
        idx = []
        for w in want:
            j = next((i for i, p in enumerate(places) if p == w and i not in idx), None)
            if j is not None:
                idx.append(j)
        if self.prompts - 1 == len(self.picks) and not idx:
            self.missed_choice = True          # the option under test is not on offer in the copy
            self._fail()
        if len(idx) < max(1, sel.min):
            return self.rules.respond(msg, duel, self.turn)
        return SelectCard.encode(sorted(idx))

    def _fail(self):
        self.done = True
        raise EndOfTurn

    def _apply_idle(self, cmd: IdleCmd) -> bytes:
        k = self.key
        if k == ("to_bp",):
            if not (cmd.to_bp and self.can_attack):
                return self._fail()
            self.applied = True
            return IdleCmd.encode(IDLE_TO_BP)
        if k == ("to_ep",):
            self.applied = True
            return IdleCmd.encode(IDLE_TO_EP)
        lst = {IDLE_ACTIVATE: cmd.activatable, IDLE_SUMMON: cmd.summonable, IDLE_SPSUMMON: cmd.spsummonable,
               IDLE_MSET: cmd.msetable, IDLE_SSET: cmd.ssetable}[k[0]]
        for i, c in enumerate(lst):
            if (k[0], c.code, c.location, c.sequence if c.location != LOCATION_HAND else 0, c.description) == k:
                self.applied = True
                return self._track_idle(IdleCmd.encode(k[0], i), cmd)
        return self._fail()

    def _track_idle(self, r: bytes, cmd: IdleCmd) -> bytes:
        v = struct.unpack("<i", r)[0]
        t, i = v & 0xFFFF, v >> 16
        if t in (IDLE_SUMMON, IDLE_MSET):
            self.turn.normal_summoned = True
        if t == IDLE_ACTIVATE and cmd.activatable[i].location == LOCATION_MZONE:
            self.turn.monster_effects_used.add(cmd.activatable[i].code)
        return r

    def _apply_battle(self, cmd: BattleCmd) -> bytes:
        k = self.key
        if k == ("leave",):
            self.applied = True
            return BattleCmd.encode(BATTLE_TO_M2 if cmd.to_m2 else BATTLE_TO_EP)
        if k[0] == "attack":
            for i, c in enumerate(cmd.attackable):
                if (c.code, c.sequence) == k[1:] and c.sequence not in self.turn.attacked:
                    self.turn.attacked.add(c.sequence)
                    self.attacks += 1
                    self.applied = True
                    self.rules.attack_pending = True
                    return BattleCmd.encode(BATTLE_ATTACK, i)
        if k[0] == "bact":
            for i, c in enumerate(cmd.activatable):
                if ("bact", c.code, c.location, c.description) == k:
                    self.applied = True
                    return BattleCmd.encode(BATTLE_ACTIVATE, i)
        return self._fail()


# ------------------------------------------------------------------ forks: response prompts

class Fork:
    """The real duel replayed to the current prompt, scrubbed, then one candidate answer played out.

    A puzzle copy starts at a fresh Main Phase and cannot hold a declared attack or an open chain, which is
    exactly what a response prompt is about. So a fork rebuilds the real duel from its seeds, dealt decks
    and response log (the same data a .yrp holds) and stops at this prompt. That rebuild necessarily
    contains hidden information, so before any candidate is played it is scrubbed with Card.Recreate
    (new identity *and* effects), drawing the same knowledge line as the puzzle copies:
      * our Deck: contents known, order not -> the codes are permuted with the pilot's own RNG
        (Normal and effect monsters separately: the core cannot move effects onto or off a Normal)
      * the opponent's hand and Deck -> INERT (count kept, identity gone)
      * the opponent's face-down monsters -> INERT at the typical face-down 450 ATK / 500 DEF
      * the engine's RNG -> advanced a pilot-chosen number of steps, so the fork cannot foresee coin
        tosses or shuffles in the real duel
    Left alone: cards whose effect is on the chain right now (their effect is in use), and the opponent's
    face-down Spells/Traps (the opponent is passive in a fork and never activates them).

    After the candidate: our later prompts use the fixed rules but never start a new response, the
    opponent declines everything optional, and the fork is scored when the turn player next gets a free
    Main/Battle Phase menu, the turn ends, or the duel ends - i.e. once this event has played out.
    """

    STOP = (MSG_SELECT_IDLECMD, MSG_SELECT_BATTLECMD)

    def __init__(self, pilot: "LookaheadPilot", duel, msg):
        self.pilot, self.real, self.msg = pilot, duel, msg
        self.log = list(duel.responses)
        self.fed = 0
        self.applied = self.done = self.desync = False
        self.rules = Rules(pilot.me, pilot.db, random.Random(pilot.rng.randrange(1 << 30)), pilot.profile)
        self.other = RandomLegal(seed=pilot.rng.randrange(1 << 30))
        self.candidate = None
        self.revealed = False

    # the scrub, as Lua run inside the fork
    def scrub_lua(self) -> str:
        me, op, db = self.pilot.me, 1 - self.pilot.me, self.pilot.db
        codes = [c.code for c in read_board(self.real, me).deck if c]
        normal = [c for c in codes if (db.row(c) or (0,) * 5)[4] & TYPE_NORMAL]
        effect = [c for c in codes if c not in normal]
        self.pilot.rng.shuffle(normal)
        self.pilot.rng.shuffle(effect)
        nil12 = ",".join(["nil"] * 11)
        return "\n".join([
            "local skip = {}",
            "for i = 1, Duel.GetCurrentChain() do",
            "  local te = Duel.GetChainInfo(i, CHAININFO_TRIGGERING_EFFECT)",
            "  if te then skip[te:GetHandler()] = true end",
            "end",
            f"local eff, nor, ie, inn = {{{','.join(map(str, effect))}}}, {{{','.join(map(str, normal))}}}, 1, 1",
            f"for c in aux.Next(Duel.GetFieldGroup({me}, LOCATION_DECK, 0)) do",
            "  if not skip[c] then",
            f"    if c:IsType(TYPE_NORMAL) then if nor[inn] then c:Recreate(nor[inn],{nil12},true) end inn = inn + 1",
            f"    else if eff[ie] then c:Recreate(eff[ie],{nil12},true) end ie = ie + 1 end",
            "  end",
            "end",
            f"for c in aux.Next(Duel.GetFieldGroup({op}, LOCATION_HAND + LOCATION_DECK, 0)) do",
            f"  if not skip[c] then c:Recreate({INERT},{nil12},true) end",
            "end",
            f"for c in aux.Next(Duel.GetFieldGroup({op}, LOCATION_MZONE, 0)) do",
            "  if c:IsFacedown() and not skip[c] then",
            f"    c:Recreate({INERT},nil,nil,nil,nil,nil,nil,450,{TYPICAL_FACEDOWN_DEF},nil,nil,nil,true)",
            "  end",
            "end",
            f"for i = 1, {self.pilot.rng.randrange(1, 64)} do Duel.GetRandomNumber(0, 1) end",
            "",
        ])

    def evaluate(self, candidate: bytes) -> float:
        t = time.perf_counter()
        try:
            return self._evaluate(candidate)
        finally:
            self.pilot.t_forks += time.perf_counter() - t

    def _evaluate(self, candidate: bytes) -> float:
        p = self.pilot
        p.forks += 1
        self.candidate = candidate
        real = self.real
        try:
            fork = type(real)(real.seed, lib=p.lib or real.lib, carddb=p.db, scripts=real.scripts,
                              flags=real.flags, starting_lp=real.starting_lp, starting_draw=real.starting_draw,
                              draw_per_turn=real.draw_per_turn)
        except Exception:
            return float("-inf")
        with fork as f:
            for team, (main, extra) in enumerate(real.dealt):
                f.load_deck(team, main, extra)
            read = f._messages

            def watched():
                batch = read()
                for m in batch:
                    track_targets(m, self.rules.doomed)
                if self.applied:
                    for m in batch:
                        if m.id in (MSG_WIN, MSG_NEW_TURN):
                            self.done = True
                        self.revealed = self.revealed or reveals_hand(m, 1 - p.me)
                return batch
            f._messages = watched
            f.start()
            try:
                f.run(self, max_steps=len(self.log) + 2000, retry_limit=8, policy1=self)
            except EndOfTurn:
                pass
            except Exception:
                return float("-inf")
            if not self.applied or self.desync:
                return float("-inf")
            b = read_board(f, p.me)
            levels = tuple(sorted({row[7] & 0xFF for c in b.extra if c and (row := p.db.row(c.code))
                                   and row[4] & TYPE_SYNCHRO}))
            return score(f, p.me, p.db, p.profile, 0, 0, levels, gy=p.gy, revealed=self.revealed)

    def __call__(self, msg, duel):
        if self.fed < len(self.log):          # replaying the real duel up to the prompt
            self.fed += 1
            return self.log[self.fed - 1]
        if not self.applied:                  # at the prompt: scrub, then play the candidate
            if msg is None or msg.id != self.msg.id or msg.payload != self.msg.payload:
                self.desync = True
                raise EndOfTurn
            lua = self.scrub_lua().encode()
            if not duel.lib.OCG_LoadScript(duel.handle, lua, len(lua), b"fork_scrub.lua"):
                self.desync = True
                raise EndOfTurn
            self.applied = True
            return self.candidate
        if self.done or msg is None or msg.id in self.STOP:
            raise EndOfTurn
        me = self.pilot.me
        if msg.player != me:                  # the opponent: passive
            if msg.id == MSG_SELECT_CHAIN:
                ch = parse_select_chain(msg.payload)
                return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)
            if msg.id in (MSG_SELECT_EFFECTYN, MSG_SELECT_YESNO):
                return struct.pack("<i", 0)
            return self.other(msg, duel)
        if msg.id == MSG_SELECT_CHAIN:        # us: no further responses inside a fork
            ch = parse_select_chain(msg.payload)
            return SelectChain.decline() if ch.can_decline() else SelectChain.encode(0)
        return self.rules.respond(msg, duel, self.pilot.turn)
