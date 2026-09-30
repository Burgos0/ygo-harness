"""Audit: which prompts do the pilots leave to the random-legal fallback?

    python -m edison.fallback_audit            # reruns the three reference runs on their seeds

Reruns (observing only - wrappers count, they never change an answer) the last Lightsworn vs
Blackwing-DAD matchup and both vs-random checkpoints, and counts every prompt a pilot's Rules passed to
RandomLegal: by deck, where it was answered (the real duel, a lookahead copy, a response fork), prompt
type, and the card whose effect or summon asked it (the top of the current chain, else the pilot's own
last action). Checks each rerun matches its logged games.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
COUNTS: Counter = Counter()


def _patch():
    import struct
    from agents import lookahead as L
    from edison import pilots
    from engine.constants import MSG_CHAIN_END, MSG_CHAINING, MSG_NAMES

    pilots.init()

    class Counting:
        def __init__(self, inner, rules):
            self.inner, self.rules = inner, rules

        def __call__(self, msg, duel):
            r = self.rules
            if msg is not None:
                ctx = getattr(r, "context", None)
                card = ctx() if ctx else "?"
                COUNTS[(r.profile.name, getattr(r, "where", "?"), MSG_NAMES.get(msg.id, str(msg.id)), card)] += 1
            return self.inner(msg, duel)

        def __getattr__(self, a):
            return getattr(self.inner, a)

    orig_rules = L.Rules.__init__

    def rules_init(self, *a, **kw):
        orig_rules(self, *a, **kw)
        self.fallback = Counting(self.fallback, self)
    L.Rules.__init__ = rules_init

    db = pilots._ctx["db"]
    orig_pilot = L.LookaheadPilot.__init__

    def pilot_init(self, *a, **kw):
        orig_pilot(self, *a, **kw)
        self.rules.where = "real"
        self._chain, self._last = [], None
        self.rules.context = lambda: db.name(self._chain[-1]) if self._chain else (
            db.name(self._last) if self._last else "-")
    L.LookaheadPilot.__init__ = pilot_init

    orig_hook = L.LookaheadPilot._hook

    def hook(self, duel):
        fresh = self._hooked is not duel
        orig_hook(self, duel)
        if fresh:
            inner = duel._messages

            def tap():
                batch = inner()
                for m in batch:
                    if m.id == MSG_CHAINING:
                        self._chain.append(struct.unpack_from("<I", m.payload, 0)[0])
                    elif m.id == MSG_CHAIN_END:
                        self._chain.clear()
                return batch
            duel._messages = tap
    L.LookaheadPilot._hook = hook

    orig_remember = L.LookaheadPilot._remember

    def remember(self, response, idle, battle):
        v = struct.unpack("<i", response)[0]
        k, i = v & 0xFFFF, v >> 16
        # IDLE_SUMMON 0, SPSUMMON 1, REPOSITION 2, MSET 3, SSET 4, ACTIVATE 5; BATTLE_ACTIVATE 0, ATTACK 1
        lists = ([idle.summonable, idle.spsummonable, idle.repositionable, idle.msetable, idle.ssetable,
                  idle.activatable]
                 if idle is not None else [battle.activatable, battle.attackable] if battle is not None else [])
        if k < len(lists) and lists[k] and i < len(lists[k]):
            self._last = lists[k][i].code
        return orig_remember(self, response, idle, battle)
    L.LookaheadPilot._remember = remember

    for cls, where in ((L._Rollout, "copy"), (L.Fork, "fork")):
        orig = cls.__init__

        def init(self, *a, _orig=orig, _where=where, **kw):
            _orig(self, *a, **kw)
            self.rules.where = _where
            self.rules.context = lambda: _where
        cls.__init__ = init

    orig_play = pilots.play

    def play(*a, **kw):
        COUNTS.clear()
        r = orig_play(*a, **kw)
        r["audit_fallbacks"] = [list(k) + [v] for k, v in COUNTS.items()]
        return r
    pilots.play = play


def _vs_random(args):
    i, profile = args
    from edison import pilots
    specs = (profile, "random") if i % 2 == 0 else ("random", profile)
    r = pilots.play(i, specs, (profile, profile))
    return {"kind": f"{profile} vs random", "i": i, "winner": r["winner"], "turns": r["turns"],
            "fallbacks": r["audit_fallbacks"]}


def _match(m):
    from edison import pilots
    from edison.matchup import play_match
    import edison.matchup as M
    got = []
    orig = pilots.play

    def spy(*a, **kw):
        r = orig(*a, **kw)
        got.append(r["audit_fallbacks"])
        return r
    M.pilots.play = spy
    try:
        res = play_match(m, "lightsworn", "blackwing_dad")
    finally:
        M.pilots.play = orig
    return {"kind": "matchup", "i": m, "winners": [g["winner"] for g in res["games"]],
            "turns": [g["turns"] for g in res["games"]], "fallbacks": [x for f in got for x in f],
            "games": len(res["games"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duels", type=int, default=200)
    ap.add_argument("--matches", type=int, default=200)
    ap.add_argument("--matchup-log", default="runs/matchup-lightsworn-vs-blackwing_dad-round2/matches.jsonl")
    ap.add_argument("--random-logs", nargs=2, default=["runs/lightsworn-v8-round2/duels.jsonl",
                                                       "runs/blackwing_dad-v5-round2/duels.jsonl"])
    ap.add_argument("--out", default="runs/fallback-audit/results.jsonl")
    args = ap.parse_args()
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    jobs = ([(_vs_random, (i, p)) for p in ("lightsworn", "blackwing_dad") for i in range(args.duels)]
            + [(_match, m) for m in range(args.matches)])
    t, results = time.perf_counter(), []
    from edison.pool import worker_pool
    with worker_pool(mp.cpu_count(), initializer=_patch) as pool, \
            open(out, "w") as log:
        futs = [pool.submit(f, a) for f, a in jobs]
        for n, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.append(r)
            log.write(json.dumps(r) + "\n")
            if n % 50 == 0 or n == len(jobs):
                el = time.perf_counter() - t
                print(f"  {n}/{len(jobs)} jobs, {n / el:.2f}/s, ETA {el / n * (len(jobs) - n):.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
