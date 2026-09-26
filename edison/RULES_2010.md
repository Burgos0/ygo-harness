# Edison (2010) rules vs. how our engine plays — measured

**Source.** edisonformat.net has no page titled "Rule Differences Between Edison & Modern" or
"Advanced Rules": not in its navigation, its sitemaps, or the Wayback Machine's index of the site.
Its material on how Edison differs from modern play is the **Rulings compendium**
(`/rules/compendium/*`, 28 topics), used here. The rulebook page is only the 2010 Official Rulebook
(v7.0) as a PDF.

**Method.** `python -m edison.rules_check` builds a small fixed field for each rule
(`edison/tests/scenario.py`) and runs it:
- once exactly as our duels run today (`MASTER_RULE_5`, the `engine.duel` default);
- once with the core duel flag that implements the 2010 rule, where one exists.

Nothing about how duels run was changed.

**Decks** = how many of the six opponent archetypes' tournament decks (TopDeck.gg data) contain the
cards that bring the rule into play. BW-DAD 549, BW 511, Frog 483, LS 372, Machina 250, GB 188.

## Edison preset (applied)

Edison duels run through `edison.duel.EdisonDuel` with `EDISON_FLAGS`. That is `MASTER_RULE_5`
minus `DUEL_TRIGGER_ONLY_IN_LOCATION`, plus `DUEL_1ST_TURN_DRAW`, `DUEL_TCG_FAST_EFFECT_IGNITION`,
`DUEL_TCG_SEGOC_FIRSTTRIGGER`, `DUEL_1_FACEUP_FIELD`, `DUEL_CAN_REPOS_IF_NON_SUMPLAYER` and
`DUEL_0_ATK_DESTROYED`. `engine.duel.Duel` (puzzles, every other test) keeps `MASTER_RULE_5`.

Ignition priority uses the TCG variant. The site's example (priority for Plaguespreader Zombie's
effect in the GY) needs ignition effects off the field, and the core limits the OCG variant to the
Monster Zone.

`edison/tests/test_edison_duel.py` fails if an Edison duel runs without the preset: the same deck
opens with 6 cards in an EdisonDuel and 5 in a plain Duel.

## Known gaps (not implemented)

| Rule | Why not |
|---|---|
| One manual chain per damage substep | Flag exists (`DUEL_SINGLE_CHAIN_IN_DAMAGE_SUBSTEP`), not tested - not enabled |
| Battle Step replays | Flag exists (`DUEL_STORE_ATTACK_REPLAYS`), not tested - not enabled |
| Paying LP that would make you lose is not allowed | No core flag |
| Hand-size discard: optional triggers can't activate, chaining restricted | No core flag |
| Negated phase triggers re-activate (Lightsworn vs LaDD) | Not tested |
| Black Garden 2010 text | See errata_2010.csv (known_gap) |

## Measured differences (before the preset; tables below are the engine under plain MR5)

| Rule (2010) | Engine today (MR5) | With flag | Flag | Could matter |
|---|---|---|---|---|
| **First Turn Draw**: the player going first draws. | 5 cards at the first Main Phase | 6 | `DUEL_1ST_TURN_DRAW` | **Every game** |
| **Ignition Priority**: after a successful Summon, the turn player may activate an Ignition effect (e.g. Exiled Force, Brionac) before the opponent can respond with, e.g., Trap Hole. | Opponent's Trap Hole window comes first | Turn player's ignition comes first | `DUEL_TCG_FAST_EFFECT_IGNITION` (TCG) or `DUEL_OCG_OBSOLETE_IGNITION`; both pass | Very often: Brionac, Swap Frog, Plaguespreader, Gearframe, Exiled Force in BW-DAD 549, BW 507, Frog 483, LS 372, Machina 250, GB 131 |
| **Early Trigger**: triggers that happened first go on the chain first (Sangan Tributed for Caius: Sangan is CL1). | Caius CL1, Sangan CL2, no prompt | Sangan CL1, Caius CL2 | `DUEL_TCG_SEGOC_FIRSTTRIGGER` | Often: Caius in BW-DAD 468, Frog 396, Machina 157, LS 54; GY triggers (Sangan, Dupe Frog, Plaguespreader, Treeborn) in most Frog, BW-DAD and LS decks |
| **Trigger Locations**: modern "trigger location" rules don't apply. A Sangan banished by D.D. Crow before its effect activates still activates. | Does not activate | Activates | Remove `DUEL_TRIGGER_ONLY_IN_LOCATION` (it is part of MR5) | Sometimes: D.D. Crow (main or side) in BW-DAD 480, BW 466, Frog 349, LS 310, Machina 199, GB 94, against GY triggers |
| **Single Field Spell**: only one face-up Field Spell on the whole field; a new one destroys the old, whoever controls it. | Opponent's Yami survives our Sogen | Yami destroyed | `DUEL_1_FACEUP_FIELD` | Rarely: 68 of 2,353 decks run a field spell (by card: Geartown 48, Mausoleum 36, Zombie World 33, Ancient Forest 17, Venom Swamp 15, Necrovalley 10) |
| **Changing Control**: you can't change the position of a monster in the turn *you* Summoned it. One the opponent Summoned and you took (Brain Control) may be repositioned. | Not allowed | Allowed | `DUEL_CAN_REPOS_IF_NON_SUMPLAYER` | Rarely: needs a steal of a monster the opponent Summoned that turn. Brain/Mind Control in BW-DAD 500, BW 505, Frog 433, Machina 212, LS 76 |
| **Zero-ATK monsters** destroy each other by battle. | Neither destroyed | Both destroyed | `DUEL_0_ATK_DESTROYED` | Rarely: needs a 0-ATK monster attacking another. 0-ATK monsters (e.g. Plaguespreader) are in most decks, but such attacks are unusual |
| **Paying Life Points**: you can't pay LP if it would make you lose. | Brain Control offered at exactly 800 LP (payable) | — | **No flag in the core** | Rarely: LP exactly at or below a cost (Brain Control 800, Premature Burial 800, Mausoleum 1000/2000) |
| **End-of-turn discard**: a card discarded for hand size can't use its optional trigger; only negation, Counter Traps and mandatory effects may chain. | Peten the Dark Clown's effect **is** offered after a hand-size discard | — | **No flag in the core** | Rarely: needs 7+ cards and such a card. Dupe Frog in 467 Frog decks is the realistic case |

## Already correct

| Rule (2010) | Engine today |
|---|---|
| **Phase Triggers**: two phase triggers (e.g. two Lightsworn End Phase mills) don't chain to each other. | Both Lylas activate, each in its own chain (longest chain 1). Matters for LS 372 and GB 188 (tag-outs) |
| **Union Monsters are Summoned in Attack Position** from the equipped state. | Official Gearframe script asks for a position; our Edison override (`oldequip`) Summons it in ATK. |
| **Conjunctions / Quickdraw "and"** (send and Summon simultaneously) | Covered by the Quickdraw override (errata work) |

## Not tested (why)

- **Damage Step activation list, and one manual chain per damage substep.** The first mostly matches
  modern rules. The second has a flag (`DUEL_SINGLE_CHAIN_IN_DAMAGE_SUBSTEP`), but needs a scenario
  with two manual chains in one substep. Not built yet.
- **Battle Step replays.** Descriptive; the core has `DUEL_STORE_ATTACK_REPLAYS`. Not built.
- **Negated phase triggers re-activate** (Lightsworn vs Light and Darkness Dragon). Needs a
  multi-turn negation loop. Not built.
- **Missing the Timing**: same rule in modern. **Both/Those/Them, Does-it-target, Priority, FAQ,
  Major/Minor Rulings index pages**: card-text reading guides, not engine rules.
- **Gemini, Prohibition, Ryko, Machina Force**: card-specific rulings. Ryko is covered by its
  "(Pre-Errata)" card. Prohibition isn't in the six decks.

## Other old-rule flags in the core, not in the compendium

EDOPro's GOAT preset also sets `DUEL_USE_TRAPS_IN_NEW_CHAIN`, `DUEL_6_STEP_BATLLE_STEP`,
`DUEL_TRIGGER_WHEN_PRIVATE_KNOWLEDGE`, `DUEL_EQUIP_NOT_SENT_IF_MISSING_TARGET` and
`DUEL_TCG_SEGOC_NONPUBLIC`. None was checked against a 2010 source here.

## Union Monsters in the six decks

| Union | Decks |
|---|---|
| Machina Gearframe | Machina 250, Frog 4, BW-DAD 1 (old-Union override in place) |
| Machina Peacekeeper | Machina 17. Old-Union override in `edison/scripts/c78349103.lua` (same one-argument change as Gearframe), tested in `test_errata_2010.py`. |

No other Union Monster appears in these decks.
