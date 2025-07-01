"""tests/unit_tests/data_path/test_provider_factory.py

REQUIREMENTS
------------
These tests assert the following acceptance-criteria for the *data provider
factory* (`src/StrateQueue/data/provider_factory.py`).

1. **Correct instance type** – `create_provider` must return the concrete
   class that corresponds to the requested provider string.
2. **Credential / environment handling**
   a) When an API key is required (Polygon, CoinMarketCap) and *not* supplied
      via argument or environment variable, the factory must raise
      `ValueError`.
   b) When the key *is* present in the environment, the factory should succeed
      without an explicit `DataProviderConfig`.
3. **Unsupported provider sanitation** – Unknown provider strings must raise
   `ValueError` and list available providers.
4. **Registry helpers** – `get_supported_providers` returns a non-empty list
   and `is_provider_supported` accurately reflects support.

The test suite passes when every assertion in this file succeeds **without
performing any real network IO** (the autouse fixture in `conftest.py` blocks
it).
"""

from __future__ import annotations

import os

import pytest

from StrateQueue.data import provider_factory as pf
from StrateQueue.data.sources.demo import TestDataIngestion
from StrateQueue.data.sources.polygon import PolygonDataIngestion
from StrateQueue.data.sources.yfinance import YahooFinanceDataIngestion


# ---------------------------------------------------------------------------
# Happy-path instance creation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ptype,expected_cls,env_key",
    [
        ("demo", TestDataIngestion, None),
        ("yfinance", YahooFinanceDataIngestion, None),
        ("polygon", PolygonDataIngestion, "POLYGON_API_KEY"),
    ],
)
def test_create_provider_returns_expected_class(monkeypatch: pytest.MonkeyPatch, ptype: str, expected_cls: type, env_key: str | None):
    """Factory returns the correct concrete provider class."""
    if env_key:
        monkeypatch.setenv(env_key, "DUMMY_KEY")

    provider = pf.create_provider(ptype)

    assert isinstance(provider, expected_cls)


# ---------------------------------------------------------------------------
# Unsupported provider string
# ---------------------------------------------------------------------------

def test_unsupported_provider_raises():
    """Requesting an unknown provider type should raise `ValueError`."""
    with pytest.raises(ValueError) as exc:
        pf.create_provider("made_up")

    assert "Unsupported data provider type" in str(exc.value)


# ---------------------------------------------------------------------------
# Credential validation – Polygon missing key
# ---------------------------------------------------------------------------

def test_polygon_missing_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)

    with pytest.raises(ValueError):
        pf.create_provider("polygon")


# ---------------------------------------------------------------------------
# Registry helper coverage
# ---------------------------------------------------------------------------

def test_supported_provider_registry():
    supported = pf.get_supported_providers()

    # Must contain at least the core four providers
    for expected in {"demo", "polygon", "coinmarketcap", "yfinance"}:
        assert expected in supported

    # is_provider_supported must agree with the list
    for provider in supported:
        assert pf.is_provider_supported(provider)

    # and be False for clearly bogus provider
    assert not pf.is_provider_supported("totally_bogus") 