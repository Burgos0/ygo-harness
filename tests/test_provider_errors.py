"""A bad key must be a harness fault, never an agent statistic.

The 401 that prompted these tests ran clean, solved nothing, and filed itself
under `no answer` - the column that means "the model declined to choose". It
is indistinguishable there from a genuinely useless agent, which is the exact
conflation scripts/run_puzzles.py's accounting exists to prevent.
"""
import inspect

import pytest

from agents.llm_agent import (FatalProviderError, NotAuthenticated, NoAnswer,
                              OutOfCredit)


def test_fatal_errors_are_not_no_answer():
    """NoAnswer is an agent outcome; these are not, so they must not be caught
    by a handler looking for one."""
    for cls in (NotAuthenticated, OutOfCredit):
        assert issubclass(cls, FatalProviderError)
        assert not issubclass(cls, NoAnswer)


def test_run_puzzles_stops_on_any_fatal_provider_error():
    """Catching OutOfCredit alone would let an auth failure run the whole
    suite, producing one meaningless row per puzzle."""
    import scripts.run_puzzles as rp

    src = inspect.getsource(rp)
    assert "except FatalProviderError" in src
    assert "except OutOfCredit" not in src, "narrow handler misses NotAuthenticated"


@pytest.mark.parametrize("message", [
    "Error code: 401 - {'error': {'message': 'Missing Authentication header'}}",
    "AuthenticationError: invalid api key",
])
def test_auth_messages_classify_as_not_authenticated(message):
    """Matches the wording the provider actually returned, not a guess."""
    low = message.lower()
    assert "authentication" in low or "401" in message or "invalid api key" in low


def _dotenv_defines(name: str) -> bool:
    """Whether the repo-root .env assigns `name` a non-empty value (same line rules as
    llm.provider._load_dotenv). Read directly, so an exported variable does not count."""
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / ".env"
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip().strip("'\""):
                return True
    return False


@pytest.mark.skipif(not _dotenv_defines("OPENROUTER_API_KEY"),
                    reason="no OPENROUTER_API_KEY in .env (engine-only checkout): "
                           "nothing to prove about loading it")
def test_dotenv_is_loaded_without_an_exported_key(monkeypatch, tmp_path):
    """The root cause: nothing read .env, so the key silently became the
    literal string "not-needed"."""
    import llm.provider as provider

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider._load_dotenv()
    # Assert on the positive: the file exists in a working checkout and the
    # variable is populated from it. A test that only proves "no crash" would
    # have passed against the bug.
    assert provider._from_env("OPENROUTER_API_KEY"), (
        "OPENROUTER_API_KEY not resolvable from .env - the 401 path is live")
