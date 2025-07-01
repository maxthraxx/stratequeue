import pandas as pd
from pandas import Timestamp

from StrateQueue.engines.vectorbt_engine import (
    VectorBTEngineStrategy,
    VectorBTSignalExtractor,
)
from StrateQueue.core.signal_extractor import SignalType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_strategy_buy(data: pd.DataFrame):
    """Buys always when called (for non-HOLD path)."""
    s = pd.Series(False, index=data.index)
    if len(data):
        s.iloc[-1] = True
    return s, pd.Series(False, index=data.index)


def _build_extractor(min_bars_required: int):
    strat = VectorBTEngineStrategy(_dummy_strategy_buy)
    return VectorBTSignalExtractor(strat, min_bars_required=min_bars_required)


def _make_close_series(vals):
    idx = pd.date_range(end=Timestamp.utcnow(), periods=len(vals), freq="1min")
    return pd.DataFrame({"Close": vals}, index=idx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_insufficient_bars_yields_hold_signal():
    extractor = _build_extractor(min_bars_required=5)

    df_short = _make_close_series([1, 2, 3])  # only 3 bars < 5
    sig = extractor.extract_signal(df_short)

    assert sig.signal == SignalType.HOLD
    assert sig.indicators.get("insufficient_data") is True


def test_sufficient_bars_runs_strategy():
    extractor = _build_extractor(min_bars_required=3)

    df_long = _make_close_series([1, 2, 3, 4])
    sig = extractor.extract_signal(df_long)

    # Strategy always buys on last bar, so not HOLD
    assert sig.signal == SignalType.BUY
    assert "insufficient_data" not in sig.indicators 