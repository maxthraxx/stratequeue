"""
Shared fixtures & stub broker implementations for BrokerFactory unit-tests
-----------------------------------------------------------------------
This conftest module injects lightweight stub broker classes into the Python
module graph so that *import side-effects* inside StrateQueue.brokers.broker_factory
work without the heavy third-party SDKs (alpaca-trade-api, ib_insync, …).

It also *resets* the BrokerFactory global registries before each test so every
case starts with a clean slate.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any, Generator

import pytest


# ---------------------------------------------------------------------------
# Stub broker implementations – mimic constructor signatures only
# ---------------------------------------------------------------------------


class _StubAlpacaBroker:  # noqa: D101 – test stub
    def __init__(
        self,
        config,  # real class takes BrokerConfig
        portfolio_manager=None,
        statistics_manager=None,
        position_sizer=None,
    ) -> None:
        self.config = config
        self.pm = portfolio_manager
        self.stats = statistics_manager
        self.sizer = position_sizer

    # Methods accessed by BrokerFactory helper paths
    @staticmethod
    def get_broker_info():  # noqa: D401 – not a docstring target
        from StrateQueue.brokers.broker_base import BrokerInfo

        return BrokerInfo(
            name="Alpaca-Stub",
            version="0",
            supported_features={},
            description="stub",
            supported_markets=["stocks"],
            paper_trading=True,
        )

    def validate_credentials(self) -> bool:  # noqa: D401 – not a docstring target
        return True


class _StubIBKRBroker:  # noqa: D101 – test stub
    def __init__(self, config) -> None:  # real class only takes config
        self.config = config

    @staticmethod
    def get_broker_info():  # noqa: D401
        from StrateQueue.brokers.broker_base import BrokerInfo

        return BrokerInfo(
            name="IBKR-Stub",
            version="0",
            supported_features={},
            description="stub",
            supported_markets=["stocks"],
            paper_trading=True,
        )

    def validate_credentials(self) -> bool:  # noqa: D401
        return True


# ---------------------------------------------------------------------------
# Autouse fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_broker_factory(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Inject stubs + reset BrokerFactory *per test*.

    1. Create temporary module objects containing the stub broker classes.
    2. Register them in `sys.modules` under the exact import paths used in
       `broker_factory.py` (relative imports inside package).
    3. Clear BrokerFactory's global registries so next import starts fresh.
    """

    # Create fake module for Alpaca broker path
    alpaca_mod = types.ModuleType("StrateQueue.brokers.Alpaca.alpaca_broker")
    alpaca_mod.AlpacaBroker = _StubAlpacaBroker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "StrateQueue.brokers.Alpaca.alpaca_broker", alpaca_mod)

    # Create fake module for IBKR broker path
    ibkr_mod = types.ModuleType("StrateQueue.brokers.IBKR.ibkr_broker")
    ibkr_mod.IBKRBroker = _StubIBKRBroker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "StrateQueue.brokers.IBKR.ibkr_broker", ibkr_mod)

    # Stub credential check helper referenced by validate_broker_credentials
    credential_mod = types.ModuleType("StrateQueue.brokers.IBKR.credential_check")
    credential_mod.test_ibkr_credentials = lambda *_, **__: True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "StrateQueue.brokers.IBKR.credential_check", credential_mod)

    # Now import the module under test (after stubs!)
    from StrateQueue.brokers import broker_factory as bf  # local import after stubs

    # Reset internal singleton state so each test is independent
    bf.BrokerFactory._brokers.clear()
    bf.BrokerFactory._initialized = False

    # Ensure module reload picks up cleared state
    importlib.reload(bf)

    # Yield to the actual test
    yield

    # (No explicit teardown needed – state reset above for next test)
    