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


class _FakeTrade:  # noqa: D401 – mirrors minimal ib_insync.Trade API
    def __init__(self, order: _FakeOrder):
        self.order = order
        # ``orderStatus`` attribute with the fields accessed in BaseOrderHandler.
        self.orderStatus = SimpleNamespace(
            status="Submitted",
            filled=0,
            remaining=order.__dict__.get("totalQuantity", 0),
            avgFillPrice=0.0,
            lastFillPrice=0.0,
        )


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
            )
        ]

    def positions(self):  # noqa: D401 – PositionManager expects an iterable
        return []  # No positions by default

    # ----- order handling ---------------------------------------------------
    def placeOrder(self, _contract, order):  # noqa: D401 – signature comp.
        # Allocate incremental orderId and wrap into _FakeTrade
        order.orderId = len(self._trades) + 1
        trade = _FakeTrade(order)
        self._trades.append(trade)
        return trade

    def trades(self):  # noqa: D401 – OrderManager scans this
        return self._trades


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

# Expose sub-module entries so that ``from ib_insync import util`` works.
sys.modules.update(
    {
        "ib_insync": ib_pkg,
        "ib_insync.util": ib_pkg.util,
    }
)

# ---------------------------------------------------------------------------
# Autouse pytest fixture: flush recorded trades between tests so state never
# leaks.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402 – after sys.modules patch


@pytest.fixture(autouse=True)
def _reset_fake_ib_state():
    yield
    # After each test, clear trades recorded in any _FakeIB instance.
    for obj in gc.get_objects():
        if isinstance(obj, _FakeIB):
            obj._trades.clear() 