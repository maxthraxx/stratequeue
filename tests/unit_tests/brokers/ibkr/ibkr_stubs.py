"""
Stub replacements for the *ib_insync* package used by IBKRBroker.

This module injects lightweight fake implementations of the classes and
functions that StrateQueue's IBKR integration touches so that unit-tests can
run fully offline (no TWS/Gateway, no ib_insync wheel).

Import this file *before* importing ``StrateQueue.brokers.IBKR.ibkr_broker`` in
any test.  A convenient way is to simply place
``import tests.unit_tests.brokers.ibkr.ibkr_stubs  # noqa: F401`` at the top of
the test module – the side-effects below will register the stubs in
``sys.modules``.
"""

from __future__ import annotations

import gc
import sys
import types
import uuid
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Fake Trade / Order classes – provide only the attributes referenced by
# StrateQueue code (orderId, orderStatus, etc.).
# ---------------------------------------------------------------------------

class _FakeOrder:  # noqa: D401 – simple attribute bag
    def __init__(self, **kwargs):
        # Copy kwargs into the instance dict for convenient dot-access.
        self.__dict__.update(kwargs)
        # ``ibkr_broker`` will assign ``orderId`` later; initialise to None.
        self.orderId: int | None = None


class _FakeContract(SimpleNamespace):
    """Minimal stand-in for ib_insync.Contract objects."""

    def __init__(self, symbol: str, secType: str, exchange: str, currency: str):
        super().__init__(
            symbol=symbol.upper(),
            secType=secType.upper(),
            exchange=exchange.upper(),
            currency=currency.upper(),
            primaryExchange=exchange.upper(),
        )


class _FakeStock(_FakeContract):  # noqa: D401 – keep ib_insync naming
    def __init__(self, symbol: str, exchange: str = "SMART", currency: str = "USD"):
        super().__init__(symbol, "STK", exchange, currency)


class _FakeCrypto(_FakeContract):  # noqa: D401
    def __init__(self, symbol: str, exchange: str = "PAXOS", currency: str = "USD"):
        super().__init__(symbol, "CRYPTO", exchange, currency)


class _FakeTrade:  # noqa: D401 – mirrors minimal ib_insync.Trade API
    def __init__(self, order: _FakeOrder, contract: _FakeContract | None = None):
        self.order = order
        self.contract = contract  # may be None
        # ``orderStatus`` attribute with the fields accessed in BaseOrderHandler.
        self.orderStatus = SimpleNamespace(
            status="Submitted",
            filled=0,
            remaining=order.__dict__.get("totalQuantity", 0),
            avgFillPrice=0.0,
            lastFillPrice=0.0,
            whyHeld="",  # field accessed by OrderManager
        )

        # Provide isDone() helper used by various wait utilities
        self.isDone = lambda: self.orderStatus.status in {  # type: ignore[method-assign]
            "Filled",
            "Cancelled",
            "ApiCancelled",
        }


# ---------------------------------------------------------------------------
# Fake IB client – enough surface for Broker & Manager classes.
# ---------------------------------------------------------------------------
class _Wrapper:  # Mimic ib_insync.internal.wrapper accounts list
    accounts = ["DU123456"]


class _FakeIB:  # noqa: D401 – stub client
    def __init__(self):
        self._connected = False
        self._trades: list[_FakeTrade] = []
        self.wrapper = _Wrapper()

    # ----- connectivity ----------------------------------------------------
    def connect(self, *_, **__):
        self._connected = True

    def isConnected(self):  # noqa: D401 – name matches real ib_insync
        return self._connected

    def disconnect(self):  # noqa: D401
        self._connected = False

    # ----- account / positions --------------------------------------------
    def accountSummary(self):  # noqa: D401
        # Return list of objects with .tag/value/currency/account attributes.
        return [
            SimpleNamespace(
                tag="NetLiquidation",
                value="100000",
                currency="USD",
                account="DU123456",
            ),
            SimpleNamespace(
                tag="BuyingPower",
                value="200000",
                currency="USD",
                account="DU123456",
            ),
            SimpleNamespace(
                tag="TotalCashValue",
                value="50000",
                currency="USD",
                account="DU123456",
            ),
        ]

    def positions(self):  # noqa: D401 – PositionManager expects an iterable
        return []  # No positions by default

    # ----- order handling ---------------------------------------------------
    def placeOrder(self, contract, order):  # noqa: D401 – signature comp.
        # Allocate incremental orderId and wrap into _FakeTrade
        order.orderId = len(self._trades) + 1
        trade = _FakeTrade(order, contract)  # pass contract for symbol lookups

        # Decide immediate status based on order type – market orders fill instantly
        otype = getattr(order, "orderType", "MKT").upper()
        if otype == "MKT":
            # Determine quantity (shares or cashQty fallback)
            qty = (
                getattr(order, "totalQuantity", 0)
                or getattr(order, "cashQty", 0)
                or getattr(order, "quantity", 0)
                or 0
            )
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = qty
            trade.orderStatus.remaining = 0
            # Provide dummy fill price so avg/last readouts are non-zero
            trade.orderStatus.avgFillPrice = 100.0
            trade.orderStatus.lastFillPrice = 100.0
        else:
            # Limit / other order types stay working
            trade.orderStatus.status = "Submitted"

        self._trades.append(trade)
        return trade

    def trades(self):  # noqa: D401 – OrderManager scans this
        return self._trades

    # ADD start – helpers required by broker & async utils
    def cancelOrder(self, order):  # noqa: D401 – mimic real API
        # Mark the matching trade as cancelled (no effect if not found)
        for tr in self._trades:
            if tr.order is order:
                tr.orderStatus.status = "Cancelled"
                tr.orderStatus.remaining = 0
                break

    # Alias used by some call-sites
    cancel_orders = cancelOrder  # type: ignore[method-assign]

    def openTrades(self):  # noqa: D401 – subset of trades still open
        return [
            tr
            for tr in self._trades
            if tr.orderStatus.status in {"Submitted", "PreSubmitted"}
        ]

    def waitOnUpdate(self, *_a, **_kw):  # noqa: D401 – stubbed event loop helper
        """Synchronisation no-op – real ib_insync blocks until update; tests proceed instantly."""
        pass

    # Market scanner – used by contracts.detect_security_type_from_ibkr
    def reqMatchingSymbols(self, symbol: str):  # noqa: D401
        """Return a minimal list mimicking IB's ContractDescription objects."""
        contract = SimpleNamespace(
            symbol=symbol.upper(),
            secType="STK",  # default to stock for tests
            exchange="SMART",
            currency="USD",
            primaryExchange="NASDAQ",
        )
        return [SimpleNamespace(contract=contract, derivativeSecTypes=[])]
    # ADD end


# ---------------------------------------------------------------------------
# Fake util helper with startLoop used by IBKRBroker.__init__
# ---------------------------------------------------------------------------
class _FakeUtil:  # noqa: D401 – container for startLoop
    @staticmethod
    def startLoop():  # noqa: D401 – no-op for tests
        pass


# ---------------------------------------------------------------------------
# Assemble a fake ``ib_insync`` package tree and register in sys.modules.
# ---------------------------------------------------------------------------
ib_pkg = types.ModuleType("ib_insync")
ib_pkg.IB = _FakeIB
ib_pkg.util = types.ModuleType("ib_insync.util")
ib_pkg.util.startLoop = _FakeUtil.startLoop  # type: ignore[attr-defined]
ib_pkg.Order = _FakeOrder
ib_pkg.Trade = _FakeTrade
ib_pkg.Contract = _FakeContract  # type: ignore[attr-defined]
ib_pkg.Stock = _FakeStock  # type: ignore[attr-defined]
ib_pkg.Crypto = _FakeCrypto  # type: ignore[attr-defined]

# Mark the fake module as a *package* so that `import ib_insync.wrapper` does
# not fall back to the real distribution on PYTHONPATH.
ib_pkg.__path__ = []  # type: ignore[attr-defined]

# Provide placeholder sub-modules that some call-sites may attempt to import.
wrapper_mod = types.ModuleType("ib_insync.wrapper")
util_internal_mod = types.ModuleType("ib_insync.internal")

sys.modules.update({
    "ib_insync.wrapper": wrapper_mod,
    "ib_insync.internal": util_internal_mod,
})
ib_pkg.wrapper = wrapper_mod  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Register the fake package and its util submodule so that standard import
# statements resolve correctly.
# ---------------------------------------------------------------------------
sys.modules.update(
    {
        "ib_insync": ib_pkg,
        "ib_insync.util": ib_pkg.util,
    }
)

# ---------------------------------------------------------------------------
# Runtime patch: If any StrateQueue IBKR modules were imported *before* this
# stub became active we need to flip their `IB_INSYNC_AVAILABLE` flag and
# point them at our fake classes so follow-up calls operate on the in-memory
# simulation rather than raising ImportErrors.
# ---------------------------------------------------------------------------
for _mn, _m in list(sys.modules.items()):
    if _mn.startswith("StrateQueue.brokers.IBKR") and hasattr(_m, "IB_INSYNC_AVAILABLE"):
        _m.IB_INSYNC_AVAILABLE = True  # noqa: D401 – runtime patch
        setattr(_m, "IB", _FakeIB)
        setattr(_m, "util", ib_pkg.util)
        setattr(_m, "Order", _FakeOrder)

# ---------------------------------------------------------------------------
# Autouse pytest fixture: ensure fresh state between tests and maintain the
# patch stability (TradingClient etc. references).
# ---------------------------------------------------------------------------
import pytest  # noqa: E402 – after sys.modules patch


@pytest.fixture(autouse=True)
def _reset_fake_ib_state():
    yield
    # 1) Clear trades recorded in any _FakeIB instance.
    for obj in gc.get_objects():
        if isinstance(obj, _FakeIB):
            obj._trades.clear()

    # 2) Re-assert our fake module mapping in case another test mutated it.
    sys.modules["ib_insync"] = ib_pkg
    sys.modules["ib_insync.util"] = ib_pkg.util
    sys.modules["ib_insync.wrapper"] = wrapper_mod
    sys.modules["ib_insync.internal"] = util_internal_mod

    # 3) Re-flip flags on already-imported StrateQueue modules (defensive).
    for _mn, _m in list(sys.modules.items()):
        if _mn.startswith("StrateQueue.brokers.IBKR") and hasattr(_m, "IB_INSYNC_AVAILABLE"):
            _m.IB_INSYNC_AVAILABLE = True
            setattr(_m, "IB", _FakeIB)
            setattr(_m, "util", ib_pkg.util)
            setattr(_m, "Order", _FakeOrder)