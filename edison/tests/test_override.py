"""An override script in edison/scripts must win over the official CardScripts file."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.carddb import CardDB, ScriptProvider
from engine.deck import Deck
from engine.duel import Duel
from engine.ocgapi import load
from edison.provider import OVERRIDES, EdisonScriptProvider

DECK = ROOT / "data" / "decks" / "sky_striker_pulp6.ydk"
ENGAGE = 63166095  # Sky Striker Mobilize - Engage!, 3 copies in the deck
MARKER = "EDISON-OVERRIDE-LOADED"


def _start_duel(scripts) -> list[str]:
    """Create a duel (every deck card's script is loaded at creation) and return the core log."""
    deck = Deck.from_ydk(DECK)
    with Duel((1, 7, 13, 29), lib=load(), carddb=CardDB(), scripts=scripts) as d:
        d.load_deck(0, deck.main, deck.extra, shuffle_seed=1)
        d.load_deck(1, deck.main, deck.extra, shuffle_seed=2)
        d.start()
        return list(d.log)


def test_override_script_wins(tmp_path):
    (tmp_path / f"c{ENGAGE}.lua").write_text(
        "local s,id=GetID()\n"
        "function s.initial_effect(c)\n"
        f'  Debug.Message("{MARKER} "..id)\n'
        "end\n")
    sp = EdisonScriptProvider(overrides=tmp_path)
    assert sp.read(f"c{ENGAGE}.lua") == (tmp_path / f"c{ENGAGE}.lua").read_bytes()

    log = _start_duel(sp)
    assert any(f"{MARKER} {ENGAGE}" in line for line in log), "the core did not run the override script"
    # Control: the official script is what runs without the override.
    assert not any(MARKER in line for line in _start_duel(ScriptProvider()))


def test_default_override_folder_is_searched_first():
    sp = EdisonScriptProvider()
    assert sp.search_dirs[0] == OVERRIDES
    # A card with no override still resolves to the official script.
    assert sp.read(f"c{ENGAGE}.lua") == ScriptProvider().read(f"c{ENGAGE}.lua") is not None
