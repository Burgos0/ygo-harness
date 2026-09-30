"""One Edison duel between two policies, reproducible from its key; shared by pilot_eval and matchup.

    from edison.pilots import init, play
    init()                                       # once per process
    r = play(key=7, specs=("lightsworn", "random"), decks=("lightsworn", "lightsworn"))

A spec is a profile name from agents.profiles.PROFILES or "random" (random-legal). specs[0] sits in seat 0,
which goes first. A duel with key k uses engine seeds (k+1, k+7, k+13, k+29) and deck shuffles k / k+500,
so (key, specs, decks) replays it exactly. Every rejected answer (MSG_RETRY) is traced to its side.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EDOPRO_REPLAYS = Path("/Applications/ProjectIgnis/replay")
_ctx: dict = {}


def init():
    from engine.carddb import CardDB
    from engine.ocgapi import load
    _ctx.update(lib=load(), db=CardDB(), decks={})


def deck(name: str):
    """A deck by profile name (its .ydk), loaded once per process."""
    from agents.profiles import PROFILES
    from edison.deck import load_ydk
    if name not in _ctx["decks"]:
        _ctx["decks"][name] = load_ydk(ROOT / PROFILES[name].deck)
    return _ctx["decks"][name]


class Traced:
    """Wraps a policy: a decision handed back unchanged means the previous answer to it was rejected."""

    def __init__(self, inner, side, log):
        self.inner, self.side, self.log, self.last = inner, side, log, None

    def attach(self, duel):
        if hasattr(self.inner, "attach"):
            self.inner.attach(duel)

    def __call__(self, msg, duel):
        if msg is not None and self.last is not None and msg is self.last:
            self.log.append((self.side, msg.id))
        r = self.inner(msg, duel)
        self.last = msg
        return r


def label(spec: str) -> str:
    from agents.profiles import PROFILES
    return "random-legal" if spec == "random" else f"{PROFILES[spec].name} pilot"


def _policy(spec: str, seat: int, seed: int):
    from agents.lookahead import LookaheadPilot
    from agents.profiles import PROFILES
    from agents.random_legal import RandomLegal
    if spec == "random":
        return RandomLegal(seed=seed)
    return LookaheadPilot(PROFILES[spec], seat=seat, seed=seed, lib=_ctx["lib"], carddb=_ctx["db"])


def win_reason(messages) -> int:
    from engine.constants import MSG_WIN
    wins = [m for m in messages if m.id == MSG_WIN]
    return wins[-1].payload[1] if wins else -1


def play(key: int, specs: tuple[str, str], decks: tuple[str, str], export: bool = False) -> dict:
    from edison.duel import EdisonDuel
    rejected: list = []
    pols = [Traced(_policy(specs[s], s, key), s, rejected) for s in (0, 1)]
    seeds = (key + 1, key + 7, key + 13, key + 29)
    t = time.perf_counter()
    with EdisonDuel(seeds, lib=_ctx["lib"], carddb=_ctx["db"]) as d:
        for s in (0, 1):
            dk = deck(decks[s])
            d.load_deck(s, dk.main, dk.extra, shuffle_seed=key + 500 * s)
        for p in pols:
            p.attach(d)
        d.start()
        r = d.run(pols[0], max_steps=300_000, retry_limit=300, policy1=pols[1])
        turns = next((p.inner.turn.number for p in pols if hasattr(p.inner, "turn")), None)
        out = {"key": key, "specs": list(specs), "decks": list(decks), "seeds": list(seeds),
               "shuffles": [key, key + 500], "winner": r["winner"], "reason": win_reason(r["messages"]),
               "turns": turns, "steps": r["steps"], "retries": r["retries"], "rejected": rejected,
               "seconds": time.perf_counter() - t}
        if export:
            from viz.replay import build_yrp
            out["yrp"] = build_yrp(seed=seeds, decks=d.dealt, responses=d.responses, duel_flags=d.flags,
                                   names=(label(specs[0]), label(specs[1])), start_lp=d.starting_lp,
                                   start_hand=d.starting_draw, draw_count=d.draw_per_turn)
    return out


def export_replay(r: dict, path: Path, edopro_subdir: str | None = None) -> tuple[bool, Path | None]:
    """Write r["yrp"] to path, verify it in EDOPro's own engine, copy it to EDOPro's replay folder."""
    import shutil
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r["yrp"])
    # EDOPro here is the system-wide install; verify_yrp's default is the per-user one (~/Applications).
    edo = ["--edopro", str(EDOPRO_REPLAYS.parent)] if EDOPRO_REPLAYS.is_dir() else []
    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_yrp.py"), *edo, str(path)],
                       capture_output=True, text=True)
    ok = "reproduces in EDOPro" in v.stdout
    if not ok:
        print(f"  {path.name}: NOT verified - {(v.stdout.strip() or v.stderr.strip()).splitlines()[-1:]}")
    dest = None
    if edopro_subdir and EDOPRO_REPLAYS.is_dir():
        (EDOPRO_REPLAYS / edopro_subdir).mkdir(exist_ok=True)
        dest = EDOPRO_REPLAYS / edopro_subdir / path.name
        shutil.copy(path, dest)
    return ok, dest


class Progress:
    """done/total, duels/sec, ETA - every `every` items."""

    def __init__(self, total: int, every: int = 50, unit: str = "duels"):
        self.total, self.every, self.unit, self.t = total, every, unit, time.perf_counter()

    def __call__(self, done: int, extra: str = "") -> None:
        if done % self.every and done != self.total:
            return
        el = time.perf_counter() - self.t
        rate = done / el if el else 0.0
        eta = (self.total - done) / rate if rate else 0.0
        print(f"  {done}/{self.total} {self.unit}, {rate:.2f} {self.unit}/s, {el:.0f}s elapsed, ETA {eta:.0f}s"
              + (f" | {extra}" if extra else ""), flush=True)
