"""The Lightsworn pilot: the generic lookahead pilot with the Lightsworn profile.

Kept so existing imports (`from agents.lightsworn import LightswornPilot`) keep working.
"""
from __future__ import annotations

from agents.lookahead import FILLER, PLACEHOLDER, LookaheadPilot  # noqa: F401
from agents.profiles import LIGHTSWORN


class LightswornPilot(LookaheadPilot):
    def __init__(self, seat: int, seed: int = 0, **kwargs):
        super().__init__(LIGHTSWORN, seat, seed, **kwargs)
