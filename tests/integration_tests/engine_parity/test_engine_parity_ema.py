import os
import sys
from pathlib import Path
import textwrap
import pandas as pd
import pytest

from StrateQueue.engines import EngineFactory
from StrateQueue.core.signal_extractor import SignalType

# ---------------------------------------------------------------------------
# Helpers (copied/minimised from SMA parity test)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_CSV_PATH = PROJECT_ROOT / "examples" / "data" / "AAPL.csv"


def _load_ohlcv_dataframe() -> pd.DataFrame:
    df = pd.read_csv(DATA_CSV_PATH, parse_dates=["Date"], index_col="Date")
    df = df.rename(columns={c: c.title() for c in df.columns})
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "")
                .astype(float)
            )
    return df.iloc[::-1]


_ema_signals_cache = {}

# ---------------------------------------------------------------------------
# Strategy generation per engine
# ---------------------------------------------------------------------------


def _write_strategy_file(engine_type: str, tmp_dir: Path) -> Path:
    """Generate an EMA-crossover strategy file compatible with *engine_type*."""
    if engine_type == "backtesting":
        code = textwrap.dedent(
            """
            from backtesting import Strategy
            from backtesting.lib import crossover

            class EmaCross(Strategy):
                fast = 10
                slow = 30

                def init(self):
                    close = self.data.Close
                    self.ema_fast = self.I(lambda s: s.ewm(span=self.fast, adjust=False).mean(), close)
                    self.ema_slow = self.I(lambda s: s.ewm(span=self.slow, adjust=False).mean(), close)

                def next(self):
                    if crossover(self.ema_fast, self.ema_slow):
                        if not self.position:
                            self.buy()
                    elif crossover(self.ema_slow, self.ema_fast):
                        if self.position:
                            self.position.close()
            """
        )
    elif engine_type == "vectorbt":
        code = textwrap.dedent(
            """
            import pandas as pd

            def ema_crossover_strategy(data, fast=10, slow=30):
                close = data['Close']
                fast_ema = close.ewm(span=fast, adjust=False).mean()
                slow_ema = close.ewm(span=slow, adjust=False).mean()
                entries = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
                exits  = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))
                return entries, exits

            # Mark for VectorBT auto-detection
            ema_crossover_strategy.__vbt_strategy__ = True
            """
        )
    elif engine_type == "backtrader":
        code = textwrap.dedent(
            """
            import backtrader as bt

            class EmaCross(bt.Strategy):
                params = dict(fast=10, slow=30)

                def __init__(self):
                    self.ema_fast = bt.ind.EMA(self.data.close, period=self.p.fast)
                    self.ema_slow = bt.ind.EMA(self.data.close, period=self.p.slow)

                def next(self):
                    if not self.position and self.ema_fast[0] > self.ema_slow[0] and self.ema_fast[-1] <= self.ema_slow[-1]:
                        self.buy()
                    elif self.position and self.ema_fast[0] < self.ema_slow[0] and self.ema_fast[-1] >= self.ema_slow[-1]:
                        self.close()
            """
        )
    else:
        raise ValueError(f"Strategy generation for engine '{engine_type}' not implemented")

    path = tmp_dir / f"ema_{engine_type}.py"
    path.write_text(code)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ohlcv_df():
    return _load_ohlcv_dataframe()


@pytest.fixture(params=["backtesting", "vectorbt", "backtrader"], ids=lambda e: e)
def engine_fixture(request, tmp_path_factory):
    engine_type = request.param

    # Skip if dependencies not available
    if not EngineFactory.is_engine_supported(engine_type):
        pytest.skip(f"{engine_type} dependencies not installed – skipping EMA parity test")

    tmp_dir = tmp_path_factory.mktemp(f"ema_{engine_type}")
    strat_path = _write_strategy_file(engine_type, tmp_dir)

    engine = EngineFactory.create_engine(engine_type)
    return engine_type, engine, strat_path


# ---------------------------------------------------------------------------
# Signal computation helper (simplified)
# ---------------------------------------------------------------------------

def _compute_signal_series(engine_type: str, engine, strategy_path: Path, df: pd.DataFrame):
    engine_strategy = engine.load_strategy_from_file(str(strategy_path))

    try:
        extractor = engine.create_signal_extractor(engine_strategy, granularity="1d")
    except TypeError:
        extractor = engine.create_signal_extractor(engine_strategy)

    signals = []
    idx = []
    for i in range(2, len(df)):
        slice_df = df.iloc[: i + 1]
        sig = extractor.extract_signal(slice_df).signal
        signals.append(sig)
        idx.append(slice_df.index[-1])

    return pd.Series([s.value for s in signals], index=idx, name=engine_type)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.dependency()
def test_collect_ema_signals(engine_fixture, ohlcv_df):
    engine_type, engine, strat_path = engine_fixture
    series = _compute_signal_series(engine_type, engine, strat_path, ohlcv_df)
    _ema_signals_cache[engine_type] = series


@pytest.mark.dependency(depends=["test_collect_ema_signals"], scope="session")
def test_ema_parity_across_engines():
    if len(_ema_signals_cache) < 2:
        pytest.skip("Fewer than two engines produced signals – parity assertion not applicable")

    engines = list(_ema_signals_cache.keys())
    ref_engine = engines[0]
    ref_series = _ema_signals_cache[ref_engine]

    mismatches = []
    for eng in engines[1:]:
        diff = _ema_signals_cache[eng] != ref_series
        if diff.any():
            mismatches.append(f"{eng}: {int(diff.sum())} mismatches")

    if mismatches:
        raise AssertionError("Signal sequence mismatch\n" + "\n".join(mismatches)) 