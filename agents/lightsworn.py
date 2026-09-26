"""Lightsworn pilot v0: one-ply lookahead to the end of our own turn, plus a scoring function.

    from agents.lightsworn import LightswornPilot
    d.run(LightswornPilot(seat=0, seed=7), policy1=RandomLegal(seed=7))   # or policy/policy1 swapped

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

import random
import struct
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from agents.random_legal import RandomLegal
from engine.board import query_field, read_board
from engine.carddb import CardDB
from engine.constants import (LOCATION_HAND, LOCATION_MZONE, LOCATION_SZONE, MSG_NEW_PHASE,
                              MSG_NEW_TURN, MSG_SELECT_BATTLECMD, MSG_SELECT_CARD, MSG_SELECT_CHAIN,
                              MSG_SELECT_EFFECTYN, MSG_SELECT_IDLECMD, MSG_SELECT_POSITION,
                              MSG_SELECT_YESNO, MSG_WIN, PHASE_END, PHASE_MAIN2, TYPE_MONSTER,
                              TYPE_SYNCHRO, TYPE_TUNER)
from engine.duel import Duel
from engine.messages import (BATTLE_ACTIVATE, BATTLE_ATTACK, BATTLE_TO_EP, BATTLE_TO_M2, IDLE_ACTIVATE,
                             IDLE_MSET, IDLE_SPSUMMON, IDLE_SSET, IDLE_SUMMON, IDLE_TO_BP, IDLE_TO_EP,
                             BattleCmd, IdleCmd, SelectCard, SelectChain, parse_idlecmd,
                             parse_select_battlecmd, parse_select_card, parse_select_chain)
from engine.puzzle import Puzzle

#: A face-down monster we cannot see is treated as the format's typical small monster: DEF 500 is the
#: median DEF of the 46,580 level 1-4 main-deck monster copies in the TopDeck Edison lists (quartiles
#: 200 / 500 / 1200, mean 765). Worst-case (2000) made the pilot never attack face-downs and deck out.
TYPICAL_FACEDOWN_DEF = 500
PLACEHOLDER = 59053232     # Turu-Purun, vanilla 450/500: stands in for an unknown face-down monster
FILLER = 15025844          # opponent's unknown Deck cards
ENGINE = {"Lumina, Lightsworn Summoner", "Solar Recharge", "Charge of the Light Brigade"}
JUDGMENT_DRAGON = "Judgment Dragon"
DD_CROW = 24508238


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

    def __init__(self, me: int, db: CardDB, rng: random.Random):
        self.me, self.db, self.rng = me, db, rng
        self.fallback = RandomLegal(seed=rng.randrange(1 << 30))
        self.attack_pending = False  # the next card choice is an attack target

    def name(self, code: int) -> str:
        return self.db.name(code) or ""

    def idle(self, cmd: IdleCmd, turn: Turn, allow_bp: bool) -> bytes:
        for i, c in enumerate(cmd.activatable):          # the engine first
            if self.name(c.code) in ENGINE and not self._used(c, turn):
                return IdleCmd.encode(IDLE_ACTIVATE, i)
        if not turn.normal_summoned and cmd.summonable:  # Lumina first (the engine), else the biggest
            i = max(range(len(cmd.summonable)), key=lambda k: (self.name(cmd.summonable[k].code) in ENGINE,
                                                                self._atk(cmd.summonable[k].code)))
            return IdleCmd.encode(IDLE_SUMMON, i)
        for i, c in enumerate(cmd.activatable):          # any other activation, once
            if c.location == LOCATION_HAND or not self._used(c, turn):
                if self.name(c.code) not in ENGINE and c.code != DD_CROW:
                    return IdleCmd.encode(IDLE_ACTIVATE, i)
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
                if o.code != DD_CROW:
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
        # Prefer the opponent's strongest card, else our best monster to revive / Lightsworn to discard.
        def value(i):
            con = sel.places[i][0] if sel.places else self.me
            atk = self._atk(sel.codes[i])
            return (1, atk) if con != self.me else (0, atk + (500 if self._lightsworn(sel.codes[i]) else 0))
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
            want = 0x1 if self._atk(code) >= 1600 else 0x4
            for p in (want, 0x1, 0x4, 0x8, 0x2):
                if mask & p:
                    return struct.pack("<i", p)
        if msg.id == MSG_SELECT_CARD:
            r = self.select_card(msg, duel)
            if r is not None:
                return r
        return self.fallback(msg, duel)

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
    def _lightsworn(self, code: int) -> bool:
        return "Lightsworn" in self.db.archetypes(code)


# ------------------------------------------------------------------ scoring

def score(duel, me: int, db: CardDB, hidden_opp_hand: int, hidden_opp_set: int, extra_levels: tuple,
          attacks: int = 0) -> float:
    fi = query_field(duel)
    mine, theirs = read_board(duel, me), read_board(duel, 1 - me)
    my_lp, op_lp = fi.lp[me], fi.lp[1 - me]
    if op_lp <= 0 and my_lp > 0:
        return 1e6
    if my_lp <= 0:
        return -1e6
    my_mons = [c for c in mine.monsters if c]
    my_cards = sum(1 for c in mine.hand if c) + len(my_mons) + sum(1 for c in mine.spells if c)
    op_cards = (sum(1 for c in theirs.hand if c) + hidden_opp_hand + sum(1 for c in theirs.monsters if c)
                + sum(1 for c in theirs.spells if c) + hidden_opp_set)
    s = 100.0 * (my_cards - op_cards)                      # card advantage: heaviest
    deck = mine.deck_count or sum(1 for c in mine.deck if c)
    # LP: 1000 LP = 20 with a full Deck, worth up to 4x as much as our Deck runs out - a mill deck
    # must close the game before it decks out, so damage and attacking matter more late.
    urgency = 1.0 + max(0, 30 - deck) / 10.0
    s += 0.02 * urgency * (my_lp - op_lp)
    face_up = [c for c in my_mons if c.position & 0x5]
    s += sum(c.attack for c in face_up) / 100.0 + 15.0 * min(len(my_mons), 3)
    s -= 10.0 * max(0, len(my_mons) - 3)                   # don't overcommit into mass removal
    ls = {c.code for c in mine.grave if c and "Lightsworn" in db.archetypes(c.code)}
    s += 10.0 * min(len(ls), 4)                            # Judgment Dragon needs 4 names
    if len(ls) >= 4 and any(c and db.name(c.code) == JUDGMENT_DRAGON for c in mine.hand):
        s += 80.0                                          # Judgment Dragon summonable next turn
    # Risk of committing into set Spells/Traps (Mirror Force, Torrential, Bottomless...): each face-down
    # card the opponent controls threatens every extra monster we put out, and every attack we make.
    op_set = hidden_opp_set + sum(1 for c in theirs.spells if c and not c.position & 0x5)
    s -= op_set * (12.0 * max(0, len(my_mons) - 1) + 6.0 * attacks)
    tuners = [c.level for c in face_up if c.type & TYPE_TUNER]
    others = [c.level for c in face_up if not c.type & TYPE_TUNER]
    if any(t + o in extra_levels or t + o + o2 in extra_levels
           for t in tuners for i, o in enumerate(others) for o2 in [0] + others[i + 1:]):
        s += 20.0                                          # a Synchro play is on the board
    if deck < 10:
        s -= 5.0 * (10 - deck)                             # Lightsworn mills itself out
    return s


# ------------------------------------------------------------------ the pilot

class LightswornPilot:
    def __init__(self, seat: int, seed: int = 0, max_candidates: int = 8, lib=None, carddb=None, scripts=None,
                 flags: int | None = None):
        from edison.duel import EDISON_FLAGS
        from edison.provider import EdisonScriptProvider
        self.me = seat
        self.rng = random.Random(seed)
        self.db = carddb or CardDB()
        self.lib, self.scripts = lib, scripts or EdisonScriptProvider()
        self.flags = EDISON_FLAGS if flags is None else flags
        self.max_candidates = max_candidates
        self.rules = Rules(seat, self.db, self.rng)
        self.turn = Turn()
        self._hooked = None
        self.searches = self.copies = 0
        self._can_bp = False
        self.plan = None   # the last searched Main/Battle Phase action: its snapshot, key and card picks

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
                return self._remember(self._search("idle", cmd, duel), cmd, None)
        if msg.id == MSG_SELECT_BATTLECMD:
            cmd = parse_select_battlecmd(msg.payload)
            if cmd.player == self.me:
                self._in_battle, self._can_bp = True, False
                return self._remember(self._search("battle", cmd, duel), None, cmd)
        self._in_battle = False
        if msg.id == MSG_SELECT_CARD and self.plan and self.turn.player == self.me:
            return self._choose_card(msg, duel)
        return self.rules.respond(msg, duel, self.turn)

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
                    if key in seen or c.code == DD_CROW:
                        continue
                    if t in (IDLE_SUMMON, IDLE_MSET) and self.turn.normal_summoned:
                        continue
                    seen.add(key)
                    out.append((IdleCmd.encode(t, i), key))
            # engine cards first when the candidate list must be cut
            out.sort(key=lambda x: x[1][1] and self.db.name(x[1][1]) not in ENGINE)
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
        self.copies += 1
        path = Path(tempfile.gettempdir()) / f"lightsworn_copy_{id(self)}.lua"
        path.write_text(snap["lua"])
        copy = Duel.from_puzzle(Puzzle.load(path), lib=self.lib, carddb=self.db, scripts=self.scripts)
        roll = _Rollout(self, snap, kind, key, picks, choice)
        with copy as d:
            read = d._messages

            def watched():
                batch = read()
                for m in batch:
                    roll.turn.observe(m.id, m.payload)
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
            return score(d, 0, self.db, snap["hidden_hand"], snap["hidden_set"], snap["extra_levels"],
                         attacks=roll.attacks)


class _Rollout:
    """Plays a copy: reach the matching decision, apply the candidate, finish the turn by fixed rules."""

    def __init__(self, pilot: LightswornPilot, snap: dict, kind: str, key: tuple, picks=(), choice=None):
        self.pilot, self.kind, self.key = pilot, kind, key
        self.picks, self.choice, self.prompts = list(picks), choice, 0
        self.attacks, self.missed_choice = 0, False
        real = snap["turn"]
        self.turn = Turn(normal_summoned=real.normal_summoned,
                         monster_effects_used=set(real.monster_effects_used), attacked=set(real.attacked))
        self.can_attack = snap["can_attack"]
        self.rules = Rules(0, pilot.db, random.Random(pilot.rng.randrange(1 << 30)))
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
