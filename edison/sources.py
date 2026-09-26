"""Edison format source data, fetched and cached (never committed).

Source of truth is edisonformat.net. Its deckbuilder and card search load the card pool
from /data/json/EdisonCards.json; its banlist page (/rules/banlist) embeds the March 2010
list in /rules/banlist.js. YGOPRODeck is only a cross-check. Raw downloads carry Konami card
text, so like BabelCDB/CardScripts they are cached locally (edison/.cache, gitignored) and
only derived id/name/status data is committed.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"

EDISON_CARDS = "https://edisonformat.net/data/json/EdisonCards.json"
EDISON_BANLIST_JS = "https://edisonformat.net/rules/banlist.js"
YGOPRODECK_CARDS = "https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes"
YGOPRODECK_SETS = "https://db.ygoprodeck.com/api/v7/cardsets.php"

#: edisonformat.net/rules/banlist: "Cards up to and including the release of Duelist Pack: Kaiba
#: are legal." The date is looked up from YGOPRODeck's set list, not hardcoded.
CUTOFF_SET = "Duelist Pack: Kaiba"


def fetch(url: str, name: str, refresh: bool = False) -> bytes:
    path = CACHE / name
    if refresh or not path.exists():
        CACHE.mkdir(exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "ygo-harness/edison"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    return path.read_bytes()


def edison_cards(refresh: bool = False) -> list[dict]:
    return json.loads(fetch(EDISON_CARDS, "EdisonCards.json", refresh))


def edison_banlist(refresh: bool = False) -> dict[str, int]:
    """Card name -> copies allowed (0/1/2), from the `ban`/`lim`/`sem` arrays in banlist.js."""
    js = fetch(EDISON_BANLIST_JS, "banlist.js", refresh).decode()
    dec, out = json.JSONDecoder(), {}
    for var in ("ban", "lim", "sem"):
        marker = f"const {var} ="
        rest = js[js.index(marker) + len(marker):].lstrip()
        for entry in dec.raw_decode(rest)[0]:
            # one semi-limited entry spells the key "status"
            out[entry["Name"]] = int(entry.get("Status", entry.get("status")))
    return out


def ygoprodeck_cards(refresh: bool = False) -> list[dict]:
    return json.loads(fetch(YGOPRODECK_CARDS, "ygoprodeck_cards.json", refresh))["data"]


def cutoff_date(refresh: bool = False) -> str:
    sets = json.loads(fetch(YGOPRODECK_SETS, "ygoprodeck_sets.json", refresh))
    (date,) = {s["tcg_date"] for s in sets if s["set_name"] == CUTOFF_SET}
    return date
