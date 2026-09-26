"""Edison tournament data from TopDeck.gg -> derived CSVs + a short report.

    python -m edison.topdeck.fetch      # once: fills edison/.cache/topdeck (needs TOPDECK_API_KEY)
    python -m edison.topdeck.analyze

Data provided by TopDeck.gg (https://topdeck.gg).

Writes (derived only - no card text, no player names; players are pseudonymous keys,
sha256 of the TopDeck player id, stable across events):
  decks.csv                one row per standing with a decklist: event, player, form, legality,
                           violations, proposed archetype, and the canonical passcodes
  matches.csv              completed 1v1 matches: players, result (p1/p2/draw), game score
  archetypes_proposed.md   PROPOSED archetype groupings with defining cards and deck counts
"""
from __future__ import annotations

import csv
import hashlib
import time
from collections import Counter, defaultdict
from pathlib import Path

from edison.topdeck.archetypes import PROPOSED, classify
from edison.topdeck.decklists import parse
from edison.topdeck.fetch import load_all

HERE = Path(__file__).resolve().parent


def pkey(player_id: str) -> str:
    return hashlib.sha256(str(player_id).encode()).hexdigest()[:12]


def packed(codes: list[int]) -> str:
    return " ".join(f"{c}x{n}" for c, n in sorted(Counter(codes).items()))


def main() -> int:
    from engine.carddb import CardDB
    db = CardDB()
    events, teams = load_all()

    forms, rules, reasons = Counter(), Counter(), Counter()
    deck_of: dict[tuple[str, str], object] = {}
    arche_decks: dict[str, list] = defaultdict(list)
    players = set()
    ok = fail = 0
    with open(HERE / "decks.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tid", "date", "player", "form", "legal", "violations", "archetype_proposed",
                    "main", "extra", "side"])
        for e in events:
            date = time.strftime("%Y-%m-%d", time.gmtime(e.get("startDate") or 0))
            for s in e.get("standings", []):
                players.add(s.get("id"))
                form, deck, violations = parse(s)
                forms[form] += 1
                if deck is None:
                    continue
                if violations:
                    fail += 1
                    for v in violations:
                        rules[v.rule] += 1
                        reasons[f"{v.rule}: {v.card}"] += 1
                else:
                    ok += 1
                deck_of[(e["TID"], s.get("id"))] = deck
                names = Counter(db.name(c) for c in deck.main + deck.extra)
                archetype = classify(names)
                arche_decks[archetype].append(deck)
                w.writerow([e["TID"], date, pkey(s.get("id")), form, not violations,
                            "; ".join(f"{v.rule}: {v.card}" for v in violations), archetype,
                            packed(deck.main), packed(deck.extra), packed(deck.side)])

    m = Counter()
    with open(HERE / "matches.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tid", "round", "table", "p1", "p2", "result", "winner_games", "loser_games",
                    "both_decklists"])
        for e in events:
            name_of = {s.get("id"): s.get("name") for s in e.get("standings", [])}
            for r in e.get("rounds") or []:
                for t in r.get("tables") or []:
                    ps = t.get("players") or []
                    if t.get("table") == "Byes" or len(ps) != 2:
                        continue
                    if t.get("status") != "Completed":
                        m["not_completed"] += 1
                        continue
                    a, b = ps[0].get("id"), ps[1].get("id")
                    win = t.get("winner_id")
                    if win is None and t.get("winner"):
                        # Some completed tables carry the winner by name only (winner_id null). Map the
                        # name to one of the two seated players via the event's standings, if unambiguous.
                        hits = [p for p in (a, b) if name_of.get(p) == t["winner"]]
                        if len(hits) == 1:
                            win = hits[0]
                            m["winner_by_name"] += 1
                    result = "draw" if win == "Draw" else "p1" if win == a else "p2" if win == b else "unknown"
                    both = (e["TID"], a) in deck_of and (e["TID"], b) in deck_of
                    scored = t.get("winner_games") is not None and t.get("loser_games") is not None
                    m["completed"] += 1
                    m["draws"] += result == "draw"
                    m["unknown_result"] += result == "unknown"
                    if both:
                        m["both"] += 1
                        m["both_scored" if scored else "both_unscored"] += 1
                    w.writerow([e["TID"], r.get("round"), t.get("table"), pkey(a), pkey(b), result,
                                t.get("winner_games"), t.get("loser_games"), both])

    total = sum(len(v) for v in arche_decks.values())
    lines = ["# Edison archetypes - PROPOSED, not final", "",
             "Data provided by [TopDeck.gg](https://topdeck.gg). Rules: `edison/topdeck/archetypes.py`",
             "(first matching rule wins). Defining cards = cards whose share of decks in the group most exceeds",
             "their share across all decks (so format staples drop out), shown as group% vs all%.", "",
             "| Proposed archetype | Decks | Rule (signature cards, how many needed) | Defining cards (share of decks) |",
             "|---|---|---|---|"]
    rule_of = {a: (sig, need) for a, sig, need in PROPOSED}
    overall = Counter(db.name(c) for ds in arche_decks.values() for d in ds for c in set(d.main + d.extra))
    for archetype, decks in sorted(arche_decks.items(), key=lambda kv: -len(kv[1])):
        share = Counter(db.name(c) for d in decks for c in set(d.main + d.extra))
        lift = sorted(share, key=lambda n: share[n] / len(decks) - overall[n] / total, reverse=True)[:6]
        top = ", ".join(f"{n} {100 * share[n] // len(decks)}% vs {100 * overall[n] // total}%" for n in lift)
        sig, need = rule_of.get(archetype, ([], 0))
        rule = f"{need} of: " + ", ".join(c for c, _ in sig) if sig else "no rule matched"
        lines.append(f"| {archetype} | {len(decks)} | {rule} | {top} |")
    lines += ["", f"{total} decks classified from {len(events)} events."]
    (HERE / "archetypes_proposed.md").write_text("\n".join(lines) + "\n")

    print(f"events {len(events)} (team events skipped {teams}); players {len(players)} unique; "
          f"standings {sum(forms.values())}")
    print(f"decklists by form {dict(forms)}")
    print(f"deck.py: load {ok}, fail {fail}; violations by rule {dict(rules)}; top {reasons.most_common(5)}")
    print(f"1v1 completed matches {m['completed']} (draws {m['draws']}, winner resolved by name "
          f"{m['winner_by_name']}, unknown result {m['unknown_result']}); "
          f"both decklists {m['both']} = with game score {m['both_scored']} + without {m['both_unscored']}")
    print("archetypes (proposed): " + ", ".join(f"{a} {len(d)}" for a, d in
                                                  sorted(arche_decks.items(), key=lambda kv: -len(kv[1]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
