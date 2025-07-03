# New test module for DataManager behavioural unit tests

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Import the system under test (SUT)
# ---------------------------------------------------------------------------
from StrateQueue.live_system.data_manager import DataManager

# ---------------------------------------------------------------------------
# Universal helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch):
    """Replace asyncio.sleep with a noop so tests run instantly."""

    async def _no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep, raising=False)


class _StubBar(SimpleNamespace):
    """Simple data structure mimicking the namedtuple returned by real ingesters."""

    pass


class _StubIngester:
    """Mimics the public API used by DataManager without any external I/O."""

    def __init__(self):
        self.calls: Dict[str, Any] = {"sub": [], "append": 0, "hist": {}}
        self.realtime_started = False
        self._demo_store: Dict[str, pd.DataFrame] = {}

    # Life-cycle ------------------------------------------------------------
    def start_realtime_feed(self):
        self.realtime_started = True

    async def subscribe_to_symbol(self, sym: str):
        self.calls["sub"].append(sym)

    async def fetch_historical_data(self, sym: str, **_kw):
        data = self.calls["hist"].get(sym)
        if isinstance(data, Exception):
            raise data  # simulate failure path
        return data

    # Demo-provider specific -------------------------------------------------
    def append_new_bar(self, sym: str):
        """Return cumulative DataFrame emulating real demo provider behaviour."""
        self.calls["append"] += 1
        ts = pd.Timestamp.utcnow().floor("s") + pd.Timedelta(seconds=self.calls["append"])
        new_row = pd.DataFrame(
            {
                "Open": [1.0],
                "High": [1.0],
                "Low": [1.0],
                "Close": [1.0],
                "Volume": [1.0],
            },
            index=[ts],
        )
        cur = self._demo_store.get(sym, pd.DataFrame())
        cur = pd.concat([cur, new_row])
        self._demo_store[sym] = cur
        return cur

    # Real-provider branch ---------------------------------------------------
    def get_current_data(self, sym: str):
        return _StubBar(
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
            timestamp=pd.Timestamp.utcnow().floor("s"),
        )


@pytest.fixture()
def stub_ingester(monkeypatch: pytest.MonkeyPatch) -> _StubIngester:
    """Inject a stub ingester into the DataManager factory helper."""
    stub = _StubIngester()

    monkeypatch.setattr(
        "StrateQueue.live_system.data_manager.setup_data_ingestion",
        lambda **_kw: stub,
        raising=False,
    )
    return stub


@pytest.fixture()
def dm(stub_ingester: _StubIngester) -> DataManager:
    """Create a DataManager instance wired to the stub ingester and initialise source."""
    manager = DataManager(
        symbols=["BTCUSD"],
        data_source="demo",
        granularity="1m",
        lookback_period=5,
    )
    # Ensure data_ingester is set for subsequent calls
    manager.initialize_data_source()
    return manager


# ---------------------------------------------------------------------------
# Tests – initialise_data_source
# ---------------------------------------------------------------------------

def test_initialize_data_source(dm: DataManager, stub_ingester: _StubIngester):
    res = dm.initialize_data_source()
    assert res is stub_ingester
    assert dm.data_ingester is stub_ingester


# ---------------------------------------------------------------------------
# Tests – historical data bootstrap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_historical_success(dm: DataManager, stub_ingester: _StubIngester):
    df = pd.DataFrame(
        {
            "Open": 1.0,
            "High": 1.0,
            "Low": 1.0,
            "Close": 1.0,
            "Volume": 1.0,
        },
        index=pd.date_range("2020-01-01", periods=3, freq="T"),
    )
    stub_ingester.calls["hist"]["BTCUSD"] = df

    await dm.initialize_historical_data()

    assert dm.cumulative_data["BTCUSD"].equals(df)
    assert stub_ingester.realtime_started is True
    assert stub_ingester.calls["sub"] == ["BTCUSD"]


@pytest.mark.asyncio
async def test_historical_fallback_creates_empty(dm: DataManager, stub_ingester: _StubIngester, monkeypatch: pytest.MonkeyPatch, caplog):
    # Prepare stub to raise when historical fetch attempted
    exc = RuntimeError("hist failure")
    stub_ingester.calls["hist"]["BTCUSD"] = exc

    async def _fail(*_a, **_kw):
        raise exc

    monkeypatch.setattr(stub_ingester, "fetch_historical_data", _fail, raising=True)

    import logging

    with caplog.at_level(logging.INFO):
        await dm.initialize_historical_data()

    assert len(dm.cumulative_data["BTCUSD"]) == 1
    assert "Will build BTCUSD data from real-time feeds only" in caplog.text


# ---------------------------------------------------------------------------
# Tests – real-time update + capping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_append_and_cap(dm: DataManager, stub_ingester: _StubIngester):
    # append six times -> should cap at lookback_period=5
    for _ in range(6):
        await dm.update_symbol_data("BTCUSD")
    assert len(dm.cumulative_data["BTCUSD"]) == 5


# ---------------------------------------------------------------------------
# Tests – runtime symbol add
# ---------------------------------------------------------------------------

def test_add_symbol_runtime_success(dm: DataManager, stub_ingester: _StubIngester):
    ok = dm.add_symbol_runtime("ETHUSD")
    assert ok is True
    assert "ETHUSD" in dm.get_tracked_symbols()
    # demo provider: should *not* trigger subscribe_to_symbol
    assert stub_ingester.calls["sub"] == []


def test_add_symbol_runtime_idempotent(dm: DataManager):
    dm.symbols.append("ETHUSD")  # manually add to simulate existing
    ok = dm.add_symbol_runtime("ETHUSD")
    assert ok is True


# ---------------------------------------------------------------------------
# Tests – utility helpers
# ---------------------------------------------------------------------------

def test_progress_and_has_sufficient_data(dm: DataManager):
    # start below lookback
    dm.cumulative_data["BTCUSD"] = pd.DataFrame(index=range(3))
    assert dm.has_sufficient_data("BTCUSD") is False

    # now exceed lookback to ensure .copy() path triggered
    dm.cumulative_data["BTCUSD"] = pd.DataFrame(index=range(6))
    assert dm.has_sufficient_data("BTCUSD") is True

    current, required, pct = dm.get_data_progress("BTCUSD")
    # DataManager caps returned rows to lookback (5)
    assert (current, required, pct) == (5, 5, 100.0)

    ext = dm.get_symbol_data("BTCUSD")
    ext.iloc[0:1] = -999  # mutate external copy
    assert not dm.cumulative_data["BTCUSD"].iloc[0:1].equals(ext.iloc[0:1]) 