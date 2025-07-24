"""
BT Engine Implementation

Implements the trading engine interface for bt (backtest library) strategies.
This module contains all the bt-specific logic for loading strategies
and extracting signals.
"""

import ast
import inspect
import logging
from typing import Any, Dict, Type

import pandas as pd

# Conditional import for bt library with dependency checking
try:
    import bt
    BT_AVAILABLE = True
except ImportError as e:
    BT_AVAILABLE = False
    bt = None
    logger = logging.getLogger(__name__)
    logger.warning(f"bt library not available: {e}")

from ..core.signal_extractor import SignalType, TradingSignal
from ..core.base_signal_extractor import BaseSignalExtractor
from .engine_base import (
    EngineInfo, EngineSignalExtractor, EngineStrategy, TradingEngine,
    build_engine_info
)

logger = logging.getLogger(__name__)


class BtEngineStrategy(EngineStrategy):
    """Wrapper for bt.Strategy objects"""

    def __init__(self, strategy_obj: Any, strategy_params: Dict[str, Any] = None):
        """
        Initialize BtEngineStrategy wrapper
        
        Args:
            strategy_obj: bt.Strategy object
            strategy_params: Optional parameters for the strategy
        """
        # For bt strategies, we store the strategy object directly
        # since bt.Strategy is an instance, not a class
        super().__init__(type(strategy_obj), strategy_params)
        self.strategy_obj = strategy_obj

    def get_lookback_period(self) -> int:
        """Get the minimum number of bars required by this strategy"""
        # Check if the strategy object has a get_lookback_period method
        if hasattr(self.strategy_obj, 'get_lookback_period') and callable(getattr(self.strategy_obj, 'get_lookback_period')):
            return self.strategy_obj.get_lookback_period()
        
        # bt strategies typically need at least 20 bars for meaningful backtests
        # This can be refined based on the specific algos used in the strategy
        return 20

    def get_strategy_name(self) -> str:
        """Get a human-readable name for this strategy"""
        if hasattr(self.strategy_obj, 'name') and self.strategy_obj.name:
            return self.strategy_obj.name
        return f"BtStrategy_{id(self.strategy_obj)}"

    def get_parameters(self) -> Dict[str, Any]:
        """Get strategy parameters from bt.Strategy object"""
        params = {}
        
        # Extract parameters from the strategy object
        if hasattr(self.strategy_obj, '__dict__'):
            for attr_name, attr_value in self.strategy_obj.__dict__.items():
                # Skip private attributes and complex objects
                if (not attr_name.startswith('_') and 
                    not callable(attr_value) and
                    isinstance(attr_value, (str, int, float, bool, list, dict))):
                    params[attr_name] = attr_value
        
        # Add strategy_params passed to constructor
        if self.strategy_params:
            params.update(self.strategy_params)
        
        return params


class BtEngineStrategyFactory(EngineStrategy):
    """Wrapper for bt strategy factory functions"""

    def __init__(self, strategy_factory: callable, strategy_params: Dict[str, Any] = None):
        """
        Initialize BtEngineStrategyFactory wrapper
        
        Args:
            strategy_factory: Function that creates bt.Strategy objects
            strategy_params: Optional parameters for the strategy factory
        """
        super().__init__(strategy_factory, strategy_params)
        self.strategy_factory = strategy_factory
        self._cached_strategy = None

    def _create_strategy_with_data(self, data: pd.DataFrame) -> bt.Strategy:
        """Create strategy instance using the factory function/class with data"""
        try:
            # Handle classes differently from functions
            if inspect.isclass(self.strategy_factory):
                return self._create_strategy_from_class(data)
            else:
                return self._create_strategy_from_function(data)
        except Exception as e:
            logger.error(f"Error creating strategy from factory {self.strategy_factory.__name__}: {e}")
            raise

    def _create_strategy_from_function(self, data: pd.DataFrame) -> bt.Strategy:
        """Create strategy from a function"""
        # Get function signature to determine how to call it
        sig = inspect.signature(self.strategy_factory)
        
        # Try different calling patterns
        strategies_to_try = []
        
        # Pattern 1: Call with data and filtered parameters
        if 'data' in sig.parameters:
            if self.strategy_params:
                valid_params = {k: v for k, v in self.strategy_params.items() if k in sig.parameters}
                strategies_to_try.append(lambda: self.strategy_factory(data, **valid_params))
            else:
                strategies_to_try.append(lambda: self.strategy_factory(data))
        
        # Pattern 2: Call with no arguments (for parameterless functions)
        elif len(sig.parameters) == 0:
            strategies_to_try.append(lambda: self.strategy_factory())
        
        # Pattern 3: Call with just parameters (data might be handled internally)
        elif self.strategy_params:
            valid_params = {k: v for k, v in self.strategy_params.items() if k in sig.parameters}
            if valid_params:
                strategies_to_try.append(lambda: self.strategy_factory(**valid_params))
        
        # Try each pattern until one works
        for strategy_creator in strategies_to_try:
            try:
                strategy = strategy_creator()
                if isinstance(strategy, bt.Strategy):
                    return strategy
            except Exception as e:
                logger.debug(f"Strategy creation attempt failed: {e}")
                continue
        
        # If all patterns fail, raise an error
        raise ValueError(f"Could not create strategy from function {self.strategy_factory.__name__}")

    def _create_strategy_from_class(self, data: pd.DataFrame) -> bt.Strategy:
        """Create strategy from a class"""
        # Try to instantiate the class and look for strategy creation methods
        try:
            # Try instantiating with data
            if self.strategy_params:
                instance = self.strategy_factory(data, **self.strategy_params)
            else:
                instance = self.strategy_factory(data)
            
            # If the instance itself is a bt.Strategy, return it
            if isinstance(instance, bt.Strategy):
                return instance
                
        except Exception:
            # Try instantiating without data
            try:
                if self.strategy_params:
                    instance = self.strategy_factory(**self.strategy_params)
                else:
                    instance = self.strategy_factory()
                
                # If the instance itself is a bt.Strategy, return it
                if isinstance(instance, bt.Strategy):
                    return instance
                
                # Look for strategy creation methods
                for method_name in ['create_strategy', 'build_strategy', 'get_strategy', 'strategy']:
                    if hasattr(instance, method_name):
                        method = getattr(instance, method_name)
                        if callable(method):
                            try:
                                strategy = method(data)
                                if isinstance(strategy, bt.Strategy):
                                    return strategy
                            except Exception:
                                try:
                                    strategy = method()
                                    if isinstance(strategy, bt.Strategy):
                                        return strategy
                                except Exception:
                                    continue
                                    
            except Exception:
                pass
        
        raise ValueError(f"Could not create strategy from class {self.strategy_factory.__name__}")

    def get_strategy_for_data(self, data: pd.DataFrame) -> bt.Strategy:
        """Get strategy instance for given data"""
        return self._create_strategy_with_data(data)

    def get_lookback_period(self) -> int:
        """Get the minimum number of bars required by this strategy"""
        # For factory functions, we need to make a reasonable assumption
        # Most mean reversion strategies need at least 20-50 bars for lookback calculations
        return 50

    def get_strategy_name(self) -> str:
        """Get a human-readable name for this strategy"""
        return self.strategy_factory.__name__

    def get_parameters(self) -> Dict[str, Any]:
        """Get strategy parameters from factory function"""
        params = {}
        
        # Extract default parameters from function signature
        try:
            sig = inspect.signature(self.strategy_factory)
            for param_name, param in sig.parameters.items():
                if param.default != inspect.Parameter.empty:
                    params[param_name] = param.default
        except (ValueError, TypeError):
            pass
        
        # Add strategy_params passed to constructor (these override defaults)
        if self.strategy_params:
            params.update(self.strategy_params)
        
        return params


class BtSignalExtractor(BaseSignalExtractor, EngineSignalExtractor):
    """Signal extractor for bt strategies"""

    def __init__(self, engine_strategy, min_bars_required: int = None, 
                 granularity: str = '1min', **kwargs):
        """
        Initialize BtSignalExtractor
        
        Args:
            engine_strategy: BtEngineStrategy or BtEngineStrategyFactory wrapper
            min_bars_required: Minimum bars needed for signal extraction (defaults to strategy's lookback period)
            granularity: Data granularity
            **kwargs: Additional parameters
        """
        super().__init__(engine_strategy)
        self.engine_strategy = engine_strategy
        # Use strategy's lookback period if min_bars_required not specified
        self.min_bars_required = min_bars_required if min_bars_required is not None else engine_strategy.get_lookback_period()
        self.granularity = granularity

    def extract_signal(self, historical_data: pd.DataFrame) -> TradingSignal:
        """Extract trading signal from historical data using bt strategy"""
        try:
            # Check for insufficient data first
            if (hold_signal := self._abort_insufficient_bars(historical_data)):
                return hold_signal
            
            # Validate data format
            data = self._validate_and_prepare_data(historical_data)
            
            # Run bt backtest and extract signals
            return self._run_bt_backtest_and_extract_signal(data)
            
        except Exception as e:
            logger.error(f"Error extracting bt signal: {e}")
            # Return safe default signal
            price = self._safe_get_last_value(historical_data['Close']) if len(historical_data) > 0 and 'Close' in historical_data.columns else 0.0
            return self._safe_hold(price=price, error=e)

    def _validate_and_prepare_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Validate and prepare data for bt processing
        
        Args:
            data: Raw historical data
            
        Returns:
            Prepared data for bt backtest
        """
        if data.empty:
            raise ValueError("Empty data provided")
        
        # bt expects data with proper column names
        # Normalize column names to match bt expectations
        data = data.copy()
        
        # Ensure we have at least Close data
        if 'Close' not in data.columns and 'close' not in data.columns:
            raise ValueError("Data must contain 'Close' price information")
        
        # Normalize column names to title case
        column_mapping = {}
        for col in data.columns:
            col_lower = col.lower()
            if col_lower in ['close', 'c']:
                column_mapping[col] = 'Close'
            elif col_lower in ['open', 'o']:
                column_mapping[col] = 'Open'
            elif col_lower in ['high', 'h']:
                column_mapping[col] = 'High'
            elif col_lower in ['low', 'l']:
                column_mapping[col] = 'Low'
            elif col_lower in ['volume', 'vol', 'v']:
                column_mapping[col] = 'Volume'
        
        data = data.rename(columns=column_mapping)
        
        # Ensure numeric data types
        numeric_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in numeric_columns:
            if col in data.columns:
                data[col] = pd.to_numeric(data[col], errors='coerce')
        
        # Handle NaN values
        if data.isnull().any().any():
            logger.warning("Data contains NaN values, forward filling...")
            data = data.ffill().bfill()
        
        return data

    def _run_bt_backtest_and_extract_signal(self, data: pd.DataFrame) -> TradingSignal:
        """
        Run bt backtest and extract trading signal
        
        Args:
            data: Prepared historical data
            
        Returns:
            TradingSignal extracted from backtest results
        """
        try:
            # Get the strategy object (either direct or from factory)
            if isinstance(self.engine_strategy, BtEngineStrategyFactory):
                strategy_obj = self.engine_strategy.get_strategy_for_data(data)
            else:
                strategy_obj = self.engine_strategy.strategy_obj
            
            # Create bt backtest with the strategy and data
            backtest = bt.Backtest(strategy_obj, data)
            
            # Run the backtest
            result = bt.run(backtest)
            
            # Extract portfolio weights from the backtest object itself
            return self._extract_signal_from_backtest_object(backtest, data)
            
        except Exception as e:
            logger.error(f"Error running bt backtest: {e}")
            current_price = self._safe_get_last_value(data['Close'])
            return self._safe_hold(price=current_price, error=e)

    def _extract_signal_from_backtest_result(self, result, data: pd.DataFrame) -> TradingSignal:
        """
        Extract trading signal from bt backtest result
        
        Args:
            result: bt backtest result
            data: Historical data used in backtest
            
        Returns:
            TradingSignal based on portfolio weights
        """
        try:
            current_price = self._safe_get_last_value(data['Close'])
            
            # Get the backtest result (first and only backtest)
            backtest_result = result[list(result.keys())[0]]
            
            # Extract security weights from the last day
            if hasattr(backtest_result, 'security_weights') and not backtest_result.security_weights.empty:
                last_weights = backtest_result.security_weights.iloc[-1]
                
                # Convert weights to signals
                signals = self._convert_weights_to_signals(last_weights, current_price)
                
                # For single security, return the first signal
                if signals:
                    return signals[0]
            
            # Fallback to HOLD if no weights available
            return self._create_hold_signal(current_price, data.index[-1])
            
        except Exception as e:
            logger.error(f"Error extracting signal from backtest result: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            current_price = self._safe_get_last_value(data['Close'])
            return self._safe_hold(price=current_price, error=e)

    def _convert_weights_to_signals(self, weights: pd.Series, current_price: float) -> list[TradingSignal]:
        """
        Convert portfolio weights to trading signals
        
        Args:
            weights: Portfolio weights from bt backtest
            current_price: Current price for the signal
            
        Returns:
            List of TradingSignal objects
        """
        signals = []
        
        for security, weight in weights.items():
            # Convert weight to signal type
            if abs(weight) < 1e-6:  # Essentially zero
                signal_type = SignalType.HOLD
            elif weight > 0:
                signal_type = SignalType.BUY
            else:
                signal_type = SignalType.SELL  # For short positions
            
            # Create indicators
            indicators = self._clean_indicators({
                "security": security,
                "weight": float(weight),
                "granularity": self.granularity,
                "current_price": current_price
            })
            
            signal = TradingSignal(
                signal=signal_type,
                price=current_price,
                timestamp=weights.name if hasattr(weights, 'name') else pd.Timestamp.now(),
                indicators=indicators
            )
            
            signals.append(signal)
        
        return signals

    def _extract_signal_from_backtest_object(self, backtest, data: pd.DataFrame) -> TradingSignal:
        """
        Extract trading signal from bt backtest object
        
        Args:
            backtest: bt.Backtest object after running
            data: Historical data used in backtest
            
        Returns:
            TradingSignal based on portfolio weights
        """
        try:
            current_price = self._safe_get_last_value(data['Close'])
            
            # Try to access security_weights from the backtest object
            if hasattr(backtest, 'security_weights') and not backtest.security_weights.empty:
                last_weights = backtest.security_weights.iloc[-1]
                
                # Convert weights to signals
                signals = self._convert_weights_to_signals(last_weights, current_price)
                
                # For single security, return the first signal
                if signals:
                    return signals[0]
            
            # Try to access weights from strategy state as fallback
            if hasattr(backtest, 'strategy') and hasattr(backtest.strategy, 'temp'):
                if 'weights' in backtest.strategy.temp:
                    weights = backtest.strategy.temp['weights']
                    
                    # Convert to pandas Series if needed
                    if not isinstance(weights, pd.Series):
                        weights = pd.Series(weights)
                    
                    # Convert weights to signals
                    signals = self._convert_weights_to_signals(weights, current_price)
                    
                    # For single security, return the first signal
                    if signals:
                        return signals[0]
            
            # Fallback to HOLD if no weights available
            return self._create_hold_signal(current_price, data.index[-1])
            
        except Exception as e:
            logger.error(f"Error extracting signal from backtest object: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            current_price = self._safe_get_last_value(data['Close'])
            return self._safe_hold(price=current_price, error=e)

    def _create_hold_signal(self, price: float, timestamp) -> TradingSignal:
        """Create a HOLD signal with given price and timestamp"""
        indicators = self._clean_indicators({
            "granularity": self.granularity,
            "current_price": price,
            "reason": "no_weights_available"
        })
        
        return TradingSignal(
            signal=SignalType.HOLD,
            price=price,
            timestamp=timestamp,
            indicators=indicators
        )


class BtEngine(TradingEngine):
    """Trading engine implementation for bt library"""
    
    # Set dependency management attributes
    _dependency_available_flag = BT_AVAILABLE
    _dependency_help = (
        "bt library support is not installed. Run:\n"
        "    pip install stratequeue[bt]\n"
        "or\n"
        "    pip install bt"
    )
    
    def __init__(self):
        """Initialize BtEngine with dependency validation"""
        if not self._dependency_available_flag:
            raise ImportError(self._dependency_help)
        super().__init__()
    
    @classmethod
    def dependencies_available(cls) -> bool:
        """Check if bt dependencies are available"""
        return BT_AVAILABLE
    
    def get_engine_info(self) -> EngineInfo:
        """Get information about this engine"""
        return build_engine_info(
            name="bt",
            lib_version=bt.__version__ if bt else "unknown",
            description="Flexible backtesting framework with tree-based algo composition",
            algo_composition=True,
            tree_based_strategies=True
        )
    
    def is_valid_strategy(self, name: str, obj: Any) -> bool:
        """
        Check if object is a valid bt strategy function by analyzing its code structure.
        
        A valid bt strategy function must:
        1. Call bt.run() with a bt.Backtest object
        2. Return a bt.Result object
        
        Args:
            name: Name of the object in the module
            obj: Object to validate
            
        Returns:
            True if object is a valid bt strategy function, False otherwise
        """
        if not BT_AVAILABLE:
            return False
        
        try:
            # Check if it's actually a bt.Strategy instance
            if isinstance(obj, bt.Strategy):
                return True
            
            # Only check functions, not classes
            if not (callable(obj) and not inspect.isclass(obj)):
                return False
                
            # Skip private functions and obvious non-strategy functions
            if name.startswith('_'):
                return False
            
            # Analyze the function's source code for bt-specific patterns
            return self._analyze_function_for_bt_patterns(obj)
            
        except Exception:
            return False

    def _analyze_function_for_bt_patterns(self, func: callable) -> bool:
        """
        Analyze a function's source code to determine if it's a bt strategy.
        
        Args:
            func: Function to analyze
            
        Returns:
            True if function contains bt strategy patterns, False otherwise
        """
        try:
            import ast
            
            # Get the function's source code
            source = inspect.getsource(func)
            
            # Parse the source code into an AST
            tree = ast.parse(source)
            
            # Look for bt-specific patterns in the AST
            visitor = BtPatternVisitor()
            visitor.visit(tree)
            
            # A valid bt strategy must call bt.run() and create bt.Backtest
            return visitor.has_bt_run and visitor.has_bt_backtest
            
        except (OSError, TypeError, ValueError):
            # If we can't get source code, fall back to signature analysis
            return self._fallback_signature_analysis(func)
    
    def _fallback_signature_analysis(self, func: callable) -> bool:
        """
        Fallback method when source code analysis fails.
        Uses function signature and return type hints.
        
        Args:
            func: Function to analyze
            
        Returns:
            True if function signature suggests it's a bt strategy, False otherwise
        """
        try:
            sig = inspect.signature(func)
            
            # Check return type annotation for bt.Result
            if sig.return_annotation != inspect.Signature.empty:
                return_type_str = str(sig.return_annotation)
                if ('bt.Result' in return_type_str or 
                    'Result' in return_type_str or
                    'bt.backtest.Result' in return_type_str):
                    return True
            
            # Check if function has 'data' parameter and reasonable signature for bt strategy
            if ('data' in sig.parameters and 
                len(sig.parameters) <= 4):  # bt strategies typically have few parameters
                return True
                
            return False
            
        except (ValueError, TypeError):
            return False
    
    def get_explicit_marker(self) -> str:
        """Get the explicit marker for bt strategies"""
        return '__bt_strategy__'
    
    def create_engine_strategy(self, strategy_obj: Any) -> BtEngineStrategy:
        """Create a bt engine strategy wrapper"""
        # If it's already a bt.Strategy instance, use it directly
        if isinstance(strategy_obj, bt.Strategy):
            return BtEngineStrategy(strategy_obj)
        
        # If it's a callable (function or class), we need to create a wrapper that can call it with data
        if callable(strategy_obj):
            return BtEngineStrategyFactory(strategy_obj)
        
        raise ValueError(f"Invalid strategy object type: {type(strategy_obj)}")
    
    def create_signal_extractor(self, engine_strategy, 
                              **kwargs) -> BtSignalExtractor:
        """Create a signal extractor for the given strategy"""
        return BtSignalExtractor(engine_strategy, **kwargs)

class BtPatternVisitor(ast.NodeVisitor):
    """AST visitor to detect bt library usage patterns in function source code."""
    
    def __init__(self):
        self.has_bt_run = False
        self.has_bt_backtest = False
        self.has_bt_strategy = False
    
    def visit_Call(self, node):
        """Visit function call nodes to detect bt.run() and bt.Backtest() calls."""
        # Check for bt.run() calls
        if (isinstance(node.func, ast.Attribute) and 
            isinstance(node.func.value, ast.Name) and
            node.func.value.id == 'bt' and 
            node.func.attr == 'run'):
            self.has_bt_run = True
        
        # Check for bt.Backtest() calls
        if (isinstance(node.func, ast.Attribute) and 
            isinstance(node.func.value, ast.Name) and
            node.func.value.id == 'bt' and 
            node.func.attr == 'Backtest'):
            self.has_bt_backtest = True
        
        # Check for bt.Strategy() calls
        if (isinstance(node.func, ast.Attribute) and 
            isinstance(node.func.value, ast.Name) and
            node.func.value.id == 'bt' and 
            node.func.attr == 'Strategy'):
            self.has_bt_strategy = True
        
        # Continue visiting child nodes
        self.generic_visit(node)