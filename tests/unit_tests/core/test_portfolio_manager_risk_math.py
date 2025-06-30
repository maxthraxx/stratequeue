"""
SimplePortfolioManager – extended risk-math verification
=======================================================
This file plugs the *remaining* holes in the portfolio-manager coverage.
If **any** test in this file fails, the engine could allocate or free
capital incorrectly.

Critical requirements covered
-----------------------------
R1  update_account_value
    • Allocated/available capital recalculated correctly – *no accumulation*.

R2  Boundary can_buy
    • Exactly exhausts capital ⇒ OK.
    • Exceed by $0.01 ⇒ rejected.

R3  Cross-strategy independence
    • Two strategies can buy the *same* symbol; their buckets stay isolated.

R4  can_sell quantity validation
    • Selling more shares than held or selling a symbol owned only by
      another strategy must be rejected with a helpful reason.

R5  Cross-strategy integrity after sells
    • Holder sets update correctly when one strategy exits and the other
      still holds.

R6  Rebalance downward while overspent
    • Rebalancing to a lower weight succeeds but blocks further buys
      until cash is freed.

R7  Hot-add after trading started
    • New strategy inherits current `account_value` when calculating its
      initial `total_allocated`.

R8  validate_allocations
    • Detects individual out-of-range weights and totals >101 %.
      Warns (doesn't fail) when totals ≪100 %.

R9  get_strategy_status / get_all_status
    • Returned dicts contain accurate, internally-consistent numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make src/ importable when the file is run directly
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC = PROJECT_ROOT / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

from StrateQueue.core.portfolio_manager import SimplePortfolioManager  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pm() -> SimplePortfolioManager:  # noqa: D401 – not a docstring target
    """Two-strategy PM with $25 000 equity (s1 40 %, s2 60 %)."""
    mgr = SimplePortfolioManager({"s1": 0.4, "s2": 0.6})
    mgr.update_account_value(25_000)
    return mgr


# ---------------------------------------------------------------------------
# R1 – update_account_value
# ---------------------------------------------------------------------------

def test_update_account_value_recalculates_allocations(pm: SimplePortfolioManager):
    s1 = pm.strategy_allocations["s1"]
    s2 = pm.strategy_allocations["s2"]

    assert s1.total_allocated == pytest.approx(10_000)
    assert s2.total_allocated == pytest.approx(15_000)

    # Call again with a different equity → values must overwrite, not accumulate
    pm.update_account_value(30_000)
    assert s1.total_allocated == pytest.approx(12_000)
    assert s2.total_allocated == pytest.approx(18_000)


# ---------------------------------------------------------------------------
# R2 – can_buy boundary amounts
# ---------------------------------------------------------------------------

def test_can_buy_exact_allocation_is_ok(pm: SimplePortfolioManager):
    avail = pm.strategy_allocations["s1"].available_capital
    ok, _ = pm.can_buy("s1", "AAPL", avail)
    assert ok


def test_can_buy_one_cent_too_much_is_rejected(pm: SimplePortfolioManager):
    avail = pm.strategy_allocations["s1"].available_capital
    ok, reason = pm.can_buy("s1", "AAPL", avail + 0.01)
    assert not ok and "insufficient capital" in reason.lower()


# ---------------------------------------------------------------------------
# R3 – Cross-strategy isolation
# ---------------------------------------------------------------------------

def test_two_strategies_can_buy_same_symbol(pm: SimplePortfolioManager):
    # Each strategy evaluated against its own bucket
    ok1, _ = pm.can_buy("s1", "TSLA", 9_000)
    ok2, _ = pm.can_buy("s2", "TSLA", 14_000)
    assert ok1 and ok2  # within 10 k / 15 k allowances

    pm.record_buy("s1", "TSLA", 9_000)
    pm.record_buy("s2", "TSLA", 14_000)

    assert pm.strategy_allocations["s1"].available_capital == pytest.approx(1_000)
    assert pm.strategy_allocations["s2"].available_capital == pytest.approx(1_000)


# ---------------------------------------------------------------------------
# R4 – can_sell quantity checks
# ---------------------------------------------------------------------------

def test_cannot_sell_more_than_held(pm: SimplePortfolioManager):
    pm.record_buy("s1", "AAPL", amount=1_000, quantity=10)

    ok, reason = pm.can_sell("s1", "AAPL", quantity=20)  # >10
    assert not ok and "only owns" in reason.lower()


def test_cannot_sell_symbol_owned_by_other_strategy(pm: SimplePortfolioManager):
    pm.record_buy("s2", "NFLX", amount=500, quantity=5)
    ok, reason = pm.can_sell("s1", "NFLX", quantity=1)
    assert not ok and "no position" in reason.lower()


# ---------------------------------------------------------------------------
# R5 – Holder set integrity
# ---------------------------------------------------------------------------

def test_holders_update_when_one_exits(pm: SimplePortfolioManager):
    pm.record_buy("s1", "TSLA", 2_000, quantity=2)
    pm.record_buy("s2", "TSLA", 2_000, quantity=2)

    assert pm.get_all_symbol_holders("TSLA") == {"s1", "s2"}

    pm.record_sell("s1", "TSLA", 2_200, quantity=2)  # s1 exits
    assert pm.get_all_symbol_holders("TSLA") == {"s2"}

    pos = pm.strategy_allocations["s2"].positions["TSLA"]
    assert pos.quantity == 2  # s2 untouched


# ---------------------------------------------------------------------------
# R6 – Rebalance downward while overspent
# ---------------------------------------------------------------------------

def test_rebalance_downward_blocks_future_buys(pm: SimplePortfolioManager):
    # Overspend s1: 8 000 > 10 000 allocation
    pm.record_buy("s1", "IBM", 8_000)

    # Rebalance: s1 now limited to 30 % of $25 000 → $7 500 cap
    assert pm.rebalance_allocations({"s1": 0.3, "s2": 0.7})  # lower s1 cap to 7 500
    ok, reason = pm.can_buy("s1", "IBM", 1)
    assert not ok and "insufficient capital" in reason.lower()


# ---------------------------------------------------------------------------
# R7 – Hot-add after trading started
# ---------------------------------------------------------------------------

def test_hot_add_inherits_current_account_value(pm: SimplePortfolioManager):
    pm.record_buy("s1", "AAPL", 1_000)
    pm.record_buy("s2", "GOOG", 2_000)

    # Add a small 0.9 % allocation (allowed because total stays < 101 %)
    assert pm.add_strategy_runtime("s3", 0.009)
    alloc = pm.strategy_allocations["s3"]
    assert alloc.total_allocated == pytest.approx(225)  # 0.009 × 25 000


# ---------------------------------------------------------------------------
# R8 – validate_allocations edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "weights, expect_ok",
    [
        ({"s1": 1.2}, False),                # individual >100 %
        ({"s1": 0.8, "s2": 0.4}, False),    # totals >101 %
        ({"s1": 0.3, "s2": 0.1}, True),      # totals 40 %
    ],
)
def test_validate_allocations(weights, expect_ok, caplog):
    pm = SimplePortfolioManager(weights)
    result = pm.validate_allocations()
    assert result is expect_ok

    if not expect_ok:
        # Should log at least one ERROR
        assert any(rec.levelname == "ERROR" for rec in caplog.records)


# ---------------------------------------------------------------------------
# R9 – get_strategy_status accuracy
# ---------------------------------------------------------------------------

def test_get_strategy_status_returns_consistent_numbers(pm: SimplePortfolioManager):
    pm.record_buy("s1", "MSFT", 2_000, quantity=10)  # avg cost 200
    status = pm.get_strategy_status("s1")

    assert status["allocation_percentage"] == pytest.approx(0.4)
    assert status["total_allocated"] == pytest.approx(10_000)
    assert status["total_spent"] == pytest.approx(2_000)
    assert status["available_capital"] == pytest.approx(8_000)
    assert status["held_symbols"] == ["MSFT"]
    assert status["positions"]["MSFT"]["avg_cost"] == pytest.approx(200)


# ---------------------------------------------------------------------------
# Direct execution hook
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__])) 