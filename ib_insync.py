"""Light-weight shim replacing the *ib_insync* package during test runs.

If the unit-test stub module ``tests.unit_tests.brokers.ibkr.ibkr_stubs`` is
available we import it – that module registers a fully-featured fake
``ib_insync`` package (named *ib_pkg*) in ``sys.modules``.  We then simply
re-export its public attributes so that ``from ib_insync import IB, util, Order``
works for application code **without** the real dependency.

If the stub module cannot be imported (e.g. the path was pruned) we fall back to
very small placeholder classes that satisfy the attribute look-ups used by
StrateQueue's IBKR integration.  These placeholders are *only* meant for unit
/integration tests – they are **not** feature-complete.
"""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

_STUB_PATH = "tests.unit_tests.brokers.ibkr.ibkr_stubs"

# ---------------------------------------------------------------------------
# First, attempt to load the *detailed* fake package used by the unit-tests.  If
# that import succeeds we copy its public attributes into *this* module and
# expose them under the standard name ``ib_insync`` so downstream code –
# including StrateQueue – perceives a fully-featured ib_insync installation.
# ---------------------------------------------------------------------------

_detailed_pkg = None
try:
    importlib.import_module(_STUB_PATH)
    _detailed_pkg = sys.modules.get("ib_insync")
except ModuleNotFoundError:
    # The dedicated stub is not accessible (e.g. when running production code
    # or stripped-down wheels).  We will fall back to a *very* small dummy
    # implementation further below.
    _detailed_pkg = None

# If the detailed stub was available just mirror its namespace and *return*
# early so that the lightweight fallbacks are skipped.
if _detailed_pkg is not None and _detailed_pkg is not sys.modules.get(__name__):
    globals().update(_detailed_pkg.__dict__)
    sys.modules[__name__] = _detailed_pkg
    sys.modules.setdefault("ib_insync", _detailed_pkg)
    # Nothing else to define – the detailed stub already contains everything.
    del importlib, sys, types, SimpleNamespace, _STUB_PATH, _detailed_pkg
    # Note: cannot use "return" at module top-level; just stop executing by
    # guarding the remainder of the file with the above condition.
else:
    # -----------------------------------------------------------------------
    # Fallback: extremely small stub that only fulfils the attributes accessed
    # by StrateQueue during offline tests.  **Not** production-ready.
    # -----------------------------------------------------------------------

    class IB:  # noqa: D401 – ultra-light fake
        def __init__(self, *_, **__):
            self._connected = False
            self._trades: list["Trade"] = []

        # --- connection helpers -------------------------------------------
        def connect(self, *_a, **_kw):
            self._connected = True

        def isConnected(self):  # noqa: D401
            return self._connected

        def disconnect(self):  # noqa: D401
            self._connected = False

        # --- account & position helpers -----------------------------------
        def accountSummary(self):  # noqa: D401
            return []

        def positions(self):  # noqa: D401
            return []

        # --- order handling -----------------------------------------------
        def placeOrder(self, _contract, order):  # noqa: D401
            order.orderId = len(self._trades) + 1
            trade = Trade(order)
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = getattr(order, "totalQuantity", 0)
            trade.orderStatus.remaining = 0
            self._trades.append(trade)
            return trade

        def trades(self):  # noqa: D401
            return self._trades

        def openTrades(self):  # noqa: D401
            return []

        def cancelOrder(self, _order):  # noqa: D401
            pass

        cancel_orders = cancelOrder  # type: ignore[method-assign]

        def waitOnUpdate(self, *_a, **_kw):  # noqa: D401
            pass

        # --- market scanner helper used by contracts.detect_security_type --
        def reqMatchingSymbols(self, _sym):  # noqa: D401
            return []


    class _DummyOrder:  # simple attribute bag
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.orderId = None


    class Trade:  # noqa: D401 – bare-bones
        def __init__(self, order):
            self.order = order
            self.orderStatus = SimpleNamespace(
                status="Submitted",
                filled=0,
                remaining=0,
                avgFillPrice=0.0,
                lastFillPrice=0.0,
            )

        def isDone(self):  # noqa: D401
            return True


    # Map expected symbols --------------------------------------------------
    Order = _DummyOrder  # noqa: N816 – keep camelCase for API parity

    # Fake util sub-module with startLoop helper -----------------------------
    util = types.ModuleType("ib_insync.util")
    util.startLoop = lambda: None  # type: ignore[assignment]

    # Register util so that "from ib_insync import util" works -------------
    sys.modules.setdefault("ib_insync.util", util)

    # Clean up helper names from module namespace ---------------------------
    del importlib, sys, types, SimpleNamespace, _STUB_PATH, _detailed_pkg 