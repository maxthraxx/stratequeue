import pandas as pd
import pytest
from datetime import timedelta

from StrateQueue.data.sources.data_source_base import MarketData


_SYMBOL_FX = {
    "demo": "AAPL",
    "polygon": "AAPL",
    "yfinance": "AAPL",
    "cmc": "BTC",
}

_GRANULARITY_FX = {
    "demo": "1m",
    "polygon": "1m",
    "yfinance": "1m",
    "cmc": "1d",
}


# ---------------------------------------------------------------------------
# Historical fetch – shape, columns & OHLC sanity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_historical_dataframe_shape_and_columns(provider):
    name = getattr(provider, "_test_name", "demo")
    symbol = _SYMBOL_FX[name]
    granularity = _GRANULARITY_FX[name]

    df = await provider.fetch_historical_data(symbol, days_back=1, granularity=granularity)

    # Basic frame checks
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert df.index.is_monotonic_increasing
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    # OHLC sanity per row
    high_ok = (df["High"] >= df[["Open", "Close"]].max(axis=1)).all()
    low_ok = (df["Low"] <= df[["Open", "Close"]].min(axis=1)).all()
    assert high_ok and low_ok


# ---------------------------------------------------------------------------
# Cache behaviour – identical object for demo provider, equality for others
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_historical_cache_semantics(provider):
    name = getattr(provider, "_test_name", "demo")
    symbol = _SYMBOL_FX[name]
    granularity = _GRANULARITY_FX[name]

    df1 = await provider.fetch_historical_data(symbol, days_back=1, granularity=granularity)
    df2 = await provider.fetch_historical_data(symbol, days_back=1, granularity=granularity)

    if name == "demo":
        assert df1 is df2  # demo provider promises identity
    else:
        # Non-demo providers may rebuild the frame; ensure *values* are identical.
        assert df1.reset_index(drop=True).equals(df2.reset_index(drop=True))


# ---------------------------------------------------------------------------
# append_current_bar – ensure exactly one new bar is appended
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_append_current_bar_updates_structures(provider):
    name = getattr(provider, "_test_name", "demo")
    symbol = _SYMBOL_FX[name]
    granularity = _GRANULARITY_FX[name]

    df_initial = await provider.fetch_historical_data(symbol, days_back=1, granularity=granularity)
    last_ts_before = df_initial.index[-1]
    rows_before = len(df_initial)

    # Create synthetic MarketData one interval ahead of current granularity
    gran_seconds = getattr(provider, "granularity_seconds", 60)
    new_ts = last_ts_before + timedelta(seconds=gran_seconds + 1)

    md = MarketData(
        symbol=symbol,
        timestamp=new_ts,
        open=float(df_initial["Close"].iloc[-1]),
        high=float(df_initial["Close"].iloc[-1] * 1.01),
        low=float(df_initial["Close"].iloc[-1] * 0.99),
        close=float(df_initial["Close"].iloc[-1]),
        volume=int(df_initial["Volume"].iloc[-1] + 10),
    )

    provider.current_bars[symbol] = md

    df_after = provider.append_current_bar(symbol)

    # One extra row expected
    assert len(df_after) == rows_before + 1

    # Timestamp strictly newer
    assert df_after.index[-1] > last_ts_before 