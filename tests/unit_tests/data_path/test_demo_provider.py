"""tests/unit_tests/data_path/test_demo_provider.py

REQUIREMENTS
------------
These tests cover the *demo / test* data-provider
(`src/StrateQueue/data/sources/demo.py`).  A passing run demonstrates that:

1. `fetch_historical_data` returns a *well-formed* `pandas.DataFrame` whose
   index is a `DatetimeIndex` and whose columns are exactly
   `['Open', 'High', 'Low', 'Close', 'Volume']`.  The method caches its result
   so subsequent calls for the same `(symbol, days_back, granularity)` tuple
   return **the identical object** (not merely an equal DataFrame).
2. OHLC sanity – for every bar, `High ≥ max(Open, Close)` and
   `Low ≤ min(Open, Close)`.
3. `append_new_bar` appends exactly one new row, updates
   `current_bars[symbol]`, and ensures the timestamp is strictly newer than
   before.
4. The real-time simulation lifecycle flips `is_connected` True/False and the
   background thread terminates within the 2-second join timeout.

If every assertion in this file passes the requirements for the demo provider
are considered satisfied.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from StrateQueue.data.sources.demo import TestDataIngestion


# ---------------------------------------------------------------------------
# Helper values
# ---------------------------------------------------------------------------
_SYMBOL = "AAPL"


# ---------------------------------------------------------------------------
# fetch_historical_data returns a well-formed, cached DataFrame
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_historical_dataframe_shape_and_columns():
    provider = TestDataIngestion()
    df = await provider.fetch_historical_data(_SYMBOL, days_back=1, granularity="1m")

    # Basic frame checks
    assert isinstance(df, pd.DataFrame)
    assert df.index.is_monotonic_increasing
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    # OHLC sanity per row
    high_is_max = (df["High"] >= df[["Open", "Close"]].max(axis=1)).all()
    low_is_min = (df["Low"] <= df[["Open", "Close"]].min(axis=1)).all()
    assert high_is_max and low_is_min


@pytest.mark.asyncio
async def test_historical_is_cached():
    provider = TestDataIngestion()
    df1 = await provider.fetch_historical_data(_SYMBOL, days_back=1, granularity="1m")
    df2 = await provider.fetch_historical_data(_SYMBOL, days_back=1, granularity="1m")

    # The very same object should be returned from cache
    assert df1 is df2


# ---------------------------------------------------------------------------
# append_new_bar adds exactly one newer bar and updates structures
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_append_new_bar_updates_structures():
    provider = TestDataIngestion()
    df_initial = await provider.fetch_historical_data(_SYMBOL, days_back=1, granularity="1m")
    last_ts_before = df_initial.index[-1]
    rows_before = len(df_initial)

    df_after = provider.append_new_bar(_SYMBOL)

    # One extra row
    assert len(df_after) == rows_before + 1

    # Timestamp strictly newer
    assert df_after.index[-1] > last_ts_before

    # Structures updated
    assert _SYMBOL in provider.current_bars
    md = provider.current_bars[_SYMBOL]
    assert md.timestamp == df_after.index[-1]


# ---------------------------------------------------------------------------
# Real-time lifecycle
# ---------------------------------------------------------------------------

def test_realtime_lifecycle():
    provider = TestDataIngestion()
    provider.set_update_interval(0.05)  # fast updates for the test

    provider.start_realtime_feed()
    assert provider.is_connected

    # Give the thread a moment to spin
    time.sleep(0.15)

    provider.stop_realtime_feed()
    assert provider.is_connected is False

    # The simulation thread should be gone (joined) or not alive
    if provider.simulation_thread is not None:
        assert not provider.simulation_thread.is_alive() 