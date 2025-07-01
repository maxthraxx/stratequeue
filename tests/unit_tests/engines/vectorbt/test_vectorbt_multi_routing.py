import pandas as pd
from pandas import Timestamp

from StrateQueue.engines.vectorbt_engine import (
    VectorBTEngineStrategy,
    VectorBTMultiTickerSignalExtractor,
)
from StrateQueue.core.signal_extractor import SignalType


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _buy_on_last_bar_strategy():
    """Return a minimal VectorBT-compatible strategy that buys on the last bar."""

    def _strategy(data: pd.DataFrame):
        entries = pd.Series(False, index=data.index)
        exits = pd.Series(False, index=data.index)
        # Flag last bar as an entry
        if len(data):
            entries.iloc[-1] = True
        return entries, exits  # no size series

    return _strategy


def _gen_ohlc(start_price: float, rows: int) -> pd.DataFrame:
    idx = pd.date_range(end=Timestamp.utcnow(), periods=rows, freq="1min")
    return pd.DataFrame({
        "Open": start_price,
        "High": start_price + 1,
        "Low": start_price - 1,
        "Close": start_price,
        "Volume": 100,
    }, index=idx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_multi_ticker_routing_buy_and_hold():
    """BTC has enough bars → BUY; ETH insufficient → HOLD."""
    symbols = ["BTC", "ETH"]

    btc_df = _gen_ohlc(30_000, rows=3)  # satisfies min_bars=2
    eth_df = _gen_ohlc(2_000, rows=1)   # insufficient

    strat = VectorBTEngineStrategy(_buy_on_last_bar_strategy())
    extractor = VectorBTMultiTickerSignalExtractor(
        strat,
        symbols=symbols,
        min_bars_required=2,
        granularity="1min",
    )

    signals = extractor.extract_signals({"BTC": btc_df, "ETH": eth_df})

    # Ensure both symbols are present and mapped correctly
    assert set(signals.keys()) == set(symbols)

    assert signals["BTC"].signal == SignalType.BUY
    assert signals["ETH"].signal == SignalType.HOLD
    # Sanity: price equality
    assert signals["BTC"].price == btc_df["Close"].iloc[-1] 