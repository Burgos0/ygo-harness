"""Is TopDeck.gg decklist coverage for Edison even across event sizes? (data: https://topdeck.gg)

    python -m edison.topdeck.coverage       # needs the fetch cache (edison/.cache/topdeck)

Coverage = standings with a usable decklist (deckObj or text) / all standings. Reported per
event-size bucket (players in the event), with how many events in the bucket publish all, some or
no lists - coverage is usually an event-level choice (organizer shows decks or not), not a player one.
Writes coverage.md.
"""
from __future__ import annotations

from pathlib import Path

from edison.topdeck.decklists import form_of
from edison.topdeck.fetch import load_all

HERE = Path(__file__).resolve().parent
BUCKETS = [(1, 15), (16, 31), (32, 63), (64, 127), (128, 10**6)]


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return cov / (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5


def main() -> int:
    events, _ = load_all()
    per = []
    for e in events:
        st = e.get("standings", [])
        if not st:
            continue
        have = sum(form_of(s) in ("deckObj", "text") for s in st)
        per.append((len(st), have))
    total_players = sum(n for n, _ in per)
    total_have = sum(h for _, h in per)
    lines = ["# Edison decklist coverage by event size (TopDeck.gg)", "",
             "Data provided by [TopDeck.gg](https://topdeck.gg). Coverage = standings with a decklist / all standings.", "",
             "| Event size (players) | Events | Players | With list | Coverage | Events: all / some / none |",
             "|---|---|---|---|---|---|"]
    for lo, hi in BUCKETS:
        b = [(n, h) for n, h in per if lo <= n <= hi]
        if not b:
            continue
        n, h = sum(x for x, _ in b), sum(y for _, y in b)
        full = sum(1 for x, y in b if y == x)
        none = sum(1 for _, y in b if y == 0)
        label = f"{lo}-{hi}" if hi < 10**6 else f"{lo}+"
        lines.append(f"| {label} | {len(b)} | {n} | {h} | {100 * h / n:.1f}% | {full} / {len(b) - full - none} / {none} |")
    rho = spearman([n for n, _ in per], [h / n for n, h in per])
    mean_event = sum(h / n for n, h in per) / len(per)
    lines += ["", f"Overall: {total_have}/{total_players} = {100 * total_have / total_players:.1f}% of players; "
                  f"mean per-event coverage {100 * mean_event:.1f}% over {len(per)} events.",
              f"Spearman rank correlation, event size vs coverage: {rho:+.2f}.", ""]
    # Where the matchup data (matches with both decklists) comes from, by the same buckets.
    import csv
    size = {e["TID"]: len(e.get("standings", [])) for e in events}
    used = [size.get(r["tid"], 0) for r in csv.DictReader(open(HERE / "matches.csv")) if r["both_decklists"] == "True"]
    if used:
        parts = []
        for lo, hi in BUCKETS:
            k = sum(lo <= n <= hi for n in used)
            parts.append(f"{f'{lo}-{hi}' if hi < 10**6 else f'{lo}+'}: {k} ({100 * k / len(used):.0f}%)")
        lines += [f"Matches with both decklists (the matchup data), by event size: " + ", ".join(parts) + ".",
                  "The matchup matrix therefore describes the large-event meta, not local play.", ""]
    (HERE / "coverage.md").write_text("\n".join(lines))
    print("\n".join(lines[4:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
