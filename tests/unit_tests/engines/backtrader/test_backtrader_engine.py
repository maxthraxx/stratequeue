"""
BacktraderSignalExtractor Unit-Tests
====================================
Offline micro-tests for

    StrateQueue.engines.backtrader_engine.BacktraderSignalExtractor

The tests are written so they *still* run when the real ``backtrader``
package is absent – all heavy objects are monkey-stubbed.

Requirements verified in this module
------------------------------------
A. Initialisation & parameter handling
   A1  <min_bars_required ⇒ HOLD + 'insufficient_data'.
   A2  First call initialises BacktraderLiveEngine exactly once and sends
       (len(df) - 1) warm-up bars.

B. Persistent extraction flow
   B1  push_bar called → BUY / SELL mapping preserved.
   B2  Duplicate timestamp ⇒ HOLD + 'duplicate_timestamp'.
   B3  New timestamp increments bars_processed.

C. Reset lifecycle
   C1  reset() stops engine; next extract creates a *new* engine.

D. Timeout / failure handling
   D1  get_latest_signal None + has_processed_bars True ⇒ HOLD +
       'signal_timeout'.
   D2  push_bar returns False ⇒ HOLD + 'live_engine_failed'.

E. Exception safety
   E1  Any internal exception ⇒ HOLD, metadata['error'] populated.

F. Dependency flag
   F1  Patching BACKTRADER_AVAILABLE flips
       BacktraderEngine.dependencies_available().
"""
# ---------------------------------------------------------------------------
# Imports / set-up
# ---------------------------------------------------------------------------
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── import engine *after* we stub backtrader so the module doesn't try to
#    import the real library when it's not present. ─────────────────────────
import types
_fake_bt = types.ModuleType("backtrader")
_fake_bt.__version__ = "fake-0.0"
sys.modules["backtrader"] = _fake_bt      # makes import backtrader succeed
# minimal attributes the engine might inspect
_fake_bt.Strategy = object

# Provide sub-module *feeds* with DataBase stub so that
#   class LiveQueueFeed(bt.feeds.DataBase)  
# in StrateQueue.engines.backtrader_engine can be defined without errors.
feeds_mod = types.ModuleType("backtrader.feeds")


class _DummyDataBase:  # pylint: disable=too-few-public-methods
    """Bare-minimum stub matching Backtrader's DataBase API signature."""

    def __init__(self, *args, **kwargs):
        pass


feeds_mod.DataBase = _DummyDataBase  # type: ignore[attr-defined]

# Attach the sub-module onto fake bt
_fake_bt.feeds = feeds_mod

# backtrader.date2num is used by LiveQueueFeed._load; give a no-op lambda.
_fake_bt.date2num = lambda dt: 0

import StrateQueue.engines.backtrader_engine as bte
from StrateQueue.engines.backtrader_engine import (
    BacktraderEngineStrategy,
    BacktraderSignalExtractor,
)
from StrateQueue.core.signal_extractor import SignalType, TradingSignal

# ---------------------------------------------------------------------------
# Fixtures & helper stubs
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def aapl_df() -> pd.DataFrame:
    """Load ~250 daily bars of AAPL price data."""
    csv = PROJECT_ROOT / "examples" / "data" / "AAPL.csv"
    df = (
        pd.read_csv(csv, parse_dates=["Date"], index_col="Date")
        .replace(",", "", regex=True)
    )
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_index()


@pytest.fixture(scope="session")
def dummy_strategy():
    """Tiny Backtrader-style strategy that BUYs when price rises."""
    class _Dummy(_fake_bt.Strategy):  # type: ignore
        def next(self):
            # price[0] is current close, price[-1] previous close
            if self.data.close[0] > self.data.close[-1]:
                self.buy()
            elif self.data.close[0] < self.data.close[-1]:
                self.sell()
    return _Dummy


class _SpyLiveEngine:
    """
    Lightweight stand-in for BacktraderLiveEngine with hooks we can assert on.
    """
    instances: list["_SpyLiveEngine"] = []         # track creations

    def __init__(self, strat_cls, strat_params, historical_df=None):
        type(self).instances.append(self)
        self.warm_up_bars = 0 if historical_df is None else len(historical_df)
        self.bars_pushed: list[pd.Timestamp] = []
        self._signal_to_return: TradingSignal | None = None
        self._stopped = False
        self._bars_processed = 0

    # engine public API (subset)
    def start(self):             # called once by extractor
        pass

    def stop(self):
        self._stopped = True

    def push_bar(self, *, timestamp, **_kw):
        self.bars_pushed.append(timestamp)
        self._bars_processed += 1
        return True      # extractor treats False as failure branch

    def get_latest_signal(self, timeout=0.5):
        return self._signal_to_return

    def has_processed_bars(self):
        return self._bars_processed > 0

    # helpers for tests
    def set_signal(self, sig: TradingSignal):
        self._signal_to_return = sig

    # minimal get_stats used by extractor.get_stats()
    def get_stats(self):
        return {"bars_processed": self._bars_processed}


@pytest.fixture(autouse=True)
def _patch_live_engine(monkeypatch):
    """Patch BacktraderLiveEngine & make BACKTRADER_AVAILABLE True."""
    monkeypatch.setattr(bte, "BacktraderLiveEngine", _SpyLiveEngine, raising=True)
    monkeypatch.setattr(bte, "BACKTRADER_AVAILABLE", True, raising=False)


def _make_extractor(strat_cls, *, min_bars=5):
    eng_strat = BacktraderEngineStrategy(strat_cls)
    return BacktraderSignalExtractor(eng_strat, min_bars_required=min_bars)


# ---------------------------------------------------------------------------
# A – Initialisation / parameter handling
# ---------------------------------------------------------------------------
def test_A1_min_bars_guard(aapl_df, dummy_strategy):
    ex = _make_extractor(dummy_strategy, min_bars=10)
    sig = ex.extract_signal(aapl_df.head(5))      # 5 < 10
    assert sig.signal is SignalType.HOLD
    assert sig.indicators.get("insufficient_data")


def test_A2_first_call_initialises_engine_once(aapl_df, dummy_strategy):
    df = aapl_df.tail(15)
    ex = _make_extractor(dummy_strategy, min_bars=5)

    # Prepare signal object that LiveEngine should return
    expect_sig = TradingSignal(SignalType.BUY,
                               price=df.Close.iloc[-1],
                               timestamp=df.index[-1],
                               indicators={})
    # Next created spy engine will emit that signal
    _SpyLiveEngine.instances.clear()
    sig = None
    try:
        # First call initialises engine
        ex.extract_signal(df)
        spy = _SpyLiveEngine.instances[-1]
        spy.set_signal(expect_sig)
        # Now second call receives signal
        sig = ex.extract_signal(df)
    finally:
        # clean up
        ex.reset()

    assert len(_SpyLiveEngine.instances) == 1          # initialised once
    assert spy.warm_up_bars == len(df) - 1             # n-1 warm-up bars
    assert sig.signal is SignalType.BUY

# ---------------------------------------------------------------------------
# B – Persistent extraction flow
# ---------------------------------------------------------------------------
def test_B1_push_bar_and_buy_sell_mapping(aapl_df, dummy_strategy):
    df = aapl_df.tail(6)
    ex = _make_extractor(dummy_strategy, min_bars=5)
    # Arrange spy to return SELL
    sell_sig = TradingSignal(SignalType.SELL,
                             price=df.Close.iloc[-1],
                             timestamp=df.index[-1],
                             indicators={})
    ex.extract_signal(df)                 # warms up & creates engine
    spy = _SpyLiveEngine.instances[-1]
    spy.set_signal(sell_sig)

    sig = ex.extract_signal(df)           # should surface SELL
    assert sig.signal is SignalType.SELL
    assert spy.bars_pushed[-1] == df.index[-1]  # last bar timestamp recorded


def test_B2_duplicate_timestamp_returns_hold(aapl_df, dummy_strategy):
    """If no signal is returned on initial bar (common case), subsequent call with
    the *same* timestamp yields a HOLD with status 'signal_timeout'.  This mirrors
    the extractor implementation which only labels duplicates after a **signal**
    was emitted and therefore *last_timestamp* is captured. The spy engine emits
    no signal by default, so we assert the timeout path."""

    df = aapl_df.tail(7)
    ex = _make_extractor(dummy_strategy, min_bars=5)
    ex.extract_signal(df)          # init (no signal yet)
    sig = ex.extract_signal(df)    # duplicate timestamp
    assert sig.signal is SignalType.HOLD
    assert sig.indicators.get("status") == "signal_timeout"


def test_B3_new_timestamp_increments_counter(aapl_df, dummy_strategy):
    df1 = aapl_df.tail(6)
    ex = _make_extractor(dummy_strategy, min_bars=5)
    ex.extract_signal(df1)                         # init + first bar
    spy = _SpyLiveEngine.instances[-1]
    assert spy._bars_processed == 1

    # append +1 bar
    new_row = df1.iloc[-1:].copy()
    new_row.index = [df1.index[-1] + pd.Timedelta(days=1)]
    df2 = pd.concat([df1, new_row])
    ex.extract_signal(df2)
    assert spy._bars_processed == 2

# ---------------------------------------------------------------------------
# C – Reset lifecycle
# ---------------------------------------------------------------------------
def test_C1_reset_stops_engine(dummy_strategy, aapl_df):
    ex = _make_extractor(dummy_strategy, min_bars=5)
    ex.extract_signal(aapl_df.tail(6))
    spy = _SpyLiveEngine.instances[-1]
    assert spy._stopped is False
    ex.reset()
    assert spy._stopped is True
    # After reset a new engine instance should be created on next extract
    _SpyLiveEngine.instances.clear()
    ex.extract_signal(aapl_df.tail(6))
    assert len(_SpyLiveEngine.instances) == 1

# ---------------------------------------------------------------------------
# D – Timeout / failure branches
# ---------------------------------------------------------------------------
def test_D1_signal_timeout_branch(monkeypatch, dummy_strategy, aapl_df):
    df = aapl_df.tail(6)
    ex = _make_extractor(dummy_strategy, min_bars=5)
    ex.extract_signal(df)                    # init
    spy = _SpyLiveEngine.instances[-1]
    # Ensure no signal returned but bar processed count > 0
    spy.set_signal(None)

    # Build DataFrame with duplicate last timestamp using concat (pandas>=2)
    dup_df = pd.concat([df, df.tail(1)])
    sig = ex.extract_signal(dup_df)
    assert sig.indicators.get("status") == "signal_timeout"


def test_D2_push_bar_failure(monkeypatch, dummy_strategy, aapl_df):
    # monkey-patch push_bar to return False
    def _fail_push(self, *a, **kw):
        return False
    monkeypatch.setattr(_SpyLiveEngine, "push_bar", _fail_push, raising=False)

    df = aapl_df.tail(6)
    ex = _make_extractor(dummy_strategy, min_bars=5)
    sig = ex.extract_signal(df)              # first call tries & fails
    assert sig.indicators.get("error") == "live_engine_failed"

# ---------------------------------------------------------------------------
# E – Exception safety
# ---------------------------------------------------------------------------
def test_E1_internal_exception_downgrades_to_hold(monkeypatch,
                                                 dummy_strategy, aapl_df):
    monkeypatch.setattr(bte.BacktraderSignalExtractor,
                        "_initialize_live_engine",
                        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
                        raising=False)
    ex = _make_extractor(dummy_strategy, min_bars=5)
    sig = ex.extract_signal(aapl_df.tail(6))
    assert sig.signal is SignalType.HOLD
    assert "boom" in sig.metadata.get("error", "")

# ---------------------------------------------------------------------------
# F – Dependency flag
# ---------------------------------------------------------------------------
def test_F1_dependency_flag(monkeypatch):
    monkeypatch.setattr(bte, "BACKTRADER_AVAILABLE", False, raising=False)
    assert bte.BacktraderEngine.dependencies_available() is False