"""
PositionSizer – unit-level risk-math verification
================================================
This module **fully specifies** the critical behaviours that must NEVER break.
If any test in this file fails, the sizing logic may place real money at risk.

Critical requirements covered
----------------------------
R1  Trading-strategy override
    • If a `TradingSignal` already supplies a positive `size`, that exact
      dollar amount MUST be returned untouched.

R2  Safety guardrails
    • Returned size is NEVER less than 1 USD.
    • On ANY internal exception the sizer MUST fall back to exactly 100 USD.

R3  FixedDollarSizing
    • Always output its configured constant, irrespective of inputs.

R4  PercentOfCapitalSizing
    • Single-strategy path: uses `account_value` kwarg (default 10 000) and
      clamps to `max_amount`.
    • Multi-strategy path: uses `portfolio_manager.get_strategy_status()`
      → `available_capital` × percentage, then clamps to `max_amount`.

R5  VolatilityBasedSizing
    • With ATR > 0: size = (available_capital × risk_per_trade × price) / ATR,
      floored at 10 USD.
    • With missing or non-positive ATR: delegate 100 % to the fallback
      strategy and return its result.

R6  Runtime strategy swap
    • After calling `PositionSizer.set_strategy(...)` subsequent sizing calls
      MUST route to the new strategy.

All tests below enforce the rules above with **micro-second** stub fixtures –
no live data, network, or heavy libraries are required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Make StrateQueue sources importable when running the file directly
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.is_dir():
    sys.path.insert(0, str(SRC_PATH))

# ---------------------------------------------------------------------------
# Imports from the library under test
# ---------------------------------------------------------------------------
from StrateQueue.core.position_sizer import (
    FixedDollarSizing,
    PercentOfCapitalSizing,
    PositionSizer,
    VolatilityBasedSizing,
)
from StrateQueue.core.signal_extractor import SignalType, TradingSignal


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _signal(**kwargs) -> TradingSignal:
    """Return a simple BUY `TradingSignal` with configurable extras."""
    return TradingSignal(
        signal=SignalType.BUY,
        price=100.0,
        timestamp=pd.Timestamp.utcnow(),
        indicators={},
        **kwargs,
    )


class _PMStub:  # noqa: D101 – minimal stub for PortfolioManager
    """Returns a constant `available_capital` for multi-strategy path tests."""

    def __init__(self, available_capital: float):
        self._cap = available_capital

    def get_strategy_status(self, _sid: str) -> dict:  # noqa: D401 – not a docstring target
        return {"available_capital": self._cap}


# ---------------------------------------------------------------------------
# R1 – Strategy-supplied size override
# ---------------------------------------------------------------------------

def test_signal_size_override_is_respected():
    sizer = PositionSizer()  # default strategy irrelevant – should be bypassed
    sig = _signal(size=250.0)
    assert sizer.get_position_size(None, "AAPL", sig, price=100.0) == 250.0


# ---------------------------------------------------------------------------
# R2 – Guardrails (min 1 USD + 100 USD fallback)
# ---------------------------------------------------------------------------

def test_minimum_position_size_enforced():
    sizer = PositionSizer(FixedDollarSizing(0.5))  # below the $1 floor
    assert sizer.get_position_size(None, "AAPL", _signal(), price=100.0) == pytest.approx(1.0)


def test_emergency_fallback_on_exception(monkeypatch):
    sizer = PositionSizer()

    def _boom(*_, **__):
        raise RuntimeError("simulated sizing failure")

    monkeypatch.setattr(sizer.strategy, "calculate_size", _boom, raising=True)
    assert sizer.get_position_size(None, "AAPL", _signal(), price=100.0) == 100.0


# ---------------------------------------------------------------------------
# R3 – FixedDollarSizing constant output
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("amount", [25.0, 500.0])
def test_fixed_dollar_returns_constant(amount):
    sizer = PositionSizer(FixedDollarSizing(amount))
    assert sizer.get_position_size(None, "AAPL", _signal(), price=200.0) == amount


# ---------------------------------------------------------------------------
# R4 – PercentOfCapitalSizing paths
# ---------------------------------------------------------------------------

def test_percent_of_capital_single_strategy_with_account_value():
    strat = PercentOfCapitalSizing(percentage=0.2, max_amount=1_000.0)
    sizer = PositionSizer(strat)

    result = sizer.get_position_size(
        None, "AAPL", _signal(), price=50.0, account_value=50_000
    )
    assert result == 1_000.0  # 10 000 theoretical but clamped


def test_percent_of_capital_multi_strategy():
    pm = _PMStub(available_capital=2_000)
    strat = PercentOfCapitalSizing(percentage=0.3, max_amount=1_000.0)
    sizer = PositionSizer(strat)

    result = sizer.get_position_size("s1", "AAPL", _signal(), price=100.0, portfolio_manager=pm)
    assert result == pytest.approx(600.0)


def test_percent_of_capital_no_artificial_limit():
    """Test that percentage allocations work without artificial limits when max_amount is None"""
    pm = _PMStub(available_capital=80_000)
    strat = PercentOfCapitalSizing(percentage=0.8)  # 80% allocation, no max_amount limit
    sizer = PositionSizer(strat)

    result = sizer.get_position_size("s1", "AAPL", _signal(), price=100.0, portfolio_manager=pm)
    assert result == pytest.approx(64_000.0)  # 80% of $80k = $64k, not capped at $1k


# ---------------------------------------------------------------------------
# R5 – VolatilityBasedSizing
# ---------------------------------------------------------------------------

def test_vol_based_sizing_uses_atr():
    pm = _PMStub(available_capital=5_000)
    strat = VolatilityBasedSizing(risk_per_trade=0.02)
    sizer = PositionSizer(strat)

    sig = _signal(metadata={"atr": 2.0})
    expected = (5_000 * 0.02 * 50.0) / 2.0  # formula from implementation

    result = sizer.get_position_size("s1", "AAPL", sig, price=50.0, portfolio_manager=pm)
    assert result == pytest.approx(expected)


def test_vol_based_sizing_respects_min_floor():
    strat = VolatilityBasedSizing(risk_per_trade=0.01)
    sizer = PositionSizer(strat)

    sig = _signal(metadata={"atr": 10_000.0})  # enormous ATR → min floor engaged
    assert sizer.get_position_size(None, "AAPL", sig, price=100.0, account_value=1_000) == 10.0


def test_vol_based_sizing_delegates_to_fallback():
    fallback = FixedDollarSizing(123.0)
    strat = VolatilityBasedSizing(fallback_sizing=fallback)
    sizer = PositionSizer(strat)

    sig = _signal()  # no ATR in metadata
    assert sizer.get_position_size(None, "AAPL", sig, price=90.0, account_value=50_000) == 123.0


# ---------------------------------------------------------------------------
# R6 – Runtime strategy swap
# ---------------------------------------------------------------------------

def test_strategy_swap_changes_result():
    sizer = PositionSizer(FixedDollarSizing(50.0))
    assert sizer.get_position_size(None, "AAPL", _signal(), price=100.0) == 50.0

    sizer.set_strategy(FixedDollarSizing(20.0))
    assert sizer.get_position_size(None, "AAPL", _signal(), price=100.0) == 20.0


# ---------------------------------------------------------------------------
# Direct execution hook: `python test_position_sizer.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__])) 