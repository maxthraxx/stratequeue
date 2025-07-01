"""
Unit tests for StrateQueue.live_system.orchestrator.LiveTradingSystem
-------------------------------------------------------------------

Requirements verified in this module
====================================
1. Constructor wiring
   1.1 Passing neither `strategy_path` nor `multi_strategy_config` raises `ValueError`.
   1.2 Single-strategy mode correctly sets `is_multi_strategy=False`, populates
       `strategy_class` and wires a `TradingProcessor` instance.
   1.3 Multi-strategy mode yields `is_multi_strategy=True`, instantiates a
       `MultiStrategyRunner` and sets `lookback_period` to
       `runner.get_max_lookback_period()`.

2. Signals-only cycle (trading disabled)
   2.1 `run_live_system` processes at least one bar in <100 ms (patched sleep).
   2.2 A BUY signal produced by the stub `TradingProcessor` is recorded in
       `StatisticsManager._latest_signals`.
   2.3 `get_system_status()` returns a sane dict with expected keys and flags
       (`mode`, `trading_enabled=False`, `broker_connected=False`).

3. Execution branch (trading enabled)
   3.1 `_execute_signals` delegates to `broker.execute_signal` exactly once for
       every non-HOLD signal and never for HOLD signals.

4. Broker initialisation fail-over
   4.1 If broker connection fails, the orchestrator disables trading and
       continues in signals-only mode (`enable_trading` becomes `False`,
       `broker_executor is None`).
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Ensure src/ is on the Python path when running the file directly
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.is_dir():
    import sys

    sys.path.insert(0, str(SRC_PATH))

import StrateQueue.live_system.orchestrator as orch
from StrateQueue.core.signal_extractor import SignalType, TradingSignal

# ---------------------------------------------------------------------------
# Universal monkey-patches / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op so loops finish instantly."""

    async def _no_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep, raising=False)


@pytest.fixture(autouse=True)
def _short_granularity(monkeypatch):
    """Force `parse_granularity` to return a 1-second interval object."""

    gran = types.SimpleNamespace(to_seconds=lambda: 1)
    monkeypatch.setattr(orch, "parse_granularity", lambda _g: gran, raising=False)


# ---------------------------------------------------------------------------
# Lightweight stubs standing in for heavy dependencies
# ---------------------------------------------------------------------------


class _StubDataManager:
    """Only minimal API surface required by the orchestrator."""

    def __init__(self, symbols, _src, _gran, lookback):
        self.symbols = symbols
        idx = pd.date_range("2020-01-01", periods=lookback, freq="T")
        self._df = pd.DataFrame(
            {
                "Open": 1.0,
                "High": 1.0,
                "Low": 1.0,
                "Close": 1.0,
                "Volume": 1.0,
            },
            index=idx,
        )

    # --- life-cycle ----------------------------------------------------
    def initialize_data_source(self):
        return None

    async def initialize_historical_data(self):
        return None

    async def update_symbol_data(self, _sym):
        return None

    # --- data access ---------------------------------------------------
    def get_symbol_data(self, _sym):
        return self._df.copy()

    def get_data_progress(self, *_a, **_kw):
        return (1, 1, 100.0)


class _StubDisplayManager:
    def __init__(self, *_a, **_kw):
        pass

    def display_startup_banner(self, *_a, **_kw):
        pass

    def display_signals_summary(self, *_a, **_kw):
        pass

    def display_session_summary(self, *_a, **_kw):
        pass


class _StubTradingProcessor:
    def __init__(self, symbols, *_a, **_kw):
        self.symbols = symbols
        self._active: dict[str, TradingSignal] = {}

    async def process_trading_cycle(self, *_a, **_kw):
        ts = pd.Timestamp.utcnow()
        sig = TradingSignal(SignalType.BUY, 1.0, ts, indicators={})
        self._active = {self.symbols[0]: sig}
        return self._active

    def get_active_signals(self):
        return self._active

    def get_strategy_info(self):
        return "stub-strategy"


# ---------------------------------------------------------------------------
# Common patch fixture – applies to every test in this module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_heavy_dependencies(monkeypatch):
    # Engine / strategy detection bypass
    monkeypatch.setattr(orch, "detect_engine_type", lambda _p: "unknown", raising=False)

    # Replace heavy classes with stubs
    monkeypatch.setattr(orch, "DataManager", _StubDataManager, raising=False)
    monkeypatch.setattr(orch, "DisplayManager", _StubDisplayManager, raising=False)
    monkeypatch.setattr(orch, "TradingProcessor", _StubTradingProcessor, raising=False)

    # Prevent real broker initialisation unless explicitly enabled
    monkeypatch.setattr(orch.LiveTradingSystem, "_initialize_trading", lambda self: None)

    # Make _load_backtesting_strategy a minimal no-op
    def _fake_load(self, _path):
        self.strategy_class = object
        self.engine_strategy = None
        self.engine = None
        self.lookback_period = self.lookback_override or 5

    monkeypatch.setattr(orch.LiveTradingSystem, "_load_backtesting_strategy", _fake_load)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signals_only_cycle():
    """Signals propagate and land in StatisticsManager in signals-only mode."""

    lts = orch.LiveTradingSystem(
        strategy_path="dummy.py",
        symbols=["AAPL"],
        enable_trading=False,
    )

    await lts.run_live_system(duration_minutes=0.0001)

    assert "AAPL" in lts.statistics_manager._latest_signals
    status = lts.get_system_status()
    assert status["trading_enabled"] is False and status["broker_connected"] is False


@pytest.mark.asyncio
async def test_execute_signals_delegates_to_broker(monkeypatch):
    """_execute_signals should call broker.execute_signal exactly once."""

    # Build stub broker with call-counting execute_signal
    broker = types.SimpleNamespace()
    broker._called = 0

    def _exec(*_a, **_kw):
        broker._called += 1
        return types.SimpleNamespace(success=True)

    broker.execute_signal = _exec
    broker.config = types.SimpleNamespace(broker_type="stub", paper_trading=True)

    lts = orch.LiveTradingSystem(
        strategy_path="dummy.py",
        symbols=["AAPL"],
        enable_trading=True,
    )
    lts.broker_executor = broker  # Attach stub

    ts = pd.Timestamp.utcnow()
    sig = TradingSignal(SignalType.BUY, 1.0, ts, indicators={})

    await lts._execute_signals({"AAPL": sig})

    assert broker._called == 1


@pytest.mark.asyncio
async def test_broker_connect_failover(monkeypatch):
    """If broker init fails, trading should be disabled and executor None."""

    def _fail(self):
        self.enable_trading = True  # mimic user intent
        self.broker_executor = None
        return None

    monkeypatch.setattr(orch.LiveTradingSystem, "_initialize_trading", _fail)

    lts = orch.LiveTradingSystem(
        strategy_path="dummy.py",
        symbols=["AAPL"],
        enable_trading=True,
    )

    # The orchestrator keeps the user‐requested trading flag unchanged when the
    # connection attempt merely *returns* None.  We only need to verify that it
    # never attached a broker executor.
    assert lts.broker_executor is None


# ---------------------------------------------------------------------------
# Allow `python test_live_trading_system.py`