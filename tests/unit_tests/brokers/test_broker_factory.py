"""
BrokerFactory Unit-Tests
========================
These micro-tests verify the *behavioural contract* of
`StrateQueue.brokers.broker_factory.BrokerFactory` in complete isolation from
real broker SDKs.  Lightweight stub broker classes are injected via the
*autouse fixture* in ``conftest.py``.

Requirements verified in this module
------------------------------------
A. Registration & alias handling
   A1  ``_initialize_brokers`` registers at least the canonical keys ``alpaca``
       and ``ibkr``.
   A2  All documented aliases (``IBKR``, ``interactive-brokers``,
       ``interactive_brokers``) resolve to **the same** class object as
       ``ibkr``.

B. ``create_broker`` happy paths
   B1  Returns an instance of the correct concrete broker for ``alpaca``.
   B2  Accepts an alias (``interactive_brokers``) and normalises it to the
       IBKR stub.
   B3  Forwards extra constructor kwargs (``portfolio_manager``,
       ``statistics_manager``, ``position_sizer``) unchanged.
   B4  Uses a *caller-supplied* ``BrokerConfig`` object without cloning it.

C. ``create_broker`` env & error branches
   C1  When ``config is None`` it auto-builds config via
       ``get_broker_config_from_env``.
   C2  Unknown broker types raise ``ValueError`` with a helpful message.
   C3  Exceptions bubbling from env-config helpers are wrapped into
       ``ValueError`` that still contains the original text.

D. Capability helpers
   D1  ``get_supported_brokers`` returns the full canonical set.
   D2  ``is_broker_supported`` returns True for an alias, False for unknown.

E. Environment-driven helpers
   E1  ``detect_broker_type`` happy path returns detected broker when
       validation passes.
   E2  Validation failure downgrades detection to ``unknown``.
   E3  Unsupported detection also yields ``unknown``.

F. Convenience wrappers
   F1  ``auto_create_broker`` delegates to ``detect_broker_type`` *and*
       ``BrokerFactory.create_broker``.
   F2  ``validate_broker_credentials`` takes the short-circuit IBKR path when
       broker type is ``ibkr``.
   F3  ``list_broker_features`` outputs *deduplicated* canonical keys only.
"""

from __future__ import annotations

import types
from pathlib import Path
import sys

# ---------------------------------------------------------------------------
# Ensure 'src/' is on the path *before* importing StrateQueue packages
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.exists() and SRC_PATH.is_dir():
    sys.path.insert(0, str(SRC_PATH))

# ---------------------------------------------------------------------------
# Inject lightweight stub broker modules so BrokerFactory can import without
# heavy external dependencies (alpaca-trade-api, ib_insync, …)
# ---------------------------------------------------------------------------

def _make_stub(module_name: str, cls_name: str):
    mod = types.ModuleType(module_name)

    class _StubBroker:  # noqa: D401 – stub
        def __init__(self, config, *args, **kwargs):
            self.config = config

        def get_broker_info(self):  # minimal implementation
            from StrateQueue.brokers.broker_base import BrokerInfo

            return BrokerInfo(
                name=f"stub-{cls_name.lower()}",
                version="0",
                supported_features={},
                description="stub",
                supported_markets=[],
                paper_trading=getattr(self.config, "paper_trading", True),
            )

    # Expose class under expected attribute name
    setattr(mod, cls_name, _StubBroker)
    sys.modules[module_name] = mod

    # Also register as attribute on its parent package to satisfy
    # `from ... import AlpacaBroker` style statements.
    parent_name, _, child_name = module_name.rpartition(".")
    if parent_name not in sys.modules:
        # Create placeholder parent package chain recursively as needed
        current = None
        for part in parent_name.split("."):
            module_so_far = part if current is None else f"{current}.{part}"
            if module_so_far not in sys.modules:
                sys.modules[module_so_far] = types.ModuleType(module_so_far)
            current = module_so_far
    # Attach submodule to its immediate parent
    setattr(sys.modules[parent_name], child_name, mod)

    return _StubBroker


# Create & register the two necessary stubs **before** importing BrokerFactory
_StubAlpacaBroker = _make_stub("StrateQueue.brokers.Alpaca.alpaca_broker", "AlpacaBroker")
_StubIBKRBroker = _make_stub("StrateQueue.brokers.IBKR.ibkr_broker", "IBKRBroker")

# Point package search paths at the real source dirs so we can import
# the *actual* broker_factory implementation even though we've stubbed
# out the heavyweight sub-modules.
if "StrateQueue" not in sys.modules:
    # Edge-case: should exist via _make_stub, but guard anyway
    sys.modules["StrateQueue"] = types.ModuleType("StrateQueue")

sys.modules["StrateQueue"].__path__ = [str(SRC_PATH / "StrateQueue")]

if "StrateQueue.brokers" not in sys.modules:
    sys.modules["StrateQueue.brokers"] = types.ModuleType("StrateQueue.brokers")

sys.modules["StrateQueue.brokers"].__path__ = [str(SRC_PATH / "StrateQueue" / "brokers")]

# Stub out the credential_check helper to short-circuit network calls
cred_mod = types.ModuleType("StrateQueue.brokers.IBKR.credential_check")
cred_mod.test_ibkr_credentials = lambda *a, **kw: True  # type: ignore[arg-type]
sys.modules["StrateQueue.brokers.IBKR.credential_check"] = cred_mod

# Also make it accessible as attribute on the parent package
sys.modules["StrateQueue.brokers.IBKR"].credential_check = cred_mod

# Third-party
import importlib
import pytest

# Import the factory module explicitly so we get the *module object* instead
# of relying on it being re-exported by the package.
bf = importlib.import_module("StrateQueue.brokers.broker_factory")

# Expose as attribute for compatibility with legacy import style
sys.modules["StrateQueue.brokers"].broker_factory = bf

from StrateQueue.brokers.broker_base import BrokerConfig

# ---------------------------------------------------------------------------
# A. Registration & alias handling
# ---------------------------------------------------------------------------


def test_initialize_brokers_registers_alpaca_and_ibkr():
    bf.BrokerFactory.get_supported_brokers()  # triggers registration
    assert {"alpaca", "ibkr"} <= set(bf.BrokerFactory._brokers)


@pytest.mark.parametrize("alias", ["IBKR", "interactive-brokers", "interactive_brokers"])
def test_aliases_point_to_same_class(alias):
    bf.BrokerFactory.get_supported_brokers()
    assert bf.BrokerFactory._brokers[alias] is bf.BrokerFactory._brokers["ibkr"]


# ---------------------------------------------------------------------------
# B. create_broker – happy paths
# ---------------------------------------------------------------------------


def test_create_broker_returns_correct_instance_for_alpaca():
    broker = bf.BrokerFactory.create_broker("alpaca", BrokerConfig("alpaca"))
    assert broker.__class__ is bf.BrokerFactory._brokers["alpaca"]


def test_create_broker_accepts_alias_and_normalises():
    broker = bf.BrokerFactory.create_broker("interactive_brokers", BrokerConfig("ibkr"))
    assert broker.__class__ is bf.BrokerFactory._brokers["ibkr"]


def test_create_broker_passes_through_extra_constructor_kwargs(monkeypatch):
    captured = {}

    def _spy(self, cfg, pm, stats, sizer):  # noqa: D401 – spy replaces __init__
        captured["args"] = (pm, stats, sizer)

    monkeypatch.setattr(
        sys.modules["StrateQueue.brokers.Alpaca.alpaca_broker"].AlpacaBroker,
        "__init__",
        _spy,
        raising=False,
    )

    sentinel_pm, sentinel_stats, sentinel_sizer = object(), object(), object()
    bf.BrokerFactory.create_broker(
        "alpaca",
        BrokerConfig("alpaca"),
        portfolio_manager=sentinel_pm,
        statistics_manager=sentinel_stats,
        position_sizer=sentinel_sizer,
    )

    assert captured["args"] == (sentinel_pm, sentinel_stats, sentinel_sizer)


def test_create_broker_uses_provided_config_unmodified():
    cfg = BrokerConfig("alpaca", paper_trading=False, credentials={"api_key": "X"})
    broker = bf.BrokerFactory.create_broker("alpaca", cfg)
    assert broker.config is cfg  # identity, not copy


# ---------------------------------------------------------------------------
# C. create_broker – env / error paths
# ---------------------------------------------------------------------------


def test_create_broker_builds_config_from_env_when_missing(monkeypatch):
    env_cfg = {"api_key": "AAA", "secret_key": "BBB", "paper_trading": False}

    monkeypatch.setattr(
        bf, "get_broker_config_from_env", lambda _b: env_cfg
    )

    broker = bf.BrokerFactory.create_broker("alpaca", config=None)

    assert broker.config.credentials == env_cfg
    assert broker.config.paper_trading is False


def test_create_broker_raises_on_unsupported_type():
    with pytest.raises(ValueError, match="Unsupported broker type"):
        bf.BrokerFactory.create_broker("nope", BrokerConfig("x"))


def test_create_broker_propagates_env_error(monkeypatch):
    # Make helper raise
    def _boom(_):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        bf, "get_broker_config_from_env", _boom
    )

    with pytest.raises(ValueError, match="auto-detect.*boom"):
        bf.BrokerFactory.create_broker("alpaca", config=None)


# ---------------------------------------------------------------------------
# D. Capability helper methods
# ---------------------------------------------------------------------------


def test_get_supported_brokers_lists_all_canonical_keys():
    supported = set(bf.BrokerFactory.get_supported_brokers())
    assert {"alpaca", "ibkr"} <= supported


@pytest.mark.parametrize("broker_type, expected", [("IBKR", True), ("foo", False)])
def test_is_broker_supported_true_for_alias_and_false_for_unknown(broker_type, expected):
    assert bf.BrokerFactory.is_broker_supported(broker_type) is expected


# ---------------------------------------------------------------------------
# E. Environment-driven helpers
# ---------------------------------------------------------------------------


def test_detect_broker_type_positive_flow(monkeypatch):
    monkeypatch.setattr(bf, "detect_broker_from_environment", lambda: "alpaca")
    monkeypatch.setattr(bf, "validate_broker_environment", lambda _b: (True, ""))
    assert bf.detect_broker_type() == "alpaca"


def test_detect_broker_type_rejects_validation_failure(monkeypatch):
    monkeypatch.setattr(bf, "detect_broker_from_environment", lambda: "alpaca")
    monkeypatch.setattr(bf, "validate_broker_environment", lambda _b: (False, "bad"))
    assert bf.detect_broker_type() == "unknown"


def test_detect_broker_type_unknown_when_not_supported(monkeypatch):
    monkeypatch.setattr(bf, "detect_broker_from_environment", lambda: "ghost")
    assert bf.detect_broker_type() == "unknown"


# ---------------------------------------------------------------------------
# F. Convenience wrappers
# ---------------------------------------------------------------------------


def test_auto_create_broker_invokes_detect_and_create(monkeypatch):
    monkeypatch.setattr(bf, "detect_broker_type", lambda: "alpaca")
    monkeypatch.setattr(bf.BrokerFactory, "create_broker", lambda *a, **k: "BROKER_SENTINEL")

    assert bf.auto_create_broker() == "BROKER_SENTINEL"


def test_validate_broker_credentials_shortcuts_ibkr_path(monkeypatch):
    monkeypatch.setattr(bf, "detect_broker_type", lambda: "ibkr")
    monkeypatch.setattr(bf.BrokerFactory, "is_broker_supported", lambda *_: True)

    # Provided by fixture: test_ibkr_credentials returns True
    assert bf.validate_broker_credentials() is True


def test_list_broker_features_deduplicates_aliases(monkeypatch):
    from StrateQueue.brokers.broker_base import BrokerInfo

    dummy_info = BrokerInfo(
        name="demo",
        version="1",
        supported_features={},
        description="",
        supported_markets=[],
        paper_trading=True,
    )

    monkeypatch.setattr(bf.BrokerFactory, "get_broker_info", lambda _b: dummy_info)

    features = bf.list_broker_features()
    assert set(features.keys()) == {"ALPACA", "IBKR"}


# ---------------------------------------------------------------------------
# Allow direct execution: `python test_broker_factory.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__])) 