"""
IBKRBroker Unit-Tests (offline)
================================
Micro-tests for ``StrateQueue.brokers.IBKR.ibkr_broker.IBKRBroker`` that run
without a running TWS / ib_insync installation – they rely on the stub module
``tests.unit_tests.brokers.ibkr.ibkr_stubs``.

Covered requirements
--------------------
1. Connection lifecycle – happy path & failure branch.
2. Credential validation – success, error, and keep_open behaviour.
3. Signal execution – BUY TradingSignal is translated into an OrderManager
   call (spy), contract helper patched.
4. Delegation helpers – get_account_info and get_orders.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Ensure repository root on sys.path *and* install stubs BEFORE real import.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the stub module *before* real broker import so the fake ``ib_insync``
# tree is registered.  When executed under pytest from repo root this import
# works; when the file is run directly from within its own directory the
# dotted path fails – fall back to manual loading like the Alpaca tests.
try:
    import tests.unit_tests.brokers.ibkr.ibkr_stubs  # noqa: F401 – side-effects only
except ModuleNotFoundError:  # pragma: no cover – direct execution edge-case
    import importlib.util as _util  # type: ignore

    _stub_path = Path(__file__).with_name("ibkr_stubs.py")
    _spec = _util.spec_from_file_location("ibkr_stubs", _stub_path)
    if _spec and _spec.loader:
        _module = _util.module_from_spec(_spec)
        sys.modules["ibkr_stubs"] = _module
        _spec.loader.exec_module(_module)  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Real imports (now safe because stubs are in place)
# ---------------------------------------------------------------------------
import pytest

from StrateQueue.brokers.broker_base import BrokerConfig, OrderSide, OrderType, OrderResult
from StrateQueue.brokers.IBKR.ibkr_broker import IBKRBroker
from StrateQueue.core.signal_extractor import TradingSignal, SignalType


# ---------------------------------------------------------------------------
# Helper – create broker (optionally already connected)
# ---------------------------------------------------------------------------

def _make_broker(connected: bool = True) -> IBKRBroker:
    cfg = BrokerConfig(
        "ibkr",
        paper_trading=True,
        credentials={"host": "127.0.0.1", "port": 7497, "client_id": 1},
    )
    broker = IBKRBroker(cfg)
    if connected:
        assert broker.connect(), "Stub IB.connect should succeed"
    return broker


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

def test_connect_success_creates_managers():
    br = _make_broker()
    assert br.is_connected
    assert br.order_manager is not None
    assert br.account_manager is not None
    assert br.position_manager is not None


def test_connect_failure_returns_false(monkeypatch):
    import ib_insync

    def _boom(self, *a, **kw):  # noqa: D401 – boom stub
        raise Exception("cannot connect")

    monkeypatch.setattr(ib_insync.IB, "connect", _boom, raising=True)

    br = _make_broker(connected=False)
    assert br.connect() is False
    assert br.is_connected is False


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------

def test_validate_credentials_happy_keep_open():
    br = _make_broker(connected=False)
    assert br.validate_credentials(keep_open=True) is True
    # keep_open flag means we should now be connected
    assert br.is_connected is True


def test_validate_credentials_error(monkeypatch):
    import ib_insync

    # Return empty summary list ⇒ validation fails
    monkeypatch.setattr(ib_insync.IB, "accountSummary", lambda self: [], raising=True)
    br = _make_broker()
    assert br.validate_credentials() is False


# ---------------------------------------------------------------------------
# Execute signal routing (patch contract factory + OrderManager spy)
# ---------------------------------------------------------------------------

def test_execute_signal_buy_routes_to_order_manager(monkeypatch):
    br = _make_broker()

    # Patch contract creator referenced inside execute_signal
    def _fake_contract(_ib, _sym):
        return SimpleNamespace(symbol=_sym), "STK"

    monkeypatch.setattr(
        "StrateQueue.brokers.IBKR.contracts.create_contract_with_detection",
        _fake_contract,
        raising=False,
    )

    # Spy on OrderManager.place_order to capture kwargs
    captured: dict = {}

    def _spy_place(self, **kwargs):  # noqa: D401 – spy func mirrors signature partly
        captured.update(kwargs)
        return OrderResult(success=True, order_id="1", timestamp=datetime.utcnow())

    monkeypatch.setattr(br.order_manager.__class__, "place_order", _spy_place, raising=False)

    sig = TradingSignal(signal=SignalType.BUY, price=50.0, timestamp=datetime.utcnow(), indicators={})
    res = br.execute_signal("AAPL", sig)

    assert res.success is True
    assert captured["order_type"] is OrderType.MARKET
    assert captured["side"] == OrderSide.BUY
    assert captured["quantity"] >= 1


# ---------------------------------------------------------------------------
# Delegation helpers
# ---------------------------------------------------------------------------

def test_get_account_info_delegates():
    br = _make_broker()
    info = br.get_account_info()
    assert info is not None and info.account_id == "DU123456"


def test_get_orders_symbol_filter(monkeypatch):
    br = _make_broker()

    # Provide controlled response from OrderManager.get_open_orders
    monkeypatch.setattr(
        br.order_manager.__class__,
        "get_open_orders",
        lambda self, symbol=None: [
            o for o in ({"symbol": "MSFT"}, {"symbol": "AAPL"}) if symbol in (None, o["symbol"])
        ],
        raising=False,
    )

    assert len(br.get_orders(symbol="AAPL")) == 1 