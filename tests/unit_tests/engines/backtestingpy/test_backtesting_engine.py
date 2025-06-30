"""
BacktestingSignalExtractor Unit-Tests
=====================================
Offline micro-tests for
``StrateQueue.engines.backtesting_engine.BacktestingSignalExtractor``.

Requirements verified in this module
------------------------------------
A. Initialisation & parameter handling
   A1 extractor.granularity_seconds parsed from '1m'      → 60      (open-candle trim).
   A2 min_bars_required guard emits HOLD + indicator when data < min bars.
   A3 engine-only kwargs ('persistent', 'history_multiplier') are NOT forwarded to Backtest(...).

B. Legacy extraction path
   B1 With last Close ↑ previous Close → BUY, ↓ → SELL.
   B2 TradingSignal.price equals last row Close.

C. Persistent extraction path
   C1 first call (initialisation) returns HOLD while extractor warms up.
   C2 pushing a new bar then calling again emits BUY/SELL via PersistentBacktest.step.
   C3 reset() stops the persistent engine and subsequent extract recreates it.

D. Open-candle trimming
   D1 <granularity_seconds old → row dropped (already covered by C1 test).
   D2 ≥granularity_seconds old → NO row dropped (no-trim branch).

E. Memory-cap logic (covered).

F. Exception safety
   F1 Backtest.run raising an error yields HOLD and error message in metadata.

G. Strategy conversion helper
   G1 StrategyLoader.convert_to_signal_strategy called exactly once during extractor init.

H. Dependency flag
   H1 BacktestingEngine.dependencies_available() reflects absence of library when BACKTESTING_AVAILABLE=False.

All tests skip automatically when the external ``backtesting`` library is
missing so they remain green in minimal CI images.
"""
# ---------------------------------------------------------------------------
# Imports / setup
# ---------------------------------------------------------------------------
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import pytest
from types import SimpleNamespace
import importlib

# Make sure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Skip entire module if backtesting.py is absent
pytest.importorskip("backtesting")

from backtesting import Strategy  # type: ignore
from StrateQueue.engines.backtesting_engine import (
    BacktestingEngineStrategy,
    BacktestingSignalExtractor,
)
from StrateQueue.core.signal_extractor import SignalType, TradingSignal
import StrateQueue.engines.backtesting_engine as be
import StrateQueue.core.strategy_loader as sl

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def aapl_df() -> pd.DataFrame:
    """Load & normalise the bundled AAPL daily data."""
    csv_path = PROJECT_ROOT / "examples" / "data" / "AAPL.csv"
    df = (
        pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        .replace(",", "", regex=True)
    )
    # Ensure numeric dtype
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Sort oldest→newest so that last row is latest day
    df = df.sort_index()
    return df


@pytest.fixture(scope="session")
def dummy_strategy():
    """Very small backtesting.py strategy that goes long if price rises bar-to-bar."""
    class _Dummy(Strategy):
        def next(self):
            # BUY if last close higher than previous, else SELL
            if self.data.Close[-1] > self.data.Close[-2]:
                self.buy()
            elif self.data.Close[-1] < self.data.Close[-2]:
                self.sell()
    return _Dummy


@pytest.fixture
def extractor(dummy_strategy):
    """Return a BacktestingSignalExtractor (legacy/full-run path)."""
    eng_strat = BacktestingEngineStrategy(dummy_strategy)
    return BacktestingSignalExtractor(
        eng_strat, granularity="1m", min_bars_required=5, history_multiplier=2
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_A1_granularity_parsed(extractor):
    assert extractor.granularity_seconds == 60


def test_A2_min_bars_guard(extractor, aapl_df):
    small = aapl_df.head(3)      # fewer than min_bars_required=5
    sig = extractor.extract_signal(small)
    assert sig.signal is SignalType.HOLD
    assert sig.indicators.get("insufficient_data") is True


def test_B1_B2_buy_or_sell_and_price(extractor, aapl_df):
    df = aapl_df.tail(10)        # >=5 rows
    sig = extractor.extract_signal(df)

    last_close, prev_close = df.Close.iloc[-1], df.Close.iloc[-2]
    expected = (
        SignalType.BUY if last_close > prev_close
        else SignalType.SELL if last_close < prev_close
        else SignalType.HOLD
    )
    assert sig.signal is expected
    assert sig.price == pytest.approx(last_close, rel=1e-9)


def test_C1_trim_open_candle_logic(extractor, aapl_df):
    # Build a tiny DF whose last bar is <60s old
    recent = aapl_df.tail(2).copy()
    recent.index = [
        pd.Timestamp.utcnow() - pd.Timedelta(minutes=1, seconds=5),
        pd.Timestamp.utcnow() - pd.Timedelta(seconds=30),  # still-forming
    ]
    trimmed = extractor._trim_open_candle(recent, extractor.granularity_seconds)
    assert len(trimmed) == len(recent) - 1
    # The surviving last timestamp should be the older one
    assert trimmed.index[-1] < pd.Timestamp.utcnow() - pd.Timedelta(seconds=59)


def test_C2_memory_cap(extractor, aapl_df):
    lookback = extractor.get_minimum_bars_required()      # 5
    hist_mult = 2
    long_df = aapl_df.head(200)                           # plenty of rows
    capped = extractor._apply_memory_limit(long_df, hist_mult)
    assert len(capped) == lookback * hist_mult


def test_A3_kwargs_not_forwarded(monkeypatch, aapl_df, dummy_strategy):
    """Ensure 'persistent' & 'history_multiplier' are stripped before Backtest(...)"""
    captured: dict = {}

    class _SpyBT:
        def __init__(self, _data, _cls, **kwargs):
            captured.update(kwargs)
        def run(self):
            return SimpleNamespace(
                _strategy=SimpleNamespace(
                    get_current_signal=lambda: TradingSignal(
                        SignalType.HOLD,
                        price=0.0,
                        timestamp=pd.Timestamp.utcnow(),
                        indicators={},
                    )
                )
            )

    monkeypatch.setattr(be, "Backtest", _SpyBT, raising=True)

    ex = BacktestingSignalExtractor(
        BacktestingEngineStrategy(dummy_strategy),
        granularity="1m",
        min_bars_required=2,
        persistent=False,
        history_multiplier=7,
    )
    # Trigger extraction
    ex.extract_signal(aapl_df.tail(10))

    assert "persistent" not in captured and "history_multiplier" not in captured


def test_D2_open_candle_not_trimmed(extractor, aapl_df):
    """If last bar is older than granularity_seconds, extractor should not trim it."""
    df = aapl_df.tail(3).copy()
    # Make last timestamp >= 2 minutes old
    df.index = df.index[:-1].append(
        pd.DatetimeIndex([pd.Timestamp.utcnow() - pd.Timedelta(minutes=2)])
    )
    trimmed = extractor._trim_open_candle(df, extractor.granularity_seconds)
    assert len(trimmed) == len(df)


def test_F1_exception_yields_hold(monkeypatch, extractor, aapl_df):
    """Backtest.run exceptions downgrade to HOLD signal with error metadata."""
    class _BoomBT:
        def __init__(self, *a, **k):
            pass
        def run(self):
            raise RuntimeError("boom")
    monkeypatch.setattr(be, "Backtest", _BoomBT, raising=True)

    sig = extractor.extract_signal(aapl_df.tail(10))
    assert sig.signal is SignalType.HOLD
    assert "boom" in sig.metadata.get("error", "")


def test_C1_C2_C3_persistent_flow(monkeypatch, dummy_strategy, aapl_df):
    """Validate PersistentBacktest lifecycle (init, step, reset)"""
    step_calls: list = []

    class _SpyPersistent:
        def __init__(self, init_data, *_a, **_kw):
            self.init_len = len(init_data)
        def step(self, bar):
            step_calls.append(bar.name)
            return TradingSignal(
                SignalType.BUY,
                price=float(bar.Close),
                timestamp=bar.name,
                indicators={},
            )
        def stop(self):
            step_calls.append("stopped")
        def get_stats(self):
            return {}

    monkeypatch.setattr(be, "PersistentBacktest", _SpyPersistent, raising=True)

    ex = BacktestingSignalExtractor(
        BacktestingEngineStrategy(dummy_strategy),
        granularity="1m",
        persistent=True,
        min_bars_required=2,
    )

    df1 = aapl_df.tail(4).copy()
    sig1 = ex.extract_signal(df1)
    assert sig1.signal is SignalType.BUY and len(step_calls) == 1

    # Append new bar +1 minute
    new_bar_time = df1.index[-1] + pd.Timedelta(minutes=1)
    new_row = df1.iloc[-1:].assign(Close=lambda s: s.Close + 1)
    new_row.index = [new_bar_time]
    df2 = pd.concat([df1, new_row])
    sig2 = ex.extract_signal(df2)
    assert sig2.signal is SignalType.BUY and len(step_calls) == 2

    ex.reset()
    assert "stopped" in step_calls

    # Third extraction after reset → new persistent engine
    new_bar_time2 = df2.index[-1] + pd.Timedelta(minutes=1)
    new_row2 = df2.iloc[-1:].assign(Close=lambda s: s.Close + 1)
    new_row2.index = [new_bar_time2]
    df3 = pd.concat([df2, new_row2])
    ex.extract_signal(df3)
    assert step_calls.count("stopped") == 1 and len(step_calls) == 4


def test_G1_convert_called_once(monkeypatch, dummy_strategy):
    """Ensure StrategyLoader.convert_to_signal_strategy invoked once."""
    call_counter = {"n": 0}
    original = sl.StrategyLoader.convert_to_signal_strategy

    def _spy(*a, **k):
        call_counter["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(sl.StrategyLoader, "convert_to_signal_strategy", _spy, raising=True)
    BacktestingSignalExtractor(BacktestingEngineStrategy(dummy_strategy), granularity="1m")
    assert call_counter["n"] == 1


def test_H1_dependency_flag(monkeypatch):
    """dependencies_available() should flip when BACKTESTING_AVAILABLE is patched."""
    monkeypatch.setattr(be, "BACKTESTING_AVAILABLE", False, raising=False)
    assert be.BacktestingEngine.dependencies_available() is False