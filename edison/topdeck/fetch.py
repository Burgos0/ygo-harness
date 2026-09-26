"""Pull Edison tournaments from the TopDeck.gg API (v2) into a local, gitignored cache.

    python -m edison.topdeck.fetch [--days 365] [--refresh]

Data provided by TopDeck.gg (https://topdeck.gg) - see README.md.

API key: TOPDECK_API_KEY in the repo-root .env (gitignored) or the environment. Never committed.
Request (POST /api/v2/tournaments, docs: https://topdeck.gg/docs/tournaments-v2):
  game "Yu-Gi-Oh", format "Edison" (both case-sensitive), a date window,
  columns id/name/decklist/wins/draws/losses (decklist also returns deckObj when structured data
  exists), rounds with tables table/players/winner/status and players ["id"] only - decklists are
  taken from standings, keyed by player id.
The whole range is tried as one call first; if the server refuses it (timeout / 5xx / 413) the range
is split into halves recursively. A 429 waits for Retry-After (header, else retryAfterSeconds).
Raw responses go to edison/.cache/topdeck/<start>-<end>.json; only derived data is committed.
The key is never printed or written: errors are raised `from None` (no chained request objects in
tracebacks) with the key scrubbed from any server text, and caches hold response bodies only.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "edison" / ".cache" / "topdeck"
URL = "https://topdeck.gg/api/v2/tournaments"
DAY = 86400
MIN_WINDOW = 7 * DAY


def api_key() -> str:
    key = os.environ.get("TOPDECK_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            name, _, value = line.strip().partition("=")
            if name.strip() == "TOPDECK_API_KEY":
                key = value.strip().strip("'\"")
    if not key:
        raise SystemExit("TOPDECK_API_KEY not set: add TOPDECK_API_KEY=... to .env (gitignored)")
    return key


class TooHeavy(Exception):
    pass


def post(body: dict, key: str) -> list:
    data = json.dumps(body).encode()
    while True:
        req = urllib.request.Request(URL, data=data, method="POST", headers={
            "Authorization": key, "Content-Type": "application/json", "User-Agent": "ygo-harness/edison"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                payload = {}
                try:
                    payload = json.loads(e.read() or b"{}")
                except ValueError:
                    pass
                wait = int(e.headers.get("Retry-After") or payload.get("retryAfterSeconds") or 60)
                print(f"  429: waiting {wait}s", flush=True)
                time.sleep(wait + 1)
                continue
            if e.code in (413, 500, 502, 503, 504):
                raise TooHeavy(f"HTTP {e.code}") from None
            body_text = e.read()[:300].decode(errors="replace").replace(key, "***")
            raise SystemExit(f"TopDeck.gg HTTP {e.code}: {body_text}") from None
        except (TimeoutError, urllib.error.URLError) as e:
            raise TooHeavy(str(e).replace(key, "***")) from None


def window(start: int, end: int, key: str, refresh: bool) -> list:
    path = CACHE / f"{start}-{end}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    body = {"game": "Yu-Gi-Oh", "format": "Edison", "start": start, "end": end,
            "columns": ["id", "name", "decklist", "wins", "draws", "losses"],
            "rounds": True, "tables": ["table", "players", "winner", "status"], "players": ["id"]}
    try:
        events = post(body, key)
    except TooHeavy as e:
        if end - start <= MIN_WINDOW:
            raise SystemExit(f"window {start}-{end} still too heavy ({e})")
        mid = (start + end) // 2
        print(f"  {e}: splitting {time.strftime('%Y-%m-%d', time.gmtime(start))}.."
              f"{time.strftime('%Y-%m-%d', time.gmtime(end))}", flush=True)
        return window(start, mid, key, refresh) + window(mid + 1, end, key, refresh)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events))
    print(f"  {time.strftime('%Y-%m-%d', time.gmtime(start))}..{time.strftime('%Y-%m-%d', time.gmtime(end))}: "
          f"{len(events)} events", flush=True)
    return events


def load_all(days: int = 365, refresh: bool = False) -> tuple[list, int]:
    """(events, team events skipped): every event in the window, de-duplicated by TID."""
    key = api_key()
    end = int(time.time()) // DAY * DAY  # day-aligned so reruns hit the cache
    events = window(end - days * DAY, end, key, refresh)
    seen, out, teams = set(), [], 0
    for e in events:
        if e.get("TID") in seen:
            continue
        seen.add(e.get("TID"))
        if e.get("isTeamEvent"):
            teams += 1
        else:
            out.append(e)
    return out, teams


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    events, teams = load_all(args.days, args.refresh)
    print(f"{len(events)} individual Edison events ({teams} team events skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
