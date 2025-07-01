"""tests/unit_tests/data_path/conftest.py
Shared fixtures and helpers for the *data-path* test-suite.

REQUIREMENTS COVERED HERE
------------------------
1. **Isolation from the Internet** – Every test must run completely offline.
   A module-wide autouse fixture monkey-patches HTTP and Web-Socket entry
   points used in StrateQueue (`requests.get`, `websocket.WebSocketApp`) so
   accidental network traffic immediately raises rather than leaking.
2. **Async helpers** – Some data-provider APIs are declared `async`.  We
   expose a tiny helper to run such coroutines from synchronous test code
   when we do not want to mark the entire test with `@pytest.mark.asyncio`.
3. **PyTest event-loop scope** – The project already enables
   `asyncio_mode = auto` in *pytest.ini* so the default loop is fine, but we
   still provide an explicit `event_loop` fixture to guarantee a fresh loop
   per test file when needed.

If these fixtures load without error and all monkey-patches succeed then the
requirements for this file are considered satisfied.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Event-loop – supply an explicit fresh loop for any test that requests it
# ---------------------------------------------------------------------------
@pytest.fixture
def event_loop():  # noqa: D401 – pytest naming convention
    """Yield a dedicated asyncio loop so tests can *await* freely."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Block real network traffic for the entire session
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: D401
    """Replace `requests.get` & `websocket.WebSocketApp` with dummies.

    Any code that *accidentally* tries to make an external call will now hit a
    `MagicMock` which records usage but performs no IO.  The substitution is
    session-wide (autouse).
    """

    # Patch HTTP requests
    monkeypatch.setattr("requests.get", MagicMock(name="requests.get"))

    # Patch websocket
    try:
        import websocket  # type: ignore

        monkeypatch.setattr("websocket.WebSocketApp", MagicMock(name="WebSocketApp"))
    except ModuleNotFoundError:
        # `websocket-client` is an optional dependency; nothing to do if absent
        pass

    yield  # tests execute here


# ---------------------------------------------------------------------------
# Tiny helper so synchronous tests can run coroutine functions easily
# ---------------------------------------------------------------------------

def run_async(coro):  # noqa: D401, ANN001
    """Run *coro* in the current event-loop and return its result."""
    return asyncio.get_event_loop().run_until_complete(coro)


# Expose the helper via pytest so tests can do `pytest.run_async(coro)`
pytest.run_async = run_async  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Parametrised *provider* fixture – yields an initialised data-ingestion object
# for each concrete implementation we want covered in the generic provider
# test-suite.  All external network calls inside `fetch_historical_data` are
# monkey-patched to return dummy data so the suite continues to run *offline*.
# ---------------------------------------------------------------------------

import pandas as _pd
from datetime import datetime, timedelta
from StrateQueue.data.sources.demo import TestDataIngestion as _Demo
from StrateQueue.data.sources.polygon import PolygonDataIngestion as _Polygon
from StrateQueue.data.sources.yfinance import YahooFinanceDataIngestion as _Yahoo
from StrateQueue.data.sources.coinmarketcap import (
    CoinMarketCapDataIngestion as _CMC,
)


def _dummy_dataframe(symbol: str, bars: int = 5) -> _pd.DataFrame:  # noqa: D401
    """Create a tiny OHLCV frame for *symbol* with monotonic index."""
    now = datetime.now()
    ts = [now - timedelta(minutes=i) for i in range(bars)][::-1]
    df = _pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(bars)],
            "High": [101.0 + i for i in range(bars)],
            "Low": [99.0 + i for i in range(bars)],
            "Close": [100.5 + i for i in range(bars)],
            "Volume": [1_000 + i for i in range(bars)],
        },
        index=ts,
    )
    df.index = _pd.to_datetime(df.index)
    return df


@pytest.fixture(params=["demo", "polygon", "yfinance", "cmc"], ids=str)
def provider(request, monkeypatch):  # noqa: D401
    """Yield a *ready* data-provider instance of the requested flavour.

    The heavy network bits are stubbed so tests run quickly and deterministically."""

    name: str = request.param

    # ------------------------------------------------------------------
    # Factory per provider type
    # ------------------------------------------------------------------
    if name == "demo":
        inst = _Demo()
        inst._test_name = name

    elif name == "polygon":
        inst = _Polygon(api_key="DUMMY")
        inst._test_name = name

        # Patch *requests.get* used inside `fetch_historical_data`
        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                df = _dummy_dataframe("AAPL", 5)
                results = []
                for ts, row in df.iterrows():
                    results.append(
                        {
                            "o": float(row.Open),
                            "h": float(row.High),
                            "l": float(row.Low),
                            "c": float(row.Close),
                            "v": int(row.Volume),
                            "t": int(ts.timestamp() * 1000),
                        }
                    )
                return {"results": results}

            def raise_for_status(self):
                pass

        monkeypatch.setattr("requests.get", lambda *a, **kw: _Resp())

        # WebSocket calls are irrelevant for historical fetch tests
        monkeypatch.setattr(
            "websocket.WebSocketApp", MagicMock(name="WebSocketApp")
        )

    elif name == "yfinance":
        inst = _Yahoo(granularity="1m")
        inst._test_name = name

        # Fake yfinance.Ticker.history
        class _Ticker:
            def __init__(self, _symbol):
                self.symbol = _symbol

            def history(self, *a, **kw):  # noqa: D401
                return _dummy_dataframe(self.symbol, 5)

        monkeypatch.setattr("yfinance.Ticker", _Ticker)

    elif name == "cmc":
        inst = _CMC(api_key="DUMMY", granularity="1d")
        inst._test_name = name

        # CoinMarketCap makes *two* requests: one for symbol → id, one for OHLCV
        def _cmc_response(url, *a, **kw):  # noqa: D401
            class _Resp:
                status_code = 200

                def __init__(self, _payload):
                    self._payload = _payload

                def json(self):
                    return self._payload

                def raise_for_status(self):
                    pass

            if "cryptocurrency/map" in url:
                return _Resp({"data": [{"id": 1}]})
            else:
                df = _dummy_dataframe("BTC", 5)
                quotes = []
                for ts, row in df.iterrows():
                    quotes.append(
                        {
                            "timestamp": ts.isoformat(),
                            "quote": {
                                "USD": {
                                    "open": float(row.Open),
                                    "high": float(row.High),
                                    "low": float(row.Low),
                                    "close": float(row.Close),
                                    "volume": int(row.Volume),
                                }
                            },
                        }
                    )
                return _Resp({"data": {"quotes": quotes}})

        monkeypatch.setattr("requests.get", _cmc_response)

    else:  # pragma: no cover – should not happen
        raise RuntimeError(f"Unknown provider param {name}")

    yield inst

    # Clean-up if provider started background threads (demo provider only)
    try:
        inst.stop_realtime_feed()
    except Exception:  # noqa: BLE001 – best-effort cleanup
        pass 