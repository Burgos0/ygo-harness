"""Capture a pilot's chain-window prompts from a recorded game, for tests/test_decisions.py.

    python scripts/capture_positions.py --key 101371 --specs blackwing_dad lightsworn \
        --profile blackwing_dad --turn 14 --out tests/fixtures/decisions/new.json

Replays the game (key and seating as edison.matchup logs them) with the current pilots and records,
at every chain prompt to `--profile`'s pilot on `--turn`, the response log up to that prompt. The
game must reach the same position under the code you run this with: to capture a position from an
older commit, run this from a worktree of that commit (that is how match137_game2_turn14 was made,
from 244cbee). Fill in each window's "summon" and "expect" by hand afterwards.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", type=int, required=True)
    ap.add_argument("--specs", nargs=2, required=True, help="seat 0 and seat 1 profiles")
    ap.add_argument("--profile", required=True, help="whose prompts to capture")
    ap.add_argument("--turn", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    from agents import lookahead as L
    from edison import pilots
    from engine.constants import MSG_SELECT_CHAIN

    pilots.init()
    seat = args.specs.index(args.profile)
    captured: dict = {"windows": []}
    orig = L.LookaheadPilot.__call__

    def call(self, msg, duel):
        if (msg is not None and msg.id == MSG_SELECT_CHAIN and self.me == seat
                and self.turn.number == args.turn and msg.player == seat):
            captured.update(seed=list(duel.seed), dealt=duel.dealt, responses=[r.hex() for r in duel.responses])
            captured["windows"].append({"n": len(duel.responses), "payload": msg.payload.hex(),
                                        "event": self.event, "summon": "?", "expect": "?"})
        return orig(self, msg, duel)
    L.LookaheadPilot.__call__ = call
    pilots.play(args.key, tuple(args.specs), tuple(args.specs))
    if not captured["windows"]:
        print("no chain prompts to that pilot on that turn")
        return 1
    captured.update(seat=seat, profile=args.profile,
                    about=f"key {args.key}, {args.specs[0]} (seat 0) vs {args.specs[1]}, turn {args.turn}")
    args.out.write_text(json.dumps(captured, indent=1))
    print(f"{len(captured['windows'])} prompts -> {args.out}: " + ", ".join(w["event"] for w in captured["windows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
