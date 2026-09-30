"""Deck profiles for agents.lookahead.LookaheadPilot: the only place card names live.

A profile is weights (what a good end of turn looks like for this deck), priorities (engine cards,
discard order, archetype to search) and hints (cards to hold, a deck-specific score term).
"""
from __future__ import annotations

from agents.lookahead import Profile, Weights
from engine.constants import ATTRIBUTE_DARK, TYPE_MONSTER

DD_CROW = 24508238


def _judgment_dragon(mine, theirs, db) -> float:
    """Judgment Dragon needs 4 Lightsworn names in the GY: reward progress, and a lot once it is live."""
    names = {c.code for c in mine.grave if c and "Lightsworn" in db.archetypes(c.code)}
    s = 10.0 * min(len(names), 4)
    if len(names) >= 4 and any(c and db.name(c.code) == "Judgment Dragon" for c in mine.hand):
        s += 80.0
    return s


LIGHTSWORN = Profile(
    name="Lightsworn",
    deck="edison/decks/lightsworn.ydk",
    weights=Weights(),                       # the v2 weights; a mill deck, so urgency is on
    engine=frozenset({"Lumina, Lightsworn Summoner", "Solar Recharge", "Charge of the Light Brigade"}),
    discard_first=("Wulf, Lightsworn Beast",),   # Special Summons itself when discarded
    search_archetype="Lightsworn",
    hold=frozenset({DD_CROW}),
    bonus=_judgment_dragon,
)

def _dark_armed_dragon(mine, theirs, db) -> float:
    """Dark Armed Dragon is Special Summoned with exactly 3 DARK monsters in the GY: reward getting there,
    and a lot when DAD is in hand and the count is exactly 3. A 4th DARK makes DAD unsummonable."""
    darks = sum(1 for c in mine.grave if c and (r := db.row(c.code)) and r[4] & TYPE_MONSTER
                and r[9] & ATTRIBUTE_DARK)
    s = 10.0 * min(darks, 3) - 15.0 * max(0, darks - 3)
    if darks == 3 and any(c and db.name(c.code) == "Dark Armed Dragon" for c in mine.hand):
        s += 80.0
    return s


BLACKWING_DAD = Profile(
    name="Blackwing-DAD",
    deck="edison/decks/blackwing_dad.ydk",
    # Beatdown with Synchros: no self-mill, so LP terms never scale with the Deck (urgency off).
    weights=Weights(urgency_deck=0),
    # Armageddon Knight fills the GY with a DARK; Reinforcement searches it; Gale/Vayu start Synchros.
    engine=frozenset({"Armageddon Knight", "Reinforcement of the Army", "Blackwing - Gale the Whirlwind"}),
    discard_first=("Necro Gardna", "Plaguespreader Zombie"),   # both do their work from the GY
    search_archetype="Blackwing",
    hold=frozenset({DD_CROW}),
    bonus=_dark_armed_dragon,
)

PROFILES = {"lightsworn": LIGHTSWORN, "blackwing_dad": BLACKWING_DAD}
