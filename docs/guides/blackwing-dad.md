# Blackwing-DAD: play notes (expert guide)

Source: notes supplied with tuning round 2 (2026-09-30). These are how the deck is meant to be played;
`agents/profiles.py` (`BLACKWING_DAD`) is the pilot's translation of them. The list is
`edison/decks/blackwing_dad.ydk` - it does not run Blackwing - Blizzard the Far North, so the Blizzard
line below has no card to act on in this list.

## 1. The Vayu engine is setup, not card loss

- Blackwing - Vayu the Emblem of Honor in the GY is progress.
- Vayu + a non-Tuner Blackwing in the GY whose Levels sum to a Blackwing Synchro still in the Extra
  Deck means a Synchro is "live": Vayu banishes itself and that monster from the GY to Special Summon
  the Synchro.
- The chain climbs: Vayu (1) + Sirocco (5) -> Blackwing Armed Wing (6); Vayu + Armed Wing (6) ->
  Blackwing Armor Master (7); Vayu + Armor Master (7) -> Blackwing - Silverwind the Ascendant (8).
- A dead Blackwing Synchro with Vayu available is fuel for the next one, not a full card lost.

## 2. Use Vayu freely

Vayu's GY effect is not once per turn and cannot be hit by Solemn Judgment (it is not a Summon that
Solemn can negate). Use it whenever the resulting Synchro improves the board.

## 3. Icarus Attack

- Highest value: in response to the opponent's removal targeting one of our Winged Beasts - Tribute the
  doomed monster as the cost, so it was lost anyway and Icarus destroys two of theirs.
- A plain 2-for-2 trade (Tribute a healthy monster, destroy two) is acceptable when we have spare
  monsters.

## 4. Return from the Different Dimension

- Value it by the total ATK of our banished monsters against the opponent's LP and blockers.
- Activate it on our own turn when it can deal lethal.
- Vayu's banishes (Vayu plus its partner, every time) are progress toward it.

## 5. Dark Armed Dragon

Dark Armed Dragon needs exactly 3 DARK monsters in the GY. Vayu banishes (two DARKs out of the GY) and
Blizzard revives are tools to bring the count back to exactly 3.
