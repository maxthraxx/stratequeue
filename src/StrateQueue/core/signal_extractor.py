import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

# Conditional imports for backtesting library
try:
    from backtesting import Backtest, Strategy
    from backtesting.lib import crossover
    BACKTESTING_AVAILABLE = True
except ImportError as e:
    BACKTESTING_AVAILABLE = False
    Backtest = None
    Strategy = None
    crossover = None

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of trading signals"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    LIMIT_BUY = "LIMIT_BUY"
    LIMIT_SELL = "LIMIT_SELL"
    STOP_BUY = "STOP_BUY"
    STOP_SELL = "STOP_SELL"
    STOP_LIMIT_BUY = "STOP_LIMIT_BUY"
    STOP_LIMIT_SELL = "STOP_LIMIT_SELL"
    TRAILING_STOP_SELL = "TRAILING_STOP_SELL"
    TRAILING_STOP_BUY = "TRAILING_STOP_BUY"
    BRACKET_BUY = "BRACKET_BUY"
    BRACKET_SELL = "BRACKET_SELL"


class OrderFunction(str, Enum):
    """Zipline order function types"""
    ORDER = "order"
    ORDER_VALUE = "order_value"
    ORDER_PERCENT = "order_percent"
    ORDER_TARGET = "order_target"
    ORDER_TARGET_VALUE = "order_target_value"
    ORDER_TARGET_PERCENT = "order_target_percent"


class ExecStyle(str, Enum):
    """Zipline execution style types"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class TradingSignal:
    """Structured trading signal output with comprehensive order support"""

    signal: SignalType
    price: float
    timestamp: pd.Timestamp
    indicators: dict[str, float]  # Current indicator values
    metadata: dict[str, Any] = None
    
    # Original fields (backward compatibility)
    size: float | None = None  # Position size (e.g., 0.5 for 50% of equity)
    limit_price: float | None = None  # For limit orders
    stop_price: float | None = None  # For stop orders
    trail_percent: float | None = None  # For trailing stop orders (percentage)
    trail_price: float | None = None  # For trailing stop orders (absolute price)
    time_in_force: str = "gtc"  # Time in force (gtc, day, ioc, fok, opg, cls, etc.)
    strategy_id: str | None = None  # Strategy identifier for multi-strategy mode
    
    # New Zipline order mechanism fields
    order_function: OrderFunction = OrderFunction.ORDER  # Which Zipline helper was used
    execution_style: ExecStyle = ExecStyle.MARKET  # Execution style
    quantity: float | None = None  # Shares for order() function
    value: float | None = None  # Dollar value for order_value()
    percent: float | None = None  # Percentage for order_percent() (0.0-1.0)
    target_quantity: float | None = None  # Target shares for order_target()
    target_value: float | None = None  # Target value for order_target_value()
    target_percent: float | None = None  # Target percent for order_target_percent()
    
    # Exchange and routing
    exchange: str | None = None  # Specific exchange for routing
    
    # Order management
    order_id: str | None = None  # Order ID from Zipline (if any)
    
    def __post_init__(self):
        """Post-initialization to set defaults and validate data"""
        if self.metadata is None:
            self.metadata = {}
        
        # Note: Removed automatic size->quantity copying to preserve sizing intent detection
        # The get_sizing_intent() method will handle legacy size field properly
    
    def get_sizing_intent(self) -> tuple[str, float] | None:
        """
        Extract sizing intent from the signal
        
        Returns:
            Tuple of (intent_type, intent_value) or None if no explicit intent
            - intent_type: "units", "equity_pct", or "notional"
            - intent_value: the numeric value for that intent type
        """
        # Check for explicit sizing intents (new Zipline-style)
        if self.value is not None and self.value > 0:
            return ("notional", self.value)
        elif self.percent is not None and self.percent > 0:
            return ("equity_pct", self.percent)
        elif self.target_value is not None and self.target_value > 0:
            return ("notional", self.target_value)
        elif self.target_percent is not None and self.target_percent > 0:
            return ("equity_pct", self.target_percent)
        elif self.quantity is not None and self.quantity > 0:
            return ("units", self.quantity)
        
        # Check legacy size field - prioritize after explicit Zipline fields
        elif self.size is not None and self.size > 0:
            # Assume size is in dollars (notional) if > 1, otherwise treat as percentage
            if self.size > 1:
                return ("notional", self.size)
            else:
                return ("equity_pct", self.size)
        
        # No explicit sizing intent found
        return None


class SignalExtractorStrategy(Strategy if BACKTESTING_AVAILABLE else object):
    """
    Modified strategy that captures signals instead of executing trades.
    This allows us to extract the current signal from the last timestep.
    """

    def __init__(self, *args, **kwargs):
        if not BACKTESTING_AVAILABLE:
            raise ImportError(
                "backtesting.py support is not installed. Run:\n"
                "    pip install stratequeue[backtesting]\n"
                "or\n"
                "    pip install backtesting"
            )
        # Initialize with any arguments backtesting.py provides
        super().__init__(*args, **kwargs)

        self.current_signal = SignalType.HOLD
        self.indicators_values = {}
        self.signal_history = []

    def next(self):
        """
        Override this method in your strategy to:
        1. Calculate indicators
        2. Determine signal
        3. Store signal instead of executing trades
        """
        # This will be overridden by actual strategy implementations
        pass

    def set_signal(
        self,
        signal: SignalType,
        metadata: dict[str, Any] = None,
        size: float | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        trail_percent: float | None = None,
        trail_price: float | None = None,
        time_in_force: str = "gtc",
    ):
        """Set the current signal instead of calling buy/sell"""
        self.current_signal = signal

        # Store signal with current data
        # For live trading, use the data timestamp; for demo, the data timestamp will be simulated time
        signal_obj = TradingSignal(
            signal=signal,
            price=self.data.Close[-1],
            timestamp=(
                self.data.index[-1]
                if hasattr(self.data.index, "__getitem__")
                else pd.Timestamp.now()
            ),
            indicators=self.indicators_values.copy(),
            metadata=metadata or {},
            size=size,
            limit_price=limit_price,
            stop_price=stop_price,
            trail_percent=trail_percent,
            trail_price=trail_price,
            time_in_force=time_in_force,
        )

        self.signal_history.append(signal_obj)

    def set_limit_buy_signal(
        self,
        limit_price: float,
        size: float | None = None,
        metadata: dict[str, Any] = None,
    ):
        """Set a limit buy signal with specified limit price"""
        self.set_signal(SignalType.LIMIT_BUY, metadata, size, limit_price)

    def set_limit_sell_signal(
        self,
        limit_price: float,
        size: float | None = None,
        metadata: dict[str, Any] = None,
    ):
        """Set a limit sell signal with specified limit price"""
        self.set_signal(SignalType.LIMIT_SELL, metadata, size, limit_price)

    def get_current_signal(self) -> TradingSignal:
        """Get the most recent signal"""
        if self.signal_history:
            return self.signal_history[-1]
        else:
            return TradingSignal(
                signal=SignalType.HOLD,
                price=self.data.Close[-1] if len(self.data.Close) > 0 else 0.0,
                timestamp=pd.Timestamp.now(),
                indicators=self.indicators_values.copy(),
            )


class SmaCrossSignalStrategy(SignalExtractorStrategy):
    """
    Modified SMA Cross strategy that generates signals instead of trades
    """

    n1 = 10
    n2 = 20

    def init(self):
        # Import the SMA function
        if not BACKTESTING_AVAILABLE:
            raise ImportError(
                "backtesting.py support is not installed. Run:\n"
                "    pip install stratequeue[backtesting]\n"
                "or\n"
                "    pip install backtesting"
            )
        from backtesting.test import SMA

        close = self.data.Close
        self.sma1 = self.I(SMA, close, self.n1)
        self.sma2 = self.I(SMA, close, self.n2)

    def next(self):
        # Update indicator values for signal output
        self.indicators_values = {
            f"SMA_{self.n1}": self.sma1[-1],
            f"SMA_{self.n2}": self.sma2[-1],
            "price": self.data.Close[-1],
        }

        # Determine signal based on crossover
        if crossover(self.sma1, self.sma2):
            # Fast MA crosses above slow MA - bullish signal
            self.set_signal(SignalType.BUY)

        elif crossover(self.sma2, self.sma1):
            # Fast MA crosses below slow MA - bearish signal
            self.set_signal(SignalType.SELL)

        else:
            # No crossover - hold current position
            self.set_signal(SignalType.HOLD)


class LiveSignalExtractor:
    """
    Extracts live trading signals from backtesting.py strategies
    """

    def __init__(self, strategy_class, min_bars_required: int = 2, enable_position_tracking: bool = True, **strategy_params):
        """
        Initialize with a strategy class and its parameters

        Args:
            strategy_class: A SignalExtractorStrategy subclass
            min_bars_required: Minimum number of bars needed for signal extraction
            enable_position_tracking: Whether to track position state and adjust signals accordingly
            **strategy_params: Parameters to pass to the strategy
        """
        if not BACKTESTING_AVAILABLE:
            raise ImportError(
                "backtesting.py support is not installed. Run:\n"
                "    pip install stratequeue[backtesting]\n"
                "or\n"
                "    pip install backtesting"
            )
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.min_bars_required = min_bars_required
        self.enable_position_tracking = enable_position_tracking
        self.last_signal = None
        
        # Track position state across signal extractions
        self._position_state = {
            'is_long': False,
            'entry_price': None,
            'entry_timestamp': None,
            'size': 0.0
        }

    def extract_signal(self, historical_data: pd.DataFrame) -> TradingSignal:
        """
        Extract current trading signal from historical data

        Args:
            historical_data: DataFrame with OHLCV data, indexed by timestamp

        Returns:
            TradingSignal object with current signal
        """
        try:
            # Ensure we have enough data
            if len(historical_data) < self.min_bars_required:
                logger.warning("Insufficient historical data for signal extraction")
                return TradingSignal(
                    signal=SignalType.HOLD,
                    price=0.0,
                    timestamp=pd.Timestamp.now(),
                    indicators={},
                )

            # Prepare data for backtesting.py format
            # Ensure columns are properly named
            required_columns = ["Open", "High", "Low", "Close", "Volume"]
            if not all(col in historical_data.columns for col in required_columns):
                logger.error(f"Historical data missing required columns: {required_columns}")
                raise ValueError("Invalid data format")

            data = historical_data[required_columns].copy()

            # Create a backtest instance but don't run full backtest
            # We'll manually step through to the last bar
            bt = Backtest(
                data,
                self.strategy_class,
                cash=10000,  # Dummy cash amount
                commission=0.0,  # No commission for signal extraction
                **self.strategy_params,
            )

            # Run the backtest to initialize strategy and process all historical data
            results = bt.run()

            # Extract the strategy instance to get the current signal
            strategy_instance = results._strategy

            # Get the current signal from the strategy
            current_signal = strategy_instance.get_current_signal()
            
            # Debug: Log indicator values and raw signal to understand what's happening
            if hasattr(current_signal, 'indicators') and current_signal.indicators:
                logger.debug(f"Indicators: {current_signal.indicators}")
            logger.debug(f"Raw strategy signal: {current_signal.signal.value}")
            
            # For SMA strategies, use manual crossover detection to fix the sliding window issue
            logger.debug(f"Strategy class: {self.strategy_class.__name__}")
            logger.debug(f"Has n1: {hasattr(self.strategy_class, 'n1')}, Has n2: {hasattr(self.strategy_class, 'n2')}")
            if hasattr(self.strategy_class, 'n1') and hasattr(self.strategy_class, 'n2'):
                manual_signal = self._detect_sma_crossover(historical_data)
                logger.debug(f"Manual crossover detection result: {manual_signal}")
                if manual_signal != 'HOLD':
                    logger.debug(f"Manual crossover detection overriding strategy signal: {manual_signal}")
                    # Create a new signal with the manual detection result
                    signal_type = SignalType.BUY if manual_signal == 'BUY' else SignalType.CLOSE
                    current_signal = TradingSignal(
                        signal=signal_type,
                        price=current_signal.price,
                        timestamp=current_signal.timestamp,
                        indicators=current_signal.indicators,
                        metadata={**current_signal.metadata, 'manual_crossover': True}
                    )
            
            # Override signal based on actual position state for live trading BEFORE updating position state
            if self.enable_position_tracking:
                adjusted_signal = self._adjust_signal_for_position_state(current_signal)
                # Update position state based on the adjusted signal
                self._update_position_state(adjusted_signal)
            else:
                adjusted_signal = current_signal

            self.last_signal = adjusted_signal

            from ..utils.price_formatter import PriceFormatter
            logger.info(
                f"Extracted signal: {adjusted_signal.signal.value} "
                f"at price: {PriceFormatter.format_price_for_logging(adjusted_signal.price)} "
                f"(position: {'LONG' if self._position_state['is_long'] else 'NONE'})"
            )

            return adjusted_signal

        except Exception as e:
            logger.error(f"Error extracting signal: {e}")
            # Return safe default signal
            return TradingSignal(
                signal=SignalType.HOLD,
                price=historical_data["Close"].iloc[-1] if len(historical_data) > 0 else 0.0,
                timestamp=pd.Timestamp.now(),
                indicators={},
                metadata={"error": str(e)},
            )
    
    def _update_position_state(self, signal: TradingSignal):
        """Update internal position state based on signal"""
        if signal.signal == SignalType.BUY and not self._position_state['is_long']:
            # Enter long position
            self._position_state['is_long'] = True
            self._position_state['entry_price'] = signal.price
            self._position_state['entry_timestamp'] = signal.timestamp
            self._position_state['size'] = signal.size or 1.0
            logger.debug(f"Position state: Entered LONG at {signal.price}")
            
        elif signal.signal in [SignalType.SELL, SignalType.CLOSE] and self._position_state['is_long']:
            # Exit long position
            self._position_state['is_long'] = False
            self._position_state['entry_price'] = None
            self._position_state['entry_timestamp'] = None
            self._position_state['size'] = 0.0
            logger.debug(f"Position state: Exited LONG at {signal.price}")
    
    def _detect_sma_crossover(self, historical_data: pd.DataFrame) -> str:
        """
        Detect SMA crossover manually since backtesting.py crossover() doesn't work well with sliding windows
        
        Returns:
            'BUY' if fast SMA crosses above slow SMA
            'SELL' if slow SMA crosses above fast SMA  
            'HOLD' if no crossover
        """
        if len(historical_data) < 4:  # Need at least 4 bars for crossover detection
            return 'HOLD'
            
        # Calculate SMAs manually
        close_prices = historical_data['Close']
        sma1 = close_prices.rolling(window=1).mean()  # Fast SMA (current price)
        sma2 = close_prices.rolling(window=3).mean()  # Slow SMA
        
        # Check for crossover in the last 2 bars
        if len(sma1) >= 2 and len(sma2) >= 2:
            # Current values
            sma1_current = sma1.iloc[-1]
            sma2_current = sma2.iloc[-1]
            
            # Previous values
            sma1_prev = sma1.iloc[-2]
            sma2_prev = sma2.iloc[-2]
            
            # Detect crossover
            if sma1_prev <= sma2_prev and sma1_current > sma2_current:
                # Fast SMA crosses above slow SMA -> BUY
                logger.debug(f"SMA crossover detected: BUY (sma1: {sma1_prev:.2f}->{sma1_current:.2f}, sma2: {sma2_prev:.2f}->{sma2_current:.2f})")
                return 'BUY'
            elif sma1_prev >= sma2_prev and sma1_current < sma2_current:
                # Slow SMA crosses above fast SMA -> SELL
                logger.debug(f"SMA crossover detected: SELL (sma1: {sma1_prev:.2f}->{sma1_current:.2f}, sma2: {sma2_prev:.2f}->{sma2_current:.2f})")
                return 'SELL'
        
        return 'HOLD'
    
    def _adjust_signal_for_position_state(self, signal: TradingSignal) -> TradingSignal:
        """Adjust signal based on current position state for live trading"""
        logger.debug(f"Adjusting signal: {signal.signal.value}, position_long: {self._position_state['is_long']}")
        
        # If we're already in a position and get another BUY signal, convert to HOLD
        if signal.signal == SignalType.BUY and self._position_state['is_long']:
            logger.debug("Converting BUY to HOLD - already in position")
            return TradingSignal(
                signal=SignalType.HOLD,
                price=signal.price,
                timestamp=signal.timestamp,
                indicators=signal.indicators,
                metadata={**signal.metadata, 'reason': 'already_in_position'},
                size=signal.size,
                limit_price=signal.limit_price,
                stop_price=signal.stop_price,
                trail_percent=signal.trail_percent,
                trail_price=signal.trail_price,
                time_in_force=signal.time_in_force,
                strategy_id=signal.strategy_id
            )
        
        # If we're not in a position and get a SELL/CLOSE signal, convert to HOLD
        if signal.signal in [SignalType.SELL, SignalType.CLOSE] and not self._position_state['is_long']:
            logger.debug("Converting SELL/CLOSE to HOLD - no position to close")
            return TradingSignal(
                signal=SignalType.HOLD,
                price=signal.price,
                timestamp=signal.timestamp,
                indicators=signal.indicators,
                metadata={**signal.metadata, 'reason': 'no_position_to_close'},
                size=signal.size,
                limit_price=signal.limit_price,
                stop_price=signal.stop_price,
                trail_percent=signal.trail_percent,
                trail_price=signal.trail_price,
                time_in_force=signal.time_in_force,
                strategy_id=signal.strategy_id
            )
        
        # If we're in a position and get a SELL/CLOSE signal, pass it through
        if signal.signal in [SignalType.SELL, SignalType.CLOSE] and self._position_state['is_long']:
            logger.debug("Passing through SELL/CLOSE signal - have position to close")
            return signal
        
        # Signal is appropriate for current position state
        logger.debug("Passing through signal unchanged")
        return signal
    
    def get_position_state(self) -> dict:
        """Get current position state for debugging"""
        return self._position_state.copy()
    
    def reset_position_state(self):
        """Reset position state (useful for testing or manual intervention)"""
        self._position_state = {
            'is_long': False,
            'entry_price': None,
            'entry_timestamp': None,
            'size': 0.0
        }
        logger.info("Position state reset")


# Example usage and testing
if __name__ == "__main__":
    # Test the signal extractor with sample data
    import asyncio

    from data_ingestion import TestDataIngestion

    async def test_signal_extraction():
        """Test signal extraction with generated data"""
        print("=== Signal Extraction Test ===")

        # Generate test data
        data_ingestion = TestDataIngestion()
        historical_data = await data_ingestion.fetch_historical_data("AAPL", days_back=30)

        if len(historical_data) == 0:
            print("No historical data available for testing")
            return

        print(f"Generated {len(historical_data)} bars of test data")
        print(
            f"Price range: ${historical_data['Low'].min():.2f} - ${historical_data['High'].max():.2f}"
        )

        # Initialize signal extractor
        signal_extractor = LiveSignalExtractor(SmaCrossSignalStrategy, n1=10, n2=20)

        # Extract signal from different data windows to simulate live updates
        print("\nExtracting signals from different time windows:")

        for i in range(5):
            # Use progressively more data (simulating live updates)
            end_idx = len(historical_data) - 5 + i
            if end_idx <= 20:  # Need minimum data for indicators
                continue

            data_window = historical_data.iloc[:end_idx]
            signal = signal_extractor.extract_signal(data_window)

            print(
                f"Window {i+1}: {signal.signal.value} "
                f"at ${signal.price:.2f}"
            )

    # Run the test
    asyncio.run(test_signal_extraction())
