from __future__ import annotations

"""
Alpaca Market Data Source

Provides historical and real-time market data (stocks & crypto) via Alpaca's
Market Data API.  Design mirrors the existing Polygon & Yahoo providers so the
rest of StrateQueue can treat it interchangeably.

Requirements
------------
    pip install "alpaca-py>=0.12"  # official SDK

Environment variables recognised (kept consistent with broker helpers):
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
    ALPACA_PAPER           # any truthy value ⇒ use free/paper IEX feed
                            # falsy ⇒ use live/SIP feed (requires paid plan)

Limitations
-----------
* Only bar (aggregate) data is supported for now.
* Granularity mapping supports 1m / 5m / 15m / 1h / 1d.  Extend as needed.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd

from .data_source_base import BaseDataIngestion, MarketData

# Conditional import so StrateQueue still imports if SDK is missing
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
    except ImportError:
        CryptoHistoricalDataClient = None                       # optional
    # Stock streaming client – optional (requires 'alpaca-py[async]')
    try:
        from alpaca.data.live import StockDataStream
    except ImportError:
        StockDataStream = None                               # optional

    try:
        from alpaca.data.live import CryptoDataStream
    except ImportError:
        CryptoDataStream = None                              # optional
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False
    # Leave classes undefined; ProviderFactory will skip registration.

logger = logging.getLogger(__name__)


class AlpacaDataIngestion(BaseDataIngestion):
    """Alpaca Market Data ingestion (historical + realtime)."""

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def dependencies_available() -> bool:
        """Return True if *alpaca-py* SDK is importable."""
        return _ALPACA_AVAILABLE

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        paper: bool = True,
        granularity: str = "1m",
        is_crypto: bool = False,
    ) -> None:
        if not _ALPACA_AVAILABLE:
            raise ImportError(
                "alpaca-py package is required for AlpacaDataIngestion.\n"
                "Install via: pip install 'alpaca-py>=0.12'"
            )

        super().__init__()

        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.is_crypto = is_crypto
        self.default_granularity = granularity

        # Map StrateQueue granularities → Alpaca TimeFrame enum
        self._tf_map: Dict[str, TimeFrame] = {
            "1m": TimeFrame.Minute,
            "5m": TimeFrame.FiveMinutes,
            "15m": TimeFrame.FifteenMinutes,
            "1h": TimeFrame.Hour,
            "1d": TimeFrame.Day,
        }
        if granularity not in self._tf_map:
            msg = (
                f"Granularity '{granularity}' not supported by Alpaca provider. "
                f"Supported: {list(self._tf_map.keys())}"
            )
            raise ValueError(msg)

        # Clients ----------------------------------------------------
        if self.is_crypto:
            if CryptoHistoricalDataClient is None or CryptoDataStream is None:
                raise ImportError("Crypto feed not available in installed alpaca-py")
            self._hist_client = CryptoHistoricalDataClient(api_key, secret_key)
            feed = "us"  # default crypto feed label – Alpaca only offers one
            self._stream: CryptoDataStream = CryptoDataStream(api_key, secret_key, feed=feed)  # type: ignore
        else:
            self._hist_client = StockHistoricalDataClient(api_key, secret_key)
            feed = "iex" if paper else "sip"
            if StockDataStream is None:
                raise ImportError(
                    "alpaca-py installed without streaming support. "
                    "Install with: pip install 'alpaca-py[async]'"
                )
            self._stream: StockDataStream = StockDataStream(api_key, secret_key, feed=feed)  # type: ignore

        # Attach WS callbacks lazily (only once)
        self._configure_stream()

        # Background task handle for run_forever
        self._stream_task: asyncio.Task | None = None

        logger.info(
            "AlpacaDataIngestion initialised (paper=%s, crypto=%s, granularity=%s, feed=%s)",
            paper,
            is_crypto,
            granularity,
            feed,
        )

    # ------------------------------------------------------------------
    # Historical data ---------------------------------------------------
    # ------------------------------------------------------------------
    async def fetch_historical_data(
        self,
        symbol: str,
        days_back: int = 30,
        granularity: str = "1m",
    ) -> pd.DataFrame:
        """Fetch **bars** using Alpaca Historical API.

        *symbol* is sent to `/v2/stocks/{symbol}/bars` or `/v2/crypto/bars`.
        """
        if granularity not in self._tf_map:
            raise ValueError(
                f"Granularity '{granularity}' not supported. Supported: {list(self._tf_map)}"
            )
        tf_enum = self._tf_map[granularity]

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)

        # Wrap sync SDK call in thread executor to avoid blocking event loop
        def _download():
            if self.is_crypto:
                bars = self._hist_client.get_crypto_bars(symbol, tf_enum, start, end)
            else:
                bars = self._hist_client.get_stock_bars(symbol, tf_enum, start, end)
            return bars.df if hasattr(bars, "df") else pd.DataFrame()

        df: pd.DataFrame = await asyncio.to_thread(_download)
        if df.empty:
            logger.warning("Alpaca returned no data for %s (%s)", symbol, granularity)
            return df

        # Normalise columns ------------------------------------------------
        rename_cols = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
        df.rename(columns=rename_cols, inplace=True)

        # Ensure datetime index & sort
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(None)
        df.sort_index(inplace=True)

        self.historical_data[symbol] = df
        logger.info(
            "Alpaca: fetched %d bars for %s (%s)", len(df), symbol, granularity
        )
        return df

    # ------------------------------------------------------------------
    # Real-time feed -----------------------------------------------------
    # ------------------------------------------------------------------
    def _configure_stream(self):
        """Wire generic *on_bar* handler for all symbols."""

        @self._stream.on_bar("*")  # type: ignore[attr-defined]
        async def _on_bar(bar):  # noqa: N802 – callback sig
            md = MarketData(
                symbol=bar.symbol,
                timestamp=bar.timestamp.replace(tzinfo=timezone.utc).astimezone(tz=None),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            self.current_bars[md.symbol] = md
            self._notify_callbacks(md)

    # Public API ---------------------------------------------------------
    def subscribe_to_symbol(self, symbol: str):
        """Subscribe to live bars for *symbol*."""
        # The SDK offers type-specific subscribe helpers
        if self.is_crypto:
            self._stream.subscribe_bars(symbol)
        else:
            self._stream.subscribe_bars(symbol)
        logger.debug("Alpaca subscribed to %s", symbol)

    def start_realtime_feed(self):
        """Begin running the WebSocket forever in the background."""
        if self._stream_task and not self._stream_task.done():
            logger.debug("Alpaca realtime feed already running")
            return
        loop = asyncio.get_event_loop()
        self._stream_task = loop.create_task(self._stream.run())
        logger.info("Alpaca realtime feed started")

    def stop_realtime_feed(self):  # override to shut down cleanly
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            logger.info("Alpaca realtime feed stopped")

    # Convenience helpers -----------------------------------------------
    def set_update_interval_from_granularity(self, granularity: str):
        """Method kept for API parity with Demo provider (no-op here)."""
        pass 