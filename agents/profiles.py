"""Deck profiles for agents.lookahead.LookaheadPilot: the only place card names live.

A profile is weights (what a good end of turn looks like for this deck), priorities (engine cards,
discard order, archetype to search), hints (cards never to activate, key cards worth holding) and a
progress hook: win-condition setup a slow deck spends turns on, scored even with no board change.
"""
from __future__ import annotations

from agents.lookahead import Profile, Weights
from engine.constants import ATTRIBUTE_DARK, TYPE_MONSTER

DD_CROW = 24508238


def _judgment_dragon(mine, theirs, db) -> float:
    """Progress toward Judgment Dragon: distinct Lightsworn monster names in the GY, toward 4 (its Summon
    condition). Four names are worth a card; more names are worth nothing extra; once it is live with
    Judgment Dragon in hand, a further 60."""
    names = {db.name(c.code) for c in mine.grave if c and "Lightsworn" in db.archetypes(c.code)
             and (db.row(c.code) or (0,) * 5)[4] & TYPE_MONSTER}
    s = 25.0 * min(len(names), 4)
    if len(names) >= 4 and any(c and db.name(c.code) == "Judgment Dragon" for c in mine.hand):
        s += 60.0
    return s


LIGHTSWORN = Profile(
    name="Lightsworn",
    deck="edison/decks/lightsworn.ydk",
    weights=Weights(),                       # the v2 weights; a mill deck, so urgency is on
    engine=frozenset({"Lumina, Lightsworn Summoner", "Solar Recharge", "Charge of the Light Brigade"}),
    discard_first=("Wulf, Lightsworn Beast",),   # Special Summons itself when discarded
    search_archetype="Lightsworn",
    hold=frozenset({DD_CROW}),
    key_cards=frozenset({"Judgment Dragon"}),
    progress=_judgment_dragon,
)

def _dark_armed_dragon(mine, theirs, db) -> float:
    """Progress toward Dark Armed Dragon: its Special Summon needs *exactly* 3 DARK monsters in the GY.
    Each DARK up to 3 is progress; each one over 3 is penalized (DAD is then unsummonable until some are
    banished); exactly 3 with DAD in hand is a further 60."""
    darks = sum(1 for c in mine.grave if c and (r := db.row(c.code)) and r[4] & TYPE_MONSTER
                and r[9] & ATTRIBUTE_DARK)
    s = 25.0 * min(darks, 3) - 40.0 * max(0, darks - 3)
    if darks == 3 and any(c and db.name(c.code) == "Dark Armed Dragon" for c in mine.hand):
        s += 60.0
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
    key_cards=frozenset({"Dark Armed Dragon", "Gorz the Emissary of Darkness"}),
    progress=_dark_armed_dragon,
)

PROFILES = {"lightsworn": LIGHTSWORN, "blackwing_dad": BLACKWING_DAD}
