"""Deck profiles for agents.lookahead.LookaheadPilot: the only place card names live.

A profile is weights (what a good end of turn looks like for this deck), priorities (engine cards,
discard order, archetype to search), hints (cards never to activate, key cards worth holding) and a
progress hook: win-condition setup a slow deck spends turns on, scored even with no board change.
"""
from __future__ import annotations

from dataclasses import replace

from agents.lookahead import Profile, Weights
from engine.constants import ATTRIBUTE_DARK, TYPE_MONSTER, TYPE_SYNCHRO, TYPE_TUNER

DD_CROW = 24508238


def _judgment_dragon(mine, theirs, db, ctx=None) -> float:
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

# ---------------------------------------------------------------- Blackwing-DAD (docs/guides/blackwing-dad.md)

VAYU = "Blackwing - Vayu the Emblem of Honor"
RFTDD = "Return from the Different Dimension"


def _row(db, code):
    return db.row(code) or (0,) * 10


def _is_dark_monster(db, code) -> bool:
    r = _row(db, code)
    return bool(r[4] & TYPE_MONSTER and r[9] & ATTRIBUTE_DARK)


def _vayu_fuel(mine, db) -> tuple[int, list[int]]:
    """(Vayus in our GY, Levels of the non-Tuner Blackwings in our GY that pair with Vayu into a Blackwing
    Synchro still in our Extra Deck). Vayu's effect: banish it + that monster, Special Summon the Synchro
    whose Level is their sum - Vayu is Level 1."""
    extra_levels = {_row(db, c.code)[7] & 0xFF for c in mine.extra
                    if c and _row(db, c.code)[4] & TYPE_SYNCHRO and "Blackwing" in db.archetypes(c.code)}
    vayus = sum(1 for c in mine.grave if c and db.name(c.code) == VAYU)
    fuel = [_row(db, c.code)[7] & 0xFF for c in mine.grave
            if c and db.name(c.code) != VAYU and "Blackwing" in db.archetypes(c.code)
            and _row(db, c.code)[4] & TYPE_MONSTER and not _row(db, c.code)[4] & TYPE_TUNER
            and (_row(db, c.code)[7] & 0xFF) + 1 in extra_levels]
    return vayus, fuel


def _rftdd_damage(mine, theirs, db) -> int:
    """What Return from the Different Dimension could swing in this turn: our banished monsters come back
    (as many as our free Monster Zones hold), attack alongside our face-up attackers, and the opponent's
    monsters each block one attacker - they block the strongest (the conservative case)."""
    free = 5 - sum(1 for c in mine.monsters if c)
    back = sorted((_row(db, c.code)[5] for c in mine.banished if c and _row(db, c.code)[4] & TYPE_MONSTER),
                  reverse=True)[:free]
    attackers = sorted(back + [c.attack for c in mine.monsters if c and c.position & 0x1], reverse=True)
    blockers = sum(1 for c in theirs.monsters if c)
    return sum(attackers[blockers:])


def _blackwing_dad(mine, theirs, db, ctx=None) -> float:
    """Blackwing-DAD's setup progress (guide sections 1, 4, 5)."""
    s = 0.0
    # 1. Vayu engine: Vayu in the GY is progress; Vayu + a partner = a Synchro is live; a dead Blackwing
    #    Synchro that Vayu can climb from is fuel (half a card back), not a full card lost.
    vayus, fuel = _vayu_fuel(mine, db)
    s += 20.0 * min(vayus, 2)
    uses = min(vayus, len(fuel))
    if uses:
        s += 60.0
        synchro_fuel = sum(1 for c in mine.grave if c and _row(db, c.code)[4] & TYPE_SYNCHRO
                           and "Blackwing" in db.archetypes(c.code) and (_row(db, c.code)[7] & 0xFF) in fuel)
        s += 50.0 * min(uses, synchro_fuel)
    # 5. Dark Armed Dragon: exactly 3 DARK monsters in the GY. A Vayu use banishes two DARKs (Vayu and its
    #    Blackwing partner), so an excess it can bring back to exactly 3 is only half a problem.
    darks = sum(1 for c in mine.grave if c and _is_dark_monster(db, c.code))
    reachable = darks - 2 if uses and darks - 2 >= 3 else darks
    s += 25.0 * min(darks, 3)
    s -= 40.0 * max(0, darks - 3) * (0.5 if reachable == 3 else 1.0)
    has_dad = any(c and db.name(c.code) == "Dark Armed Dragon" for c in mine.hand)
    if has_dad and darks == 3:
        s += 60.0
    elif has_dad and reachable == 3:
        s += 30.0
    # 4. Return from the Different Dimension: banished ATK against their LP and blockers (Vayu's banishes
    #    feed it). Lethal on board with RftDD available is worth a lot; short of that, progress toward it.
    if ctx is not None and any(c and db.name(c.code) == RFTDD for c in mine.hand + mine.spells):
        dmg = _rftdd_damage(mine, theirs, db)
        s += 60.0 * min(1.0, dmg / max(1, ctx.op_lp))
        if dmg >= ctx.op_lp and ctx.my_lp > 1:
            s += 150.0
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
    progress=_blackwing_dad,
    # Vayu's GY effect is not once per turn and cannot be hit by Solemn; RftDD is a finisher - keep both in
    # every Main Phase search (guide 2, 4).
    always_consider=frozenset({VAYU, RFTDD}),
    # A plain 2-for-2 Icarus trade is acceptable (guide 3): half the usual holding value.
    hold_factor=(("Icarus Attack", 0.5),),
)

# ---------------------------------------------------------------- Blackwing (pure) (docs/guides/blackwing.md)

WHIRLWIND = "Black Whirlwind"
SHURA = "Blackwing - Shura the Blue Flame"


def _blackwing(mine, theirs, db, ctx=None) -> float:
    """Pure Blackwing's setup progress: the shared Blackwing terms (Vayu engine, exactly-3 DARKs for its one
    Dark Armed Dragon) plus Black Whirlwind on the field (guide 1) and a Shura that can win a battle
    (guide 4: its trigger Special Summons a Blackwing <= 1500 ATK - often a Tuner - from the Deck)."""
    s = _blackwing_dad(mine, theirs, db, ctx)
    if any(c and c.position & 0x5 and db.name(c.code) == WHIRLWIND for c in mine.spells):
        s += 80.0
    shura = [c for c in mine.monsters if c and c.position & 0x1 and db.name(c.code) == SHURA]
    if shura:
        # what an attacker must beat: ATK in Attack Position, DEF in Defense, the typical DEF if face-down
        walls = [c.attack if c.position & 0x1 else c.defense if c.position & 0x4 else 500
                 for c in theirs.monsters if c]
        if any(max(x.attack for x in shura) > w for w in walls):
            s += 30.0
    return s


BLACKWING = Profile(
    name="Blackwing",
    deck="edison/decks/blackwing.ydk",
    # Beatdown: no self-mill, LP terms flat.
    weights=Weights(urgency_deck=0),
    # Black Whirlwind is the engine (guide 1): activated first, never cut.
    engine=frozenset({WHIRLWIND}),
    discard_first=("Blackwing - Blizzard the Far North",),
    search_archetype="Blackwing",
    hold=frozenset({DD_CROW}),
    # Worth more in hand than on the field: Bora for a Whirlwind search or the winning attack (guide 2),
    # Kalut for the battle that matters (guide 3); Gorz and Dark Armed Dragon as in Blackwing-DAD.
    key_cards=frozenset({"Blackwing - Bora the Spear", "Blackwing - Kalut the Moon Shadow",
                         "Gorz the Emissary of Darkness", "Dark Armed Dragon"}),
    progress=_blackwing,
    # Gale's halving (guide 5), Sirocco's one big attack (guide 6), Vayu: always in the Main Phase search.
    always_consider=frozenset({"Blackwing - Gale the Whirlwind", "Blackwing - Sirocco the Dawn", VAYU}),
    # Icarus Attack: spare monsters into removal (guide 7) - half holding value, as in Blackwing-DAD; the
    # doomed-monster Tribute is the generic rule.
    hold_factor=(("Icarus Attack", 0.5),),
)


# ---------------------------------------------------------------- v1: the evaluation before c62c3c6
# Kept for attribution runs (one side on the old evaluation, the other on the new). v1 = the current
# score() with every term added in c62c3c6 at zero weight, and the progress bonuses as they were then.

_V1_OFF = dict(gy_resource=0.0, hold=0.0, key_card=0.0, op_board_atk=0.0, lethal_threat=0.0, low_lp=0.0,
               lp_curve=False, hidden_hand=0.0, reveal=0.0)


def _judgment_dragon_v1(mine, theirs, db, ctx=None) -> float:
    names = {c.code for c in mine.grave if c and "Lightsworn" in db.archetypes(c.code)}
    s = 10.0 * min(len(names), 4)
    if len(names) >= 4 and any(c and db.name(c.code) == "Judgment Dragon" for c in mine.hand):
        s += 80.0
    return s


def _dark_armed_dragon_v1(mine, theirs, db, ctx=None) -> float:
    darks = sum(1 for c in mine.grave if c and (r := db.row(c.code)) and r[4] & TYPE_MONSTER
                and r[9] & ATTRIBUTE_DARK)
    s = 10.0 * min(darks, 3) - 15.0 * max(0, darks - 3)
    if darks == 3 and any(c and db.name(c.code) == "Dark Armed Dragon" for c in mine.hand):
        s += 80.0
    return s


LIGHTSWORN_V1 = replace(LIGHTSWORN, weights=Weights(**_V1_OFF), key_cards=frozenset(),
                        progress=_judgment_dragon_v1)
BLACKWING_DAD_V1 = replace(BLACKWING_DAD, weights=Weights(urgency_deck=0, **_V1_OFF), key_cards=frozenset(),
                           progress=_dark_armed_dragon_v1)

PROFILES = {"lightsworn": LIGHTSWORN, "blackwing_dad": BLACKWING_DAD, "blackwing": BLACKWING,
            "lightsworn@v1": LIGHTSWORN_V1, "blackwing_dad@v1": BLACKWING_DAD_V1}
