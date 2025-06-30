# New test module for TradingProcessor behavioural unit tests

from __future__ import annotations

import pandas as pd
import pytest
from types import SimpleNamespace

from StrateQueue.live_system.trading_processor import TradingProcessor
from StrateQueue.core.signal_extractor import TradingSignal, SignalType


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubExtractor:
    def __init__(self):
        self.calls = 0

    def extract_signal(self, _df):
        self.calls += 1
        return TradingSignal(SignalType.BUY, 1.0, pd.Timestamp.utcnow(), {})


class _StubMultiExtractor:
    def __init__(self):
        self.calls = 0

    def extract_signals(self, data_dict):
        self.calls += 1
        return {
            sym: TradingSignal(SignalType.BUY, 1.0, pd.Timestamp.utcnow(), {})
            for sym in data_dict
        }


class _StubDataManager:
    def __init__(self):
        # pre-construct DF with 10 bars so lookback always satisfied
        self._df = pd.DataFrame({"Close": [1.0] * 10})

    async def update_symbol_data(self, _sym):
        return None  # no-op

    def get_symbol_data(self, _sym):
        return self._df.copy()

    def get_data_progress(self, *_a, **_kw):
        return (len(self._df), 10, 100.0)


auto_stats_call_counter = 0


class _StubStats:
    def __init__(self):
        self.updates = 0

    def update_market_prices(self, _d):
        self.updates += 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def patch_live_signal_extractor(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "StrateQueue.live_system.trading_processor.LiveSignalExtractor",
        lambda *a, **k: _StubExtractor(),
        raising=False,
    )


@pytest.fixture()
def single_tp(patch_live_signal_extractor):
    return TradingProcessor(
        symbols=["AAPL"],
        lookback_period=5,
        is_multi_strategy=False,
        strategy_class=object,  # triggers LiveSignalExtractor path
        statistics_manager=_StubStats(),
    )


@pytest.fixture()
def multi_ticker_tp(monkeypatch: pytest.MonkeyPatch):
    # Engine stub capable of returning the multi-ticker extractor
    engine = SimpleNamespace()
    engine.create_multi_ticker_signal_extractor = lambda *_a, **_kw: _StubMultiExtractor()

    tp = TradingProcessor(
        symbols=["AAPL", "MSFT"],
        lookback_period=5,
        is_multi_strategy=False,
        engine_strategy=object,
        engine=engine,
    )
    return tp


# ---------------------------------------------------------------------------
# Tests – single-strategy per-symbol
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_cycle_produces_signal(single_tp: TradingProcessor):
    dm_stub = _StubDataManager()
    result = await single_tp.process_trading_cycle(dm_stub)

    assert result and "AAPL" in result
    assert single_tp.get_active_signals() == result
    assert single_tp.statistics_manager.updates == 1


# ---------------------------------------------------------------------------
# Tests – multi-ticker extractor path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_ticker_cycle(multi_ticker_tp: TradingProcessor):
    dm_stub = _StubDataManager()
    res = await multi_ticker_tp.process_trading_cycle(dm_stub)

    assert set(res.keys()) == {"AAPL", "MSFT"}
    assert multi_ticker_tp.multi_ticker_extractor.calls == 1


# ---------------------------------------------------------------------------
# Constructor attribute checks
# ---------------------------------------------------------------------------

def test_constructor_flags(multi_ticker_tp: TradingProcessor):
    assert multi_ticker_tp.use_multi_ticker is True
    assert isinstance(multi_ticker_tp.signal_extractors, dict) and not multi_ticker_tp.signal_extractors 