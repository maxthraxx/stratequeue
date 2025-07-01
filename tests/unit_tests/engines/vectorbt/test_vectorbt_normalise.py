import pandas as pd
import pytest

# Import the extractor and strategy wrapper directly from the library
from StrateQueue.engines.vectorbt_engine import VectorBTSignalExtractor, VectorBTEngineStrategy


def _build_extractor(min_bars: int = 2) -> VectorBTSignalExtractor:
    """Return a VectorBTSignalExtractor wired with a trivial dummy strategy."""

    def _dummy_strategy(data: pd.DataFrame):  # pragma: no cover – strategy body irrelevant
        # Return dummy entries / exits Series matching the index length
        # to allow the extractor to proceed without raising.
        dummy = pd.Series(False, index=data.index)
        return dummy, dummy  # (entries, exits)

    strategy = VectorBTEngineStrategy(_dummy_strategy)
    return VectorBTSignalExtractor(strategy, min_bars_required=min_bars)


# ---------------------------------------------------------------------------
# Happy-path: column aliases, NaN handling, dtype coercion
# ---------------------------------------------------------------------------

def test_validate_and_normalize_accepts_aliases_and_fills_nans():
    df = pd.DataFrame({
        "o": [1, 2, 3],          # alias for Open
        "h": [1.5, 2.5, 3.5],    # alias for High
        "l": [0.5, 1.0, 2.0],    # alias for Low
        "price": [1, 2, 3],      # alias for Close
        "vol": [10, None, 20],   # alias for Volume with a NaN
    })

    extractor = _build_extractor()
    normalised = extractor._validate_and_normalize_data(df)

    # Expected canonical schema and order
    assert list(normalised.columns) == ["Open", "High", "Low", "Close", "Volume"]
    # No NaNs should remain after forward/back fill
    assert normalised.isna().sum().sum() == 0
    # All columns should be numeric
    assert normalised.dtypes.apply(lambda t: t.kind in "iufc").all()


# ---------------------------------------------------------------------------
# Negative path: DataFrame without a Close column or alias should raise
# ---------------------------------------------------------------------------

def test_validate_and_normalize_requires_close_column():
    df = pd.DataFrame({
        "Open": [1, 2, 3],
        "High": [2, 3, 4],
        "Low": [0.5, 1.5, 2.5],
        "Volume": [100, 120, 140],
    })

    extractor = _build_extractor()
    with pytest.raises(ValueError):
        extractor._validate_and_normalize_data(df) 