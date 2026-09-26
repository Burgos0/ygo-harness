"""Edison duels: the 2010 rules preset, applied only here.

    from edison.duel import EdisonDuel
    with EdisonDuel(seed) as d:
        d.load_edison_deck(0, "my.ydk", shuffle_seed=1)   # validated by edison/deck.py
        ...

EDISON_FLAGS is the harness's MASTER_RULE_5 with the seven 2010 rules measured in
edison/RULES_2010.md. engine.duel.Duel keeps MASTER_RULE_5, so puzzles and every other test are
unchanged. EdisonDuel refuses any other flags and re-checks them at start(), and uses the Edison
script overrides (edison/scripts) by default.

Ignition priority uses DUEL_TCG_FAST_EFFECT_IGNITION, not DUEL_OCG_OBSOLETE_IGNITION: the site's
example (a Summon, then Plaguespreader Zombie's ignition effect in the GY) needs priority for
ignition effects off the field, which only the TCG variant grants (processor.cpp limits the OCG one
to monsters in the Monster Zone).
"""
from __future__ import annotations

from pathlib import Path

from engine.constants import (DUEL_0_ATK_DESTROYED, DUEL_1_FACEUP_FIELD, DUEL_1ST_TURN_DRAW,
                              DUEL_CAN_REPOS_IF_NON_SUMPLAYER, DUEL_TCG_FAST_EFFECT_IGNITION,
                              DUEL_TCG_SEGOC_FIRSTTRIGGER, DUEL_TRIGGER_ONLY_IN_LOCATION, MASTER_RULE_5)
from engine.duel import Duel
from edison.deck import load_ydk
from edison.provider import EdisonScriptProvider

EDISON_FLAGS = (
    (MASTER_RULE_5 & ~DUEL_TRIGGER_ONLY_IN_LOCATION)  # triggers still activate after leaving the zone
    | DUEL_1ST_TURN_DRAW                # the player going first draws
    | DUEL_TCG_FAST_EFFECT_IGNITION     # ignition priority (TCG ruling)
    | DUEL_TCG_SEGOC_FIRSTTRIGGER       # early trigger: what happened first chains first
    | DUEL_1_FACEUP_FIELD               # one face-up Field Spell on the whole field
    | DUEL_CAN_REPOS_IF_NON_SUMPLAYER   # may reposition a monster the *opponent* Summoned this turn
    | DUEL_0_ATK_DESTROYED              # 0-ATK monsters destroy each other by battle
)


class EdisonDuel(Duel):
    def __init__(self, seed, *, flags: int | None = None, scripts=None, **kwargs):
        if flags is not None and flags != EDISON_FLAGS:
            raise ValueError(f"an Edison duel runs with EDISON_FLAGS ({EDISON_FLAGS:#x}), not {flags:#x}")
        super().__init__(seed, flags=EDISON_FLAGS, scripts=scripts or EdisonScriptProvider(), **kwargs)

    def start(self) -> None:
        if self.flags != EDISON_FLAGS:
            raise RuntimeError(f"Edison duel flags were changed to {self.flags:#x}")
        super().start()

    def load_edison_deck(self, player: int, ydk: str | Path, shuffle_seed: int) -> None:
        """Load a .ydk after Edison validation (aliases, pool, banlist, 2010-text passcodes)."""
        deck = load_ydk(ydk)
        self.load_deck(player, deck.main, deck.extra, shuffle_seed=shuffle_seed)
