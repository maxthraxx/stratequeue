"""
VectorBTSignalExtractor Unit-Tests
=================================
Offline micro-tests for
    ``StrateQueue.engines.vectorbt_engine.VectorBTSignalExtractor`` and
    ``VectorBTMultiTickerSignalExtractor``.

Requirements verified in this module
------------------------------------
A. Data validation / normalisation
   A1  Alias columns renamed to title-case.
   A2  Close-only frame autocompletes OHLC.
   A3  Missing Volume added.
   A4  NaNs forward/back-filled & numeric coercion.
   A5  Missing Close raises ValueError.

B. Minimum-bars guard
   B1  <min_bars_required ⇒ HOLD + indicator.

C. Core extraction logic
   C1  BUY when entries=True & exits=False.
   C2  SELL when exits=True & entries=False.
   C3  HOLD otherwise.
   C4  price passthrough.
   C5  size passthrough.
   C6  indicators include granularity + pandas_freq.

D. Exception safety
   D1  Strategy error ⇒ HOLD + metadata['error'].

E. Multi-ticker extractor
   E1  Missing symbol ⇒ HOLD.
   E2  Insufficient bars ⇒ HOLD + indicator.
   E3  When valid, parity with single-ticker extractor.

F. Dependency flag
   F1  Patching VECTORBT_AVAILABLE flips dependencies_available().

All tests run without the real ``vectorbt`` library thanks to monkey-patching
``call_vectorbt_strategy``.
"""
# ---------------------------------------------------------------------------
# Imports / setup
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

import StrateQueue.engines.vectorbt_engine as vbe
from StrateQueue.engines.vectorbt_engine import (
    VectorBTEngineStrategy,
    VectorBTSignalExtractor,
    VectorBTMultiTickerSignalExtractor,
)
from StrateQueue.core.signal_extractor import SignalType, TradingSignal

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def aapl_df() -> pd.DataFrame:
    """Load & normalise the bundled AAPL daily data (upper-case columns)."""
    csv = PROJECT_ROOT / "examples" / "data" / "AAPL.csv"
    df = (
        pd.read_csv(csv, parse_dates=["Date"], index_col="Date")
        .replace(",", "", regex=True)
    )
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_index()


@pytest.fixture
def extractor():
    eng_strat = VectorBTEngineStrategy(lambda d: None)          # dummy
    return VectorBTSignalExtractor(
        eng_strat, granularity="1m", min_bars_required=5
    )


def _stub_call(entries_last: bool, exits_last: bool, size_last: float | None = None):
    """Return a stub for call_vectorbt_strategy producing desired last-bar flags."""
    def _impl(_cls, data: pd.DataFrame, **_kw):
        idx = data.index
        n = len(idx)
        entries = pd.Series([False]*(n-1) + [entries_last], index=idx, name="e")
        exits   = pd.Series([False]*(n-1) + [exits_last],   index=idx, name="x")
        if size_last is None:
            return entries, exits, None
        size = pd.Series([0.0]*(n-1) + [size_last], index=idx, name="s")
        return entries, exits, size
    return _impl

# ---------------------------------------------------------------------------
# A - Data validation / normalisation
# ---------------------------------------------------------------------------

def test_A1_alias_columns_renamed(extractor):
    df = pd.DataFrame(
        {
            "o": [1, 2],
            "h": [2, 3],
            "l": [0.5, 1.5],
            "close": [1, 2],
            "vol": [10, 10],
        },
        index=pd.date_range("2023-01-01", periods=2, freq="1T"),
    )
    norm = extractor._validate_and_normalize_data(df)
    assert set(norm.columns) >= {"Open", "High", "Low", "Close", "Volume"}


def test_A2_A3_close_only_autofill_and_volume(extractor):
    df = pd.DataFrame({"close": [1, 2, 3]},
                      index=pd.date_range("2023-01-01", periods=3, freq="1T"))
    norm = extractor._validate_and_normalize_data(df)
    # Compare element-wise instead of DataFrame alignment
    for col in ["Open", "High", "Low"]:
        assert (norm[col] == norm["Close"]).all()
    assert "Volume" in norm.columns and (norm["Volume"] == 1.0).all()


def test_A4_nan_forward_fill(extractor):
    df = pd.DataFrame(
        {"Close": [1, None, 3]},
        index=pd.date_range("2023-01-01", periods=3, freq="1T"),
    )
    norm = extractor._validate_and_normalize_data(df)
    # NaNs should be filled
    assert norm["Close"].isna().sum() == 0


def test_A5_missing_close_raises(extractor):
    df = pd.DataFrame(
        {"Open": [1, 2]},
        index=pd.date_range("2023", periods=2, freq="1T"),
    )
    with pytest.raises(ValueError):
        extractor._validate_and_normalize_data(df)

# ---------------------------------------------------------------------------
# B - Minimum-bars guard
# ---------------------------------------------------------------------------

def test_B1_min_bars_guard(extractor, aapl_df):
    sig = extractor.extract_signal(aapl_df.head(3))  # <5 bars
    assert sig.signal is SignalType.HOLD
    assert sig.indicators.get("insufficient_data") is True

# ---------------------------------------------------------------------------
# C - Core extraction (BUY / SELL / HOLD paths)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "entries_last, exits_last, expected",
    [
        (True,  False, SignalType.BUY),
        (False, True,  SignalType.SELL),
        (False, False, SignalType.HOLD),
    ],
)
def test_C1_C3_signal_paths(monkeypatch, extractor, aapl_df,
                            entries_last, exits_last, expected):
    monkeypatch.setattr(
        vbe, "call_vectorbt_strategy",
        _stub_call(entries_last, exits_last),
        raising=True,
    )
    sig = extractor.extract_signal(aapl_df.tail(10))
    assert sig.signal is expected
    assert sig.price == pytest.approx(aapl_df.Close.iloc[-1], rel=1e-9)
    assert sig.indicators["granularity"] == "1m"
    assert sig.indicators["pandas_freq"] == "1T"


def test_C5_size_passthrough(monkeypatch, extractor, aapl_df):
    monkeypatch.setattr(
        vbe, "call_vectorbt_strategy",
        _stub_call(True, False, size_last=1.5),
        raising=True,
    )
    sig = extractor.extract_signal(aapl_df.tail(10))
    assert sig.size == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# D - Exception safety
# ---------------------------------------------------------------------------

def test_D1_exception_downgrades_to_hold(monkeypatch, extractor, aapl_df):
    def _boom(*_a, **_k):
        raise RuntimeError("vectorbt failed")

    monkeypatch.setattr(vbe, "call_vectorbt_strategy", _boom, raising=True)
    sig = extractor.extract_signal(aapl_df.tail(10))
    assert sig.signal is SignalType.HOLD
    assert "vectorbt failed" in sig.metadata.get("error", "")

# ---------------------------------------------------------------------------
# E - Multi-ticker extractor
# ---------------------------------------------------------------------------

@pytest.fixture
def multi_extractor():
    """Concrete wrapper that satisfies ABC for tests only."""
    class _TestMulti(vbe.VectorBTMultiTickerSignalExtractor):
        # Fulfils the abstract extract_signal; not used in tests
        def extract_signal(self, *_a, **_kw):
            return TradingSignal(SignalType.HOLD, price=0.0,
                                 timestamp=pd.Timestamp.utcnow(),
                                 indicators={})

    eng = VectorBTEngineStrategy(lambda d: None)
    return _TestMulti(eng, symbols=["AAA", "BBB"],
                      min_bars_required=3, granularity="1m")


def _mk_df(seed: int, rows: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": list(range(seed, seed + rows))},
        index=pd.date_range("2023-01-01", periods=rows, freq="1T"),
    )


def test_E1_missing_symbol(monkeypatch, multi_extractor):
    monkeypatch.setattr(
        vbe, "call_vectorbt_strategy", _stub_call(True, False), raising=True
    )
    data = {"AAA": _mk_df(1)}
    sigs = multi_extractor.extract_signals(data)
    assert sigs["BBB"].signal is SignalType.HOLD


def test_E2_insufficient_bars(monkeypatch, multi_extractor):
    monkeypatch.setattr(
        vbe, "call_vectorbt_strategy", _stub_call(True, False), raising=True
    )
    data = {"AAA": _mk_df(1, rows=2), "BBB": _mk_df(10, rows=4)}
    sigs = multi_extractor.extract_signals(data)
    assert sigs["AAA"].signal is SignalType.HOLD
    assert sigs["BBB"].signal is SignalType.BUY


def test_E3_parity_with_single_extractor(monkeypatch, multi_extractor):
    monkeypatch.setattr(
        vbe, "call_vectorbt_strategy", _stub_call(True, False), raising=True
    )
    data = {"AAA": _mk_df(1, 5), "BBB": _mk_df(10, 5)}
    sigs_multi = multi_extractor.extract_signals(data)

    # Single extractor reference
    eng = VectorBTEngineStrategy(lambda d: None)
    single = VectorBTSignalExtractor(eng, granularity="1m")
    monkeypatch.setattr(
        vbe, "call_vectorbt_strategy", _stub_call(True, False), raising=True
    )
    ref = {sym: single.extract_signal(df) for sym, df in data.items()}
    assert {s.signal for s in sigs_multi.values()} == {s.signal for s in ref.values()}

# ---------------------------------------------------------------------------
# F - Dependency flag
# ---------------------------------------------------------------------------

def test_F1_dependency_flag(monkeypatch):
    monkeypatch.setattr(vbe, "VECTORBT_AVAILABLE", False, raising=False)
    assert vbe.VectorBTEngine.dependencies_available() is False