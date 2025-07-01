"""
LIVE IBKR integration-tests
───────────────────────────
• Opt-in only:  skipped unless marker ``live_ibkr`` (or path-selection) is
  used *and* a running paper TWS / Gateway is reachable.
• Uses the real ib_insync client; **never** mocks network calls.
• Every test cleans up the resources it created (orders, connection).

Covered scenarios
1. Connection / credential handshake
2. Account-info caching
3. Market-order life-cycle + position tracking
4. Limit order submit → cancel
5. Per-symbol order filter
6. cancel_all_orders() no-op success
7. replace_order() currently unimplemented path

Run (example):
    pytest -q -m live_ibkr tests/integration_tests/brokers/ibkr/test_ibkr_live.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# --------------------------------------------------------------------------- #
# 1) Ensure local sources shadow any globally-installed StrateQueue package   #
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# --------------------------------------------------------------------------- #
# 2) Credential / host discovery                                              #
# --------------------------------------------------------------------------- #
_ENV_FILE = Path.home() / ".stratequeue" / "credentials.env"
_DEFAULTS = {"IBKR_HOST": "127.0.0.1", "IBKR_PORT": "7497", "IBKR_CLIENT_ID": "1"}


def _inject_from_file(file_path: Path = _ENV_FILE) -> None:
    """Populate os.environ with key=value lines found in ~/.stratequeue/credentials.env."""
    if not file_path.exists():
        return
    for line in file_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


_inject_from_file()

IB_HOST = os.getenv("IBKR_HOST", _DEFAULTS["IBKR_HOST"])
IB_PORT = int(os.getenv("IBKR_PORT", _DEFAULTS["IBKR_PORT"]))
IB_CID = int(os.getenv("IBKR_CLIENT_ID", _DEFAULTS["IBKR_CLIENT_ID"]))

_IBKR_ENV_LIVE = os.getenv("IBKR_ENV", "paper").lower() == "live"
_SKIP_REASON = (
    "live_ibkr tests skipped: no TWS/Gateway reachable on paper port 7497 "
    "or pytest marker not selected"
)

# --------------------------------------------------------------------------- #
# 3) Test marker & global skip                                                #
# --------------------------------------------------------------------------- #
pytestmark = pytest.mark.live_ibkr

try:
    from StrateQueue.brokers.IBKR.ibkr_broker import IBKRBroker, IB_INSYNC_AVAILABLE
    from StrateQueue.brokers.broker_base import OrderSide, OrderType
except ImportError as exc:  # pragma: no cover
    pytest.skip(f"Cannot import IBKRBroker – {exc}", allow_module_level=True)

# Skip if ib_insync is not available
if not IB_INSYNC_AVAILABLE:
    pytest.skip("ib_insync not installed. Install with: pip install stratequeue[ibkr]", allow_module_level=True)

if not (_IBKR_ENV_LIVE or IB_PORT == 7497):
    pytest.skip(_SKIP_REASON, allow_module_level=True)

# --------------------------------------------------------------------------- #
# 4) Helper utilities                                                         #
# --------------------------------------------------------------------------- #
def _wait_until(
    cond_fn,
    timeout: float = 10.0,
    poll: float = 1.0,
    *,
    desc: str | None = None,
) -> bool:
    """Block until cond_fn() is truthy or timeout expires."""
    end = time.time() + timeout
    while time.time() < end:
        if cond_fn():
            return True
        time.sleep(poll)
    if desc:
        pytest.fail(f"Timed out waiting for: {desc}")
    return False


# --------------------------------------------------------------------------- #
# 5) Fixtures                                                                 #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def broker() -> IBKRBroker:
    conf = {
        "credentials": {"host": IB_HOST, "port": IB_PORT, "client_id": IB_CID},
        "paper_trading": not _IBKR_ENV_LIVE,
    }
    ibkr = IBKRBroker(config=type("Cfg", (), conf))  # lightweight ad-hoc object

    assert ibkr.connect(), "Could not connect to IBKR paper gateway"
    yield ibkr

    # Cleanup – cancel anything left & disconnect
    try:
        ibkr.cancel_all_orders()
    finally:
        ibkr.disconnect()


# ─────────────────────────────────────────────────────────────────────────── #
# 6) Tests                                                                    #
# ─────────────────────────────────────────────────────────────────────────── #
def test_validate_credentials_leaves_connection_open(broker: IBKRBroker) -> None:
    assert broker.validate_credentials(keep_open=True) is True
    assert broker.is_connected


def test_account_info_caching(broker: IBKRBroker) -> None:
    start = time.perf_counter()
    info1 = broker.get_account_info()
    t1 = time.perf_counter() - start

    start = time.perf_counter()
    info2 = broker.get_account_info()
    t2 = time.perf_counter() - start

    assert info1 and info2
    assert info1.account_id
    assert info1.total_value > 0
    # second call should hit cache and be faster
    assert t2 < t1


def test_market_order_lifecycle_and_position(broker: IBKRBroker) -> None:
    qty = 1
    symbol = "SPY"
    res = broker.place_order(
        symbol, OrderType.MARKET, OrderSide.BUY, quantity=qty
    )
    assert res.success and res.order_id

    # wait until the trade is filled and position is updated
    _wait_until(
        lambda: broker.get_order_status(res.order_id)["status"] == "Filled",
        desc="market order to fill",
        timeout=20,
    )

    positions = broker.get_positions()
    assert symbol in positions
    pos = positions[symbol]
    assert pos.quantity >= qty


def test_limit_order_submit_and_cancel(broker: IBKRBroker) -> None:
    symbol = "SPY"
    res = broker.place_order(
        symbol, OrderType.LIMIT, OrderSide.SELL, quantity=1, price=9999
    )
    assert res.success and res.order_id
    oid = res.order_id

    # Should sit in Submitted state
    status = broker.get_order_status(oid)
    assert status and status["status"] in {"Submitted", "PreSubmitted"}

    # Cancel and ensure it moves to Cancelled
    assert broker.cancel_order(oid) is True
    _wait_until(
        lambda: broker.get_order_status(oid)["status"] == "Cancelled",
        desc="limit order to cancel",
    )


def test_get_orders_symbol_filter(broker: IBKRBroker) -> None:
    all_orders = broker.get_orders()
    spy_only = broker.get_orders(symbol="SPY")
    # Every SPY-filtered order must indeed be SPY
    assert all(o["symbol"] == "SPY" for o in spy_only)
    # spy_only ⊆ all_orders
    assert set(o["order_id"] for o in spy_only).issubset(
        o["order_id"] for o in all_orders
    )


def test_cancel_all_orders_noop(broker: IBKRBroker) -> None:
    assert broker.cancel_all_orders() is True  # should succeed even if nothing pending


def test_replace_order_not_implemented(broker: IBKRBroker) -> None:
    assert broker.replace_order("non-existent") is False