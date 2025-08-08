"""tests/unit_tests/core/test_signal_extractor.py

Unit-tests for StrateQueue.core.signal_extractor.LiveSignalExtractor.

We intentionally *stub* the heavy ``backtesting.Backtest`` dependency with a tiny
in-module fake so that these remain true micro-tests (milliseconds runtime).
The fixture data is loaded from ``examples/data/AAPL.csv``.

Scenarios under test
--------------------
1. Insufficient bars – when ``len(df) < min_bars_required`` the extractor should
   *not* attempt a backtest; it must return a default HOLD signal with empty
   metadata.
2. Happy-path delegation – given enough data, the extractor returns exactly the
   ``TradingSignal`` produced by the supplied strategy.
3. Signal propagation – for a selection of non-default ``SignalType`` values
   verify they survive intact through the extractor.
4. Missing column handling – if the OHLCV frame is missing a required column the
   extractor catches the error and returns a HOLD signal embedding the error
   text in ``metadata['error']``.

"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.is_dir():
    sys.path.insert(0, str(SRC_PATH))

import pandas as pd
import pytest

from StrateQueue.core.signal_extractor import (
    LiveSignalExtractor,
    TradingSignal,
    SignalType,
)

# ---------------------------------------------------------------------------
# Load AAPL OHLCV data once for all tests
# ---------------------------------------------------------------------------

CSV_PATH = PROJECT_ROOT / "examples" / "data" / "AAPL.csv"

if not CSV_PATH.exists():
    raise FileNotFoundError(f"AAPL fixture not found at {CSV_PATH}")

_AAPL_DF = pd.read_csv(CSV_PATH, parse_dates=["Date"], index_col="Date")
_AAPL_DF = _AAPL_DF.rename(columns={c: c.title() for c in _AAPL_DF.columns})
for col in ["Open", "High", "Low", "Close", "Volume"]:
    _AAPL_DF[col] = (
        _AAPL_DF[col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .astype(float)
    )
# chronological order (oldest first) – matches most engine expectations
_AAPL_DF = _AAPL_DF.iloc[::-1]


def _slice(rows: int) -> pd.DataFrame:
    """Return the *first* ``rows`` of the deterministic AAPL frame."""
    return _AAPL_DF.head(rows).copy()

# ---------------------------------------------------------------------------
# Tiny stubs replacing heavy backtesting.py classes
# ---------------------------------------------------------------------------

class _DummyStrategy:
    """Strategy whose ``get_current_signal`` returns a configurable value."""

    def __init__(self, desired: SignalType = SignalType.BUY):
        self._desired = desired

    def get_current_signal(self) -> TradingSignal:  # noqa: D401 – not a docstring target
        return TradingSignal(
            signal=self._desired,
            price=123.45,
            timestamp=pd.Timestamp.utcnow(),
            indicators={},
        )


class _Results:
    def __init__(self, strat):
        self._strategy = strat


class _FakeBacktest:
    """Mimics the minimal interface that LiveSignalExtractor calls."""

    def __init__(self, _data, strategy_cls, *_, **__):
        self._instance = strategy_cls()

    def run(self):
        return _Results(self._instance)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _patch_backtesting(monkeypatch):
    """Make module believe backtesting is available and supply fake class."""
    import StrateQueue.core.signal_extractor as se

    monkeypatch.setattr(se, "BACKTESTING_AVAILABLE", True, raising=False)
    monkeypatch.setattr(se, "Backtest", _FakeBacktest, raising=False)


def test_insufficient_bars_returns_hold(monkeypatch):
    """len(df) < min_bars_required ⇒ extractor returns HOLD and no error metadata."""
    _patch_backtesting(monkeypatch)

    extractor = LiveSignalExtractor(strategy_class=_DummyStrategy, min_bars_required=2)
    sig = extractor.extract_signal(_slice(1))  # 1 < 2

    assert sig.signal is SignalType.HOLD
    assert sig.metadata == {}


def test_happy_path_delegates_signal(monkeypatch):
    """Extractor should forward the strategy's BUY signal unchanged."""
    _patch_backtesting(monkeypatch)

    extractor = LiveSignalExtractor(_DummyStrategy)
    sig = extractor.extract_signal(_slice(15))  # sufficient history

    assert sig.signal is SignalType.BUY
    assert isinstance(sig, TradingSignal)


def test_signal_type_propagation(monkeypatch):
    """Validate a few non-default SignalType values propagate through extractor."""
    _patch_backtesting(monkeypatch)

    for stype in [SignalType.SELL, SignalType.LIMIT_BUY, SignalType.TRAILING_STOP_SELL]:
        class _S(_DummyStrategy):
            def __init__(self):
                super().__init__(stype)

        sig = LiveSignalExtractor(_S, enable_position_tracking=False).extract_signal(_slice(10))
        assert sig.signal is stype


def test_missing_columns_returns_hold_with_error(monkeypatch):
    """Dropping a required column should return HOLD and embed an error message."""
    _patch_backtesting(monkeypatch)

    bad_df = _slice(12).drop(columns=["Low"])
    sig = LiveSignalExtractor(_DummyStrategy).extract_signal(bad_df)

    assert sig.signal is SignalType.HOLD
    assert "error" in sig.metadata


if __name__ == "__main__":
    pytest.main() 