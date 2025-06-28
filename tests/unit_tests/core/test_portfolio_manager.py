"""
Unit tests for StrateQueue.core.portfolio_manager.SimplePortfolioManager
-----------------------------------------------------------------------
These tests focus only on the *internal* bookkeeping logic of the portfolio
manager.  No real broker, market data, or file-system interaction is ever
performed.

Requirements verified in this module
====================================
1. Allocation & capital tracking
   1.1 A strategy *can* buy when the requested amount is ≤ its available capital.
   1.2 A strategy *cannot* buy when the requested amount exceeds its available
       capital – an explanatory message is returned.

2. Position existence & sell permissions
   2.1 Attempting to sell a symbol for which the strategy has **no** position
       fails with an appropriate reason.

3. `record_buy` bookkeeping
   3.1 `total_spent` increases by the amount spent.
   3.2 Available capital decreases accordingly.
   3.3 A new `StrategyPosition` is created/updated with correct quantity,
       cost basis, and average cost.

4. `record_sell` bookkeeping
   4.1 A *full* position sell removes the symbol from the positions dict and
       reduces `total_spent` by the sale proceeds.
   4.2 A *partial* position sell keeps the position but reduces quantity and
       cost basis proportionally.

5. Runtime strategy management
   5.1 `add_strategy_runtime` refuses to add an allocation that causes the
       portfolio to exceed 101 % total allocation (allowing a 1 % buffer).
   5.2 It succeeds when the new total allocation stays within the 101 % limit.
   5.3 `remove_strategy_runtime` successfully removes a strategy ID from the
       portfolio (even if it still holds positions when `liquidate_positions`
       is False).

6. Rebalancing
   6.1 Rebalancing to a valid set of weights updates both the allocation
       percentages *and* the pre-computed dollar amounts.
   6.2 Rebalancing to weights summing to >100 % is rejected and the original
       percentages are left intact (rollback behaviour).
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure src/ is on the Python path when running the file directly
# (mirrors helper block used in integration tests)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.exists() and SRC_PATH.is_dir():
    sys.path.insert(0, str(SRC_PATH))

import pytest

from StrateQueue.core.portfolio_manager import SimplePortfolioManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pm() -> SimplePortfolioManager:
    """Fresh portfolio manager with two strategies and $10 000 equity."""
    manager = SimplePortfolioManager({"s1": 0.4, "s2": 0.6})
    manager.update_account_value(10_000)
    return manager


# ---------------------------------------------------------------------------
# can_buy / can_sell
# ---------------------------------------------------------------------------


def test_can_buy_within_allocation_returns_true(pm: SimplePortfolioManager):
    ok, reason = pm.can_buy("s1", "AAPL", amount=1_000)
    assert ok and reason == "OK"


def test_can_buy_exceeding_allocation_returns_false(pm: SimplePortfolioManager):
    ok, reason = pm.can_buy("s1", "AAPL", amount=5_000)  # > $4 000 allocation
    assert not ok and "insufficient capital" in reason.lower()


def test_can_sell_without_position_returns_false(pm: SimplePortfolioManager):
    ok, reason = pm.can_sell("s1", "AAPL", quantity=1)
    assert not ok and "no position" in reason.lower()


# ---------------------------------------------------------------------------
# record_buy / record_sell
# ---------------------------------------------------------------------------


def test_record_buy_updates_spent_and_position(pm: SimplePortfolioManager):
    pm.record_buy("s1", "AAPL", amount=1_500, quantity=10)

    alloc = pm.strategy_allocations["s1"]
    pos = alloc.positions["AAPL"]

    assert alloc.total_spent == pytest.approx(1_500)
    assert alloc.available_capital == pytest.approx(4_000 - 1_500)
    assert pos.quantity == 10
    assert pos.avg_cost == pytest.approx(150.0)


def test_record_sell_full_position_removes_position(pm: SimplePortfolioManager):
    pm.record_buy("s1", "AAPL", amount=1_500, quantity=10)
    pm.record_sell("s1", "AAPL", amount=1_800, quantity=10)

    alloc = pm.strategy_allocations["s1"]
    assert "AAPL" not in alloc.positions
    assert alloc.total_spent == pytest.approx(1_500 - 1_800)


def test_record_sell_partial_position_updates_cost(pm: SimplePortfolioManager):
    pm.record_buy("s1", "AAPL", amount=1_000, quantity=10)  # avg cost 100
    pm.record_sell("s1", "AAPL", amount=400, quantity=4)  # sell 4 shares

    pos = pm.strategy_allocations["s1"].positions["AAPL"]
    assert pos.quantity == 6
    assert pos.total_cost == pytest.approx(600)  # 60 % of original cost
    assert pos.avg_cost == pytest.approx(100)


# ---------------------------------------------------------------------------
# Hot-add / hot-remove strategy management
# ---------------------------------------------------------------------------


def test_add_strategy_runtime_allocation_limits(pm: SimplePortfolioManager):
    # Anything that pushes total allocation > 101 % should fail
    assert not pm.add_strategy_runtime("s3", 0.10)  # 110 %
    assert not pm.add_strategy_runtime("s3", 0.05)  # 105 %
    assert not pm.add_strategy_runtime("s3", 0.02)  # 102 %

    # 100.9 % is within the 1 % buffer and should succeed
    assert pm.add_strategy_runtime("s3", 0.009)
    assert "s3" in pm.strategy_allocations


def test_remove_strategy_runtime_success(pm: SimplePortfolioManager):
    pm.record_buy("s1", "AAPL", amount=500)  # create a position
    assert pm.remove_strategy_runtime("s1", liquidate_positions=False)
    assert "s1" not in pm.strategy_allocations


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------


def test_rebalance_allocations_success(pm: SimplePortfolioManager):
    assert pm.rebalance_allocations({"s1": 0.3, "s2": 0.7})
    assert pm.strategy_allocations["s1"].allocation_percentage == pytest.approx(0.3)
    assert pm.strategy_allocations["s2"].allocation_percentage == pytest.approx(0.7)
    assert pm.strategy_allocations["s1"].total_allocated == pytest.approx(3_000)
    assert pm.strategy_allocations["s2"].total_allocated == pytest.approx(7_000)


def test_rebalance_allocations_sum_gt_100_rolls_back(pm: SimplePortfolioManager):
    original = {
        sid: alloc.allocation_percentage for sid, alloc in pm.strategy_allocations.items()
    }

    assert not pm.rebalance_allocations({"s1": 0.7, "s2": 0.7})  # 140 %

    assert {
        sid: alloc.allocation_percentage for sid, alloc in pm.strategy_allocations.items()
    } == original


# ---------------------------------------------------------------------------
# Allow direct execution: `python test_portfolio_manager.py`
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import pytest as _pytest

    # Run only this file's tests.  Use exit code for shell integration.
    _pytest_args = [__file__]
    raise SystemExit(_pytest.main(_pytest_args)) 