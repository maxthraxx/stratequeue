"""
LIVE Alpaca integration-tests
─────────────────────────────
• Run ONLY against a PAPER account.
• Skipped unless ALPACA_KEY / ALPACA_SECRET are exported *and*
  the pytest marker ``live_alpaca`` (or ``network``) is selected.

Covered scenarios
1. Connection / credential handshake
2. Account & position fetch
3. Market-order lifecycle (equity & crypto)
4. Limit order + replace + cancel
5. Bulk helpers (cancel_all_orders / close_all_positions)
6. Symbol normalisation & filters
7. Automatic cleanup to leave the account flat
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
import sys
import re

# ---------------------------------------------------------------------------
# Ensure local StrateQueue sources are imported first
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import pytest

from StrateQueue.brokers.Alpaca.alpaca_broker import AlpacaBroker
from StrateQueue.brokers.broker_base import BrokerConfig, OrderSide, OrderType
from StrateQueue.core.signal_extractor import SignalType, TradingSignal

# ---------------------------------------------------------------------------
# Pytest markers / guard-rails
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.live_alpaca,
    pytest.mark.network,  # convenient generic marker if you already use one
]

_REQ_ENV_CANDIDATES = [
    ("ALPACA_KEY", "ALPACA_SECRET"),  # legacy
    ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),  # official names
    ("PAPER_KEY", "PAPER_SECRET"),  # stratequeue setup (paper)
]
_CFG_ENV_FILE = Path.home() / ".stratequeue" / "credentials.env"
_SKIP_REASON = "Live Alpaca credentials not supplied via env vars or ~/.stratequeue/credentials.env"


def _load_from_env_file() -> None:
    """Load ~/.stratequeue/credentials.env into os.environ (non-destructive)."""
    if not _CFG_ENV_FILE.exists():
        return

    pattern = re.compile(r"^([A-Z0-9_]+)=(.*)$")
    try:
        for line in _CFG_ENV_FILE.read_text().splitlines():
            m = pattern.match(line.strip())
            if m and m.group(1) not in os.environ:
                os.environ[m.group(1)] = m.group(2)
    except Exception:
        # best-effort – ignore parse errors
        pass


# ---------------------------------------------------------------------------
# Credential guard-rail helpers
# ---------------------------------------------------------------------------


def _get_alpaca_creds() -> tuple[str | None, str | None]:
    """Return (api_key, secret_key) or (None, None) if unavailable."""
    # first try direct env vars
    for key_var, sec_var in _REQ_ENV_CANDIDATES:
        k, s = os.getenv(key_var), os.getenv(sec_var)
        if k and s:
            return k, s

    # fallback: load env file and retry once
    _load_from_env_file()
    for key_var, sec_var in _REQ_ENV_CANDIDATES:
        k, s = os.getenv(key_var), os.getenv(sec_var)
        if k and s:
            return k, s

    return None, None


def _env_ready() -> bool:
    k, s = _get_alpaca_creds()
    return bool(k and s)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def broker():
    """
    Session-scoped *connected* broker instance. Auto-discovers credentials from
    env vars *or* from `~/.stratequeue/credentials.env` written by
    `stratequeue setup`.
    """
    if not _env_ready():
        pytest.skip(_SKIP_REASON)

    api_key, secret_key = _get_alpaca_creds()

    cfg = BrokerConfig(
        "alpaca",
        paper_trading=True,  # **never run live in CI!**
        credentials={
            "api_key": api_key,
            "secret_key": secret_key,
            # base_url optional – default paper endpoint is fine
        },
    )

    br = AlpacaBroker(cfg)
    assert br.connect(), "Unable to connect to Alpaca paper account"
    yield br

    # ------------- guaranteed cleanup -----------------
    br.cancel_all_orders()
    br.close_all_positions()
    br.disconnect()


def _wait_until(predicate, timeout: float = 15, poll: float = 0.5):
    """Utility: spin until predicate() returns truthy or timeout (sec)."""
    start = time.time()
    while time.time() - start < timeout:
        if predicate():
            return True
        time.sleep(poll)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_validate_credentials(broker: AlpacaBroker):
    assert broker.validate_credentials() is True
    assert broker.is_connected


def test_account_info_fields(broker: AlpacaBroker):
    acct = broker.get_account_info()
    assert acct and acct.total_value > 0 and acct.buying_power > 0
    assert acct.currency.upper() in ("USD", "EUR", "GBP")


def test_market_order_equity_lifecycle(broker: AlpacaBroker):
    res = broker.place_order(
        "AAPL", OrderType.MARKET, OrderSide.BUY, quantity=1
    )
    assert res.success and res.order_id

    # Wait until filled/accepted
    assert _wait_until(
        lambda: broker.get_order_status(res.order_id)["status"] in {"filled", "accepted"}
    )

    # Cancel just in case (idempotent even if filled)
    assert broker.cancel_order(res.order_id)
    broker.cancel_all_orders()


def test_market_order_crypto_symbol_normalisation(broker: AlpacaBroker):
    res = broker.place_order(
        "btc", OrderType.MARKET, OrderSide.BUY, quantity=0.0001
    )
    assert res.success
    order = broker.get_order_status(res.order_id)
    assert order["symbol"] == "BTC/USD"  # normalised

    broker.cancel_all_orders()
    broker.close_all_positions()


def test_limit_order_replace_and_cancel(broker: AlpacaBroker):
    # Price far below market so order sits open
    res = broker.place_order(
        "MSFT", OrderType.LIMIT, OrderSide.BUY, quantity=1, price=1.00
    )
    assert res.success
    oid = res.order_id

    # Replace limit price higher -> expect updated
    new_price = 2.00
    assert broker.replace_order(oid, limit_price=new_price) is True

    updated = broker.get_order_status(oid)
    assert float(updated["limit_price"]) == pytest.approx(new_price, rel=1e-3)

    # Cancel and ensure status reflects
    assert broker.cancel_order(oid)
    assert _wait_until(
        lambda: broker.get_order_status(oid)["status"] == "canceled"
    )


def test_bulk_helpers_and_filters(broker: AlpacaBroker):
    # Two orders, different symbols
    broker.place_order("AAPL", OrderType.MARKET, OrderSide.BUY, 1)
    broker.place_order("MSFT", OrderType.MARKET, OrderSide.BUY, 1)

    assert len(broker.get_orders()) >= 2
    assert len(broker.get_orders(symbol="AAPL")) == 1

    # bulk cancel & close
    assert broker.cancel_all_orders()
    assert broker.close_all_positions()

    assert broker.get_orders() == []
    assert broker.get_positions() == {}


def test_execute_signal_path(broker: AlpacaBroker):
    sig = TradingSignal(
        signal=SignalType.BUY,
        price=10.0,
        timestamp=datetime.utcnow(),
        indicators={},
    )
    res = broker.execute_signal("AAPL", sig)
    assert res.success
    assert broker.cancel_order(res.order_id)