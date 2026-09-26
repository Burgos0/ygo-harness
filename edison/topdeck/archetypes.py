"""PROPOSED Edison archetype groupings from signature cards - not final, pending the user's review.

Each rule is (archetype, [(card name, min copies in main+extra), ...], how many of those must hold).
Rules are tried in order; the first that matches names the deck, else "Unclassified".
The defining cards reported alongside each group are measured from the decks it captured
(inclusion rate), so a rule that captures the wrong decks shows up as odd defining cards.
"""
from __future__ import annotations

from collections import Counter

PROPOSED: list[tuple[str, list[tuple[str, int]], int]] = [
    ("Blackwing", [("Blackwing - Kalut the Moon Shadow", 1), ("Blackwing - Shura the Blue Flame", 1),
                   ("Black Whirlwind", 1), ("Blackwing - Sirocco the Dawn", 2),
                   ("Blackwing - Bora the Spear", 1)], 3),
    # DARK engine + Blackwing starters without the full Blackwing package (Kalut/Shura/Whirlwind).
    ("Blackwing-DAD", [("Dark Armed Dragon", 1), ("Dark Grepher", 1), ("Armageddon Knight", 1),
                       ("Blackwing - Vayu the Emblem of Honor", 1), ("Blackwing - Sirocco the Dawn", 1)], 4),
    ("Lightsworn", [("Judgment Dragon", 1), ("Lumina, Lightsworn Summoner", 1),
                    ("Wulf, Lightsworn Beast", 1), ("Charge of the Light Brigade", 1)], 2),
    ("Gladiator Beasts", [("Gladiator Beast Bestiari", 1), ("Gladiator Beast Darius", 1),
                          ("Test Tiger", 1)], 2),
    ("Machina Gadgets", [("Machina Gearframe", 1), ("Green Gadget", 1), ("Red Gadget", 1),
                         ("Yellow Gadget", 1)], 3),
    ("Frog Monarchs", [("Treeborn Frog", 1), ("Swap Frog", 1), ("Substitoad", 1),
                       ("Caius the Shadow Monarch", 1)], 3),
    ("Machina", [("Machina Fortress", 1), ("Machina Gearframe", 1)], 2),
    ("Quickdraw Plants", [("Quickdraw Synchron", 1), ("Lonefire Blossom", 1), ("Dandylion", 1)], 2),
    ("Zombies", [("Goblin Zombie", 1), ("Zombie Master", 1), ("Mezuki", 1)], 2),
    ("Tele-DAD", [("Emergency Teleport", 1), ("Krebons", 1), ("Psychic Commander", 1),
                  ("Dark Armed Dragon", 1)], 3),
    ("HERO Beat", [("Elemental HERO Stratos", 1), ("Miracle Fusion", 1)], 2),
    ("X-Sabers", [("X-Saber Airbellum", 1), ("XX-Saber Faultroll", 1), ("Saber Slash", 1)], 2),
    ("Gravekeepers", [("Gravekeeper's Spy", 1), ("Necrovalley", 1), ("Gravekeeper's Descendant", 1)], 2),
    ("REDMD Dragons", [("Red-Eyes Darkness Metal Dragon", 1), ("Five-Headed Dragon", 1),
                       ("Koa'ki Meiru Drago", 1)], 2),
    ("Chaos / DAD Control", [("Dark Armed Dragon", 1), ("Chaos Sorcerer", 1),
                             ("Return from the Different Dimension", 1)], 2),
]


def classify(names: Counter) -> str:
    """names: card name -> copies across main+extra."""
    for archetype, signature, need in PROPOSED:
        if sum(names.get(card, 0) >= n for card, n in signature) >= need:
            return archetype
    return "Unclassified"
