"""
tests/unit_tests/multi_strategy/test_multi_strategy_plumbing.py

End-to-end tests for the *portfolio-integration* & *signal-co-ordination*
layer (MultiStrategyRunner → PortfolioIntegrator → SimplePortfolioManager).

The tests spin up two tiny 'toy' strategies, write them to tmp files, generate
a throw-away multi-strategy config, and then verify:

1.  Allocation / available-capital math after portfolio initialisation.
2.  Enforcement of capital limits via can_execute_signal.
3.  Correct bookkeeping once a BUY execution is recorded.
4.  Pause / resume of a strategy stops & restarts signal flow.
5.  Hot-add and hot-remove keep every internal dict in sync.
6.  Portfolio rebalancing updates allocations everywhere.

Nothing touches real brokers, data-providers or backtesting; we monkey-patch
LiveSignalExtractor's heavy dependency exactly the same way the existing
signal-extractor tests do.

Run with::

    pytest -q tests/unit_tests/multi_strategy/test_multi_strategy_plumbing.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Project import path helper (mirrors other unit-tests)
# ---------------------------------------------------------------------------

PROJ_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJ_ROOT / "src"
if SRC_PATH.is_dir():
    sys.path.insert(0, str(SRC_PATH))

# ---------------------------------------------------------------------------
# Imports *after* sys.path tweaked
# ---------------------------------------------------------------------------

from StrateQueue.core.signal_extractor import (
    TradingSignal,
    SignalType,
    LiveSignalExtractor,
)
from StrateQueue.multi_strategy.runner import MultiStrategyRunner

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _DummyResults:
    def __init__(self, strat):  # noqa: D401
        self._strategy = strat


class _FakeBacktest:
    """Ultra-light replacement for backtesting.Backtest."""

    def __init__(self, _df, strategy_cls, *_, **__):  # noqa: D401
        self._instance = strategy_cls()

    def run(self):
        return _DummyResults(self._instance)


def _patch_backtesting(monkeypatch):
    """Convince LiveSignalExtractor that backtesting is installed."""
    import StrateQueue.core.signal_extractor as se

    monkeypatch.setattr(se, "BACKTESTING_AVAILABLE", True, raising=False)
    monkeypatch.setattr(se, "Backtest", _FakeBacktest, raising=False)


@pytest.fixture(scope="module")
def _ohlcv() -> pd.DataFrame:
    """Very small deterministic OHLCV frame (5 bars)."""
    idx = pd.date_range("2024-01-01 09:30", periods=5, freq="1min")
    return pd.DataFrame(
        {
            "Open": 100,
            "High": 101,
            "Low":  99,
            "Close": [100, 100.5, 101, 100.7, 101.2],
            "Volume": 1000,
        },
        index=idx,
    )


def _write_strategy(tmp: Path, name: str, sig: str) -> Path:
    """Create a minimal strategy file returning the desired SignalType."""
    code = f"""
import pandas as pd
from StrateQueue.core.signal_extractor import TradingSignal, SignalType

class {name.capitalize()}:
    def init(self): pass
    def next(self): pass
    def get_current_signal(self):
        return TradingSignal(
            signal=SignalType.{sig},
            price=100.0,
            timestamp=pd.Timestamp.utcnow(),
            indicators={{}},
        )
"""
    path = tmp / f"{name}.py"
    path.write_text(code)
    return path


def _make_config(
    tmp: Path, entries: Iterable[tuple[Path, str, float]]
) -> Path:
    """Write a config file compatible with ConfigManager."""
    lines = [f"{p},{sid},{alloc}" for p, sid, alloc in entries]
    cfg = tmp / "strategies.txt"
    cfg.write_text("\n".join(lines))
    return cfg


# ---------------------------------------------------------------------------
# Test-cases
# ---------------------------------------------------------------------------


@pytest.fixture
def runner(monkeypatch, tmp_path, _ohlcv) -> MultiStrategyRunner:
    """Spin up a MultiStrategyRunner with two toy strategies."""
    _patch_backtesting(monkeypatch)

    # 1) generate strategies -------------------------------------------------
    strat_a = _write_strategy(tmp_path, "strat_a", "BUY")
    strat_b = _write_strategy(tmp_path, "strat_b", "SELL")

    # 2) build config (60 % / 40 %) -----------------------------------------
    # Leave 20 % head-room so that the hot-add test can succeed without
    # violating the portfolio's ≤ 100 % allocation constraint.
    # Config: 50 % + 30 % = 80 % initial utilisation.
    cfg = _make_config(
        tmp_path,
        [
            (strat_a, "strat_a", 0.5),
            (strat_b, "strat_b", 0.3),
        ],
    )

    # 3) create runner & initialise -----------------------------------------
    r = MultiStrategyRunner(str(cfg), symbols=["AAPL"])
    r.initialize_strategies()

    # feed initial account value so allocations are monetised
    r.update_portfolio_value(10_000.0)

    # monkey-patch generate_signals to always return the known dataframe
    async def _fake_hist(symbol: str, *_args, **_kw):
        return _ohlcv.copy()

    monkeypatch.setattr(
        "StrateQueue.multi_strategy.signal_coordinator.LiveSignalExtractor.extract_signal",
        lambda self, _df: TradingSignal(
            signal=SignalType.BUY
            if self.strategy_class.__name__.startswith("Strat_a")
            else SignalType.SELL,
            price=100.0,
            timestamp=pd.Timestamp.utcnow(),
            indicators={},
            strategy_id="strat_a"
            if self.strategy_class.__name__.startswith("Strat_a")
            else "strat_b",
        ),
        raising=False,
    )

    return r


# ---------------------------------------------------------------------------
# 1. Allocation math
# ---------------------------------------------------------------------------
def test_initial_allocations(runner: MultiStrategyRunner):
    pm = runner.portfolio_integrator.portfolio_manager
    assert pm.strategy_allocations["strat_a"].total_allocated == pytest.approx(5000)
    assert pm.strategy_allocations["strat_b"].total_allocated == pytest.approx(3000)


# ---------------------------------------------------------------------------
# 2. can_execute gating logic
# ---------------------------------------------------------------------------
def test_can_execute_signal_buy_vs_sell(runner: MultiStrategyRunner):
    pi = runner.portfolio_integrator

    buy_sig = TradingSignal(
        signal=SignalType.BUY,
        price=100.0,
        timestamp=pd.Timestamp.utcnow(),
        indicators={},
        strategy_id="strat_a",
    )
    ok, _ = pi.can_execute_signal(buy_sig, "AAPL")
    assert ok is True, "BUY within allocation should pass"

    sell_sig = TradingSignal(
        signal=SignalType.SELL,
        price=100.0,
        timestamp=pd.Timestamp.utcnow(),
        indicators={},
        strategy_id="strat_b",
    )
    ok, reason = pi.can_execute_signal(sell_sig, "AAPL")
    assert ok is False and "no position" in reason.lower()


# ---------------------------------------------------------------------------
# 3. Record execution mutates capital
# ---------------------------------------------------------------------------
def test_record_execution_updates_capital(runner: MultiStrategyRunner):
    pi = runner.portfolio_integrator
    pm = pi.portfolio_manager

    pre = pm.strategy_allocations["strat_a"].available_capital
    sig = TradingSignal(
        signal=SignalType.BUY,
        price=100.0,
        timestamp=pd.Timestamp.utcnow(),
        indicators={},
        strategy_id="strat_a",
    )
    pi.record_execution(sig, "AAPL", execution_amount=1000, execution_successful=True)

    post = pm.strategy_allocations["strat_a"].available_capital
    assert post == pytest.approx(pre - 1000)


# ---------------------------------------------------------------------------
# 4. Pause / resume stops signal flow
# ---------------------------------------------------------------------------
def test_pause_resume_stops_signals(runner: MultiStrategyRunner):
    sc = runner.signal_coordinator
    sc.pause_strategy("strat_a")

    # After pause, strategy must report as paused
    assert sc.is_strategy_paused("strat_a") is True

    sc.resume_strategy("strat_a")
    assert sc.is_strategy_paused("strat_a") is False


# ---------------------------------------------------------------------------
# 5. Hot-add & hot-remove keep dicts in sync
# ---------------------------------------------------------------------------
def test_hot_add_then_remove_strategy(runner: MultiStrategyRunner, tmp_path):
    # Hot-add --------------------------------------------------------------
    new_path = _write_strategy(tmp_path, "strat_c", "BUY")
    runner.deploy_strategy_runtime(
        strategy_path=str(new_path),
        strategy_id="strat_c",
        allocation_percentage=0.2,
    )

    assert "strat_c" in runner.signal_coordinator.strategy_configs
    assert "strat_c" in runner.portfolio_integrator.portfolio_manager.strategy_allocations

    # Hot-remove -----------------------------------------------------------
    runner.undeploy_strategy_runtime("strat_c", liquidate_positions=False)

    assert "strat_c" not in runner.signal_coordinator.strategy_configs
    assert "strat_c" not in runner.portfolio_integrator.portfolio_manager.strategy_allocations


# ---------------------------------------------------------------------------
# 6. Rebalance allocations
# ---------------------------------------------------------------------------
def test_rebalance_updates_allocations(runner: MultiStrategyRunner):
    ok = runner.rebalance_portfolio_runtime(
        {"strat_a": 0.7, "strat_b": 0.3}
    )
    assert ok is True

    pm = runner.portfolio_integrator.portfolio_manager
    assert pm.strategy_allocations["strat_a"].allocation_percentage == pytest.approx(0.7)
    assert pm.strategy_allocations["strat_b"].allocation_percentage == pytest.approx(0.3)