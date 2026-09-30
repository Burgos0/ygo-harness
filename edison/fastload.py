"""Speed for many short-lived duels: scripts compiled once, card rows read once.

    from edison.fastload import CompiledScripts, CachedCardDB
    scripts = CompiledScripts(EdisonScriptProvider(), lib)
    Duel(seed, lib=lib, carddb=CachedCardDB(), scripts=scripts)

A pilot builds thousands of duels per game (lookahead copies, response forks), and each one used to
re-read and re-*compile* every Lua script it touched - utility.lua and its procedures for every duel,
then each card's script. That was ~40% of all time. `CompiledScripts` hands the core precompiled
bytecode instead (luaL_loadbuffer accepts binary chunks), compiled by the core's *own* Lua via
string.dump inside a scratch duel, so the bytecode format is exactly the one the core reads - a
system luac (5.4.9 here vs the core's 5.4.8) is not guaranteed to be. Each chunk keeps the chunk name
the core would have used, so error messages are unchanged. Nothing here changes what a duel does:
the same scripts run, only parsing is skipped.
"""
from __future__ import annotations

from engine.carddb import CardDB


class CompiledScripts:
    """A script provider returning bytecode for what `inner` returns as source."""

    def __init__(self, inner, lib):
        self.inner, self.lib = inner, lib
        self.cache: dict[str, bytes | None] = {}
        self._compiler = None

    def __getattr__(self, attr):            # search_dirs etc. stay the inner provider's
        return getattr(self.inner, attr)

    def source(self, name) -> bytes | None:
        """The script's source text, for anything that reads scripts rather than runs them."""
        return self.inner.read(name)

    def read(self, name) -> bytes | None:
        key = name.decode() if isinstance(name, bytes) else name
        if key not in self.cache:
            src = self.inner.read(key)
            self.cache[key] = None if src is None else self._compile(src, key)
        return self.cache[key]

    def _compile(self, src: bytes, chunkname: str) -> bytes:
        from engine.duel import Duel
        if self._compiler is None:
            # A scratch duel whose only use is its Lua state: no globals, no cards.
            self._compiler = Duel((1, 2, 3, 4), lib=self.lib, scripts=self.inner, load_globals=False)
        d = self._compiler
        level = 1
        while f"]{'=' * level}]".encode() in src:
            level += 1
        eq = "=" * level
        lua = (f"local f = assert(load([{eq}[\n".encode() + src + f"]{eq}], {chunkname!r}))\n".encode()
               + b"Debug.Message((string.dump(f):gsub('.', function(c) return string.format('%02x', c:byte()) end)))")
        d.log.clear()
        if not self.lib.OCG_LoadScript(d.handle, lua, len(lua), b"compile.lua") or not d.log:
            return src                       # could not compile here: let the core compile it as before
        hexed = d.log[-1].split("] ", 1)[1]
        return bytes.fromhex(hexed)


class CachedCardDB(CardDB):
    """CardDB with row lookups cached (the database is read-only for a run)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._rows: dict[int, tuple | None] = {}

    def row(self, code: int):
        if code not in self._rows:
            self._rows[code] = super().row(code)
        return self._rows[code]
