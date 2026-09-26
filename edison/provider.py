"""Script provider for Edison: edison/scripts/ is searched before the official CardScripts.

    from edison.provider import EdisonScriptProvider
    Duel(seed, lib=lib, carddb=db, scripts=EdisonScriptProvider())

engine.carddb.ScriptProvider resolves a requested script name through `search_dirs`, where
an earlier directory wins. Putting the override folder first is the whole change: official
data stays untouched, and a file missing from edison/scripts falls back to CardScripts.
"""
from __future__ import annotations

from pathlib import Path

from engine.carddb import ScriptProvider

OVERRIDES = Path(__file__).resolve().parent / "scripts"


class EdisonScriptProvider(ScriptProvider):
    def __init__(self, root: Path | None = None, overrides: Path = OVERRIDES):
        super().__init__(root)
        self.overrides = Path(overrides)
        self.search_dirs.insert(0, self.overrides)  # checked first; index is built lazily
