"""
AlpacaBroker Unit-Tests
=======================
Offline micro-tests for ``StrateQueue.brokers.Alpaca.alpaca_broker.AlpacaBroker``.
They run without the real ``alpaca-trade-api`` thanks to the stubbed
implementation in ``tests.unit_tests.brokers.alpaca_stubs``.

Requirements verified in this module
------------------------------------
A. Configuration mapping
   A1  ``_create_alpaca_config`` copies api_key / secret_key / base_url & paper flag.

B. Connection handling
   B1  ``connect`` succeeds and sets ``is_connected`` when TradingClient works.
   B2  ``connect`` returns False and leaves ``is_connected`` False on constructor error.

C. Credential validation
   C1  ``validate_credentials`` happy-path returns True.
   C2  ``APIError`` from client is caught → returns False.

D. Order placement via ``place_order``
   D1  MARKET order succeeds and is reflected in ``get_orders`` output.
   D2  LIMIT order without price fails with error_code ``MISSING_PRICE``.
   D3  Unsupported order type returns error_code ``UNSUPPORTED_ORDER_TYPE``.

E. Order management helpers
   E1  ``cancel_order`` marks order as *canceled* and ``get_order_status`` returns a dict with ``status == "canceled"``.
   E2  ``get_orders(symbol)`` filters correctly.

F. Broker metadata
   F1  ``get_broker_info`` contains expected name and flags.
   F2  ``paper_trading`` flag mirrors config.

G. Utility helpers
   G1  ``normalize_crypto_symbol`` normalises pairs / symbols.
"""

# ---------------------------------------------------------------------------
# Ensure project root & stubs are importable even when executed directly via
# `python3.10 test_alpaca_broker.py` from the tests directory.
# ---------------------------------------------------------------------------

from __future__ import annotations

import sys
from pathlib import Path

# Add repository root to sys.path (four levels up: brokers → unit_tests → tests → repo)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the stub package – must come *before* real AlpacaBroker import so that
# the patch in alpaca_stubs installs its fake modules.
import importlib

try:
    # Preferred import path when executed under pytest (root working directory).
    import tests.unit_tests.brokers.alpaca.alpaca_stubs  # noqa: F401 – side-effects only
except ModuleNotFoundError:  # pragma: no cover – direct execution from sub-dir
    # When the module is run directly (e.g. `python test_alpaca_broker.py`) the
    # parent packages may not be importable.  Fall back to loading the sibling
    # stub file manually so that the real broker can still import.
    import importlib.util as _util  # type: ignore  # noqa: E402
    from pathlib import Path as _Path  # noqa: E402

    _stub_path = _Path(__file__).with_name("alpaca_stubs.py")
    _spec = _util.spec_from_file_location("alpaca_stubs", _stub_path)
    if _spec and _spec.loader:
        _module = _util.module_from_spec(_spec)
        sys.modules["alpaca_stubs"] = _module
        _spec.loader.exec_module(_module)  # type: ignore[attr-defined]

from datetime import datetime  # noqa: E402 – after sys.path manipulation

import pytest  # noqa: E402

from StrateQueue.brokers.broker_base import BrokerConfig, OrderSide, OrderType  # noqa: E402
from StrateQueue.brokers.Alpaca.alpaca_broker import (  # noqa: E402
    AlpacaBroker,
    normalize_crypto_symbol,
)
from StrateQueue.core.signal_extractor import SignalType, TradingSignal  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker():
    """Return a *connected* AlpacaBroker instance backed by fakes."""
    cfg = BrokerConfig("alpaca", credentials={"api_key": "k", "secret_key": "s"})
    broker = AlpacaBroker(cfg)
    assert broker.connect(), "Stub connection should always succeed"
    return broker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_alpaca_config():
    cfg = BrokerConfig(
        "alpaca",
        credentials={"api_key": "K", "secret_key": "S", "base_url": "u"},
        paper_trading=False,
    )
    broker = AlpacaBroker(cfg)
    acfg = broker.alpaca_config
    assert (acfg.api_key, acfg.secret_key, acfg.base_url, acfg.paper) == (
        "K",
        "S",
        "u",
        False,
    )


def test_get_broker_info_contains_required_features():
    info = _make_broker().get_broker_info()
    assert info.name == "Alpaca"
    assert info.supported_features.get("market_orders") is True


def test_connect_sets_state_and_uses_fake_client():
    broker = _make_broker()
    from alpaca.trading.client import TradingClient  # imported from stub

    assert isinstance(broker.trading_client, TradingClient)
    assert broker.is_connected is True


def test_connect_failure_returns_false(monkeypatch):
    # Patch the TradingClient reference *inside* the broker module – the one used at runtime
    def _boom(*_a, **_kw):  # noqa: D401 – raise generic error to simulate failure
        raise Exception("boom")

    monkeypatch.setattr(
        "StrateQueue.brokers.Alpaca.alpaca_broker.TradingClient",
        _boom,
        raising=True,
    )

    bad = AlpacaBroker(BrokerConfig("alpaca"))
    assert bad.connect() is False
    assert bad.is_connected is False


def test_validate_credentials_happy_and_error(monkeypatch):
    broker = _make_broker()
    assert broker.validate_credentials() is True

    # Error path: patch get_account to raise APIError
    from alpaca.trading.client import TradingClient
    from alpaca.common.exceptions import APIError

    def _err(self):  # noqa: D401
        raise APIError("bad creds")

    monkeypatch.setattr(TradingClient, "get_account", _err, raising=False)
    assert broker.validate_credentials() is False


def test_place_market_order_success():
    broker = _make_broker()
    res = broker.place_order("AAPL", OrderType.MARKET, OrderSide.BUY, quantity=1)
    assert res.success is True
    orders = broker.get_orders()
    assert len(orders) == 1
    assert orders[0]["order_type"] == "MARKET"


def test_limit_order_without_price_fails():
    broker = _make_broker()
    res = broker.place_order("AAPL", OrderType.LIMIT, OrderSide.BUY, quantity=1)
    assert res.success is False
    assert res.error_code == "MISSING_PRICE"


def test_unsupported_order_type_fails():
    class _DummyOrderType:
        value = "FOO"

    broker = _make_broker()
    res = broker.place_order("AAPL", _DummyOrderType, OrderSide.BUY, 1)
    assert res.success is False and res.error_code == "UNSUPPORTED_ORDER_TYPE"


def test_cancel_order_and_status_lookup():
    broker = _make_broker()
    res = broker.place_order("AAPL", OrderType.MARKET, OrderSide.BUY, 1)
    oid = res.order_id
    assert broker.cancel_order(oid) is True

    status = broker.get_order_status(oid)
    assert status is not None and status["status"] == "canceled"


def test_get_orders_symbol_filter():
    broker = _make_broker()
    broker.place_order("AAPL", OrderType.MARKET, OrderSide.BUY, 1)
    broker.place_order("MSFT", OrderType.MARKET, OrderSide.BUY, 1)
    assert len(broker.get_orders(symbol="AAPL")) == 1


def test_broker_info_paper_flag_respects_config():
    cfg = BrokerConfig("alpaca", paper_trading=False, credentials={})
    broker = AlpacaBroker(cfg)
    broker.connect()
    assert broker.get_broker_info().paper_trading is False


def test_normalize_crypto_symbol_helper():
    assert normalize_crypto_symbol("btc") == "BTC/USD"
    assert normalize_crypto_symbol("ETH/USD") == "ETH/USD" 