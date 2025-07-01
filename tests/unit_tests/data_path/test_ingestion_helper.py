"""tests/unit_tests/data_path/test_ingestion_helper.py

REQUIREMENTS
------------
These tests validate the high-level helper `setup_data_ingestion` defined in
`src/StrateQueue/data/ingestion.py`.

1. **CONSTRUCT mode**
   • Provider is instantiated but *not* connected (`is_connected` is False).
   • No historical data fetched.
2. **ONLINE mode**
   • Provider is connected (`is_connected` is True) but still no history.
3. **FULL mode**
   • Historical data is fetched for every requested symbol.

The helper must raise `ValueError` when given an unrecognised `data_source`.
A test run passes when every assertion below succeeds.
"""

from __future__ import annotations

import pytest

from StrateQueue.data.ingestion import IngestionInit, setup_data_ingestion

SYMBOLS = ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# CONSTRUCT mode (build only)
# ---------------------------------------------------------------------------

def test_construct_mode_returns_uninitialised_demo():
    provider = setup_data_ingestion(
        data_source="demo",
        symbols=SYMBOLS,
        mode=IngestionInit.CONSTRUCT,
    )

    assert provider.is_connected is False
    assert provider.historical_data == {}


# ---------------------------------------------------------------------------
# ONLINE mode (build + realtime)
# ---------------------------------------------------------------------------

def test_online_mode_skips_history():
    provider = setup_data_ingestion(
        data_source="demo",
        symbols=SYMBOLS,
        mode=IngestionInit.ONLINE,
    )

    assert provider.is_connected is True
    # No history fetched yet
    assert provider.historical_data == {}


# ---------------------------------------------------------------------------
# FULL mode (build + realtime + fetch history)
# ---------------------------------------------------------------------------

def test_full_mode_fetches_history():
    provider = setup_data_ingestion(
        data_source="demo",
        symbols=SYMBOLS,
        days_back=1,
        mode=IngestionInit.FULL,
    )

    # History present for every symbol
    for sym in SYMBOLS:
        assert sym in provider.historical_data
        assert not provider.historical_data[sym].empty


# ---------------------------------------------------------------------------
# Unsupported data source string
# ---------------------------------------------------------------------------

def test_unknown_data_source_raises():
    with pytest.raises(ValueError):
        setup_data_ingestion("not_a_real_source", SYMBOLS) 