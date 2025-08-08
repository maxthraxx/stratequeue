"""
Position Sizer

Broker-independent position sizing for trading signals.
Implements pluggable sizing algorithms following the strategy pattern.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from .signal_extractor import TradingSignal
from .portfolio_manager import SimplePortfolioManager

if TYPE_CHECKING:
    from ..brokers.broker_base import BrokerCapabilities

logger = logging.getLogger(__name__)


class PositionSizingStrategy(ABC):
    """Abstract base class for position sizing strategies"""

    @abstractmethod
    def calculate_size(
        self,
        strategy_id: str | None,
        symbol: str,
        signal: TradingSignal,
        price: float,
        portfolio_manager: SimplePortfolioManager | None = None,
        **kwargs
    ) -> float:
        """
        Calculate position size for a trading signal

        Args:
            strategy_id: Strategy identifier (None for single strategy)
            symbol: Trading symbol
            signal: Trading signal
            price: Current price
            portfolio_manager: Portfolio manager instance
            **kwargs: Additional parameters

        Returns:
            Position size in dollars
        """
        pass


class FixedDollarSizing(PositionSizingStrategy):
    """Fixed dollar amount per trade"""

    def __init__(self, amount: float = 100.0):
        """
        Initialize fixed dollar sizing

        Args:
            amount: Fixed dollar amount per trade
        """
        self.amount = amount

    def calculate_size(
        self,
        strategy_id: str | None,
        symbol: str,
        signal: TradingSignal,
        price: float,
        portfolio_manager: SimplePortfolioManager | None = None,
        **kwargs
    ) -> float:
        """Return fixed dollar amount"""
        return self.amount


class PercentOfCapitalSizing(PositionSizingStrategy):
    """Percentage of available capital per trade"""

    def __init__(self, percentage: float = 0.1, max_amount: float | None = None):
        """
        Initialize percent of capital sizing

        Args:
            percentage: Percentage of available capital (0.0 to 1.0)
            max_amount: Maximum dollar amount per trade
        """
        self.percentage = percentage
        self.max_amount = max_amount

    def calculate_size(
        self,
        strategy_id: str | None,
        symbol: str,
        signal: TradingSignal,
        price: float,
        portfolio_manager: SimplePortfolioManager | None = None,
        **kwargs
    ) -> float:
        """Calculate percentage of available capital"""
        if portfolio_manager and strategy_id:
            # Multi-strategy mode: get available capital for this strategy
            strategy_status = portfolio_manager.get_strategy_status(strategy_id)
            available_capital = strategy_status.get("available_capital", 100.0)
            position_size = available_capital * self.percentage
        else:
            # Single strategy mode: use default fallback
            # Could be enhanced to use account info if available
            available_capital = kwargs.get("account_value", 10000.0)
            position_size = available_capital * self.percentage

        # Apply maximum limit only if specified
        if self.max_amount is not None:
            position_size = min(position_size, self.max_amount)
        
        return position_size


class VolatilityBasedSizing(PositionSizingStrategy):
    """Position sizing based on volatility (ATR-based risk)"""

    def __init__(self, risk_per_trade: float = 0.02, fallback_sizing: PositionSizingStrategy = None):
        """
        Initialize volatility-based sizing

        Args:
            risk_per_trade: Risk percentage per trade (0.0 to 1.0)
            fallback_sizing: Fallback strategy if volatility data unavailable
        """
        self.risk_per_trade = risk_per_trade
        self.fallback_sizing = fallback_sizing or FixedDollarSizing(100.0)

    def calculate_size(
        self,
        strategy_id: str | None,
        symbol: str,
        signal: TradingSignal,
        price: float,
        portfolio_manager: SimplePortfolioManager | None = None,
        **kwargs
    ) -> float:
        """Calculate position size based on volatility"""
        # Check if ATR or volatility data is available in signal metadata
        atr = None
        if signal.metadata:
            atr = signal.metadata.get("atr") or signal.metadata.get("volatility")

        if atr and atr > 0:
            # Get available capital
            if portfolio_manager and strategy_id:
                strategy_status = portfolio_manager.get_strategy_status(strategy_id)
                available_capital = strategy_status.get("available_capital", 100.0)
            else:
                available_capital = kwargs.get("account_value", 10000.0)

            # Calculate position size based on risk
            # Risk per trade = position_size * (atr / price)
            # Therefore: position_size = (available_capital * risk_per_trade) / (atr / price)
            position_size = (available_capital * self.risk_per_trade * price) / atr
            return max(position_size, 10.0)  # Minimum $10 position
        else:
            # Fallback if no volatility data
            logger.debug(f"No volatility data for {symbol}, using fallback sizing")
            return self.fallback_sizing.calculate_size(
                strategy_id, symbol, signal, price, portfolio_manager, **kwargs
            )


class PositionSizer:
    """
    Main position sizing coordinator

    Uses pluggable strategies to determine position sizes for trading signals.
    Converts sizing intents (units, equity_pct, notional) to executable quantities.
    """

    def __init__(self, strategy: PositionSizingStrategy = None):
        """
        Initialize position sizer

        Args:
            strategy: Position sizing strategy (defaults to PercentOfCapitalSizing)
        """
        self.strategy = strategy or PercentOfCapitalSizing()
        logger.info(f"Initialized position sizer with {self.strategy.__class__.__name__}")

    def calculate_position_size(
        self,
        signal: TradingSignal,
        symbol: str,
        price: float,
        broker_capabilities: "BrokerCapabilities",
        account_value: float,
        available_cash: float,
        current_position: float = 0.0,
        portfolio_manager: SimplePortfolioManager | None = None,
        **kwargs
    ) -> tuple[float, str]:
        """
        Calculate executable position size from trading signal intent
        
        Args:
            signal: Trading signal with sizing intent
            symbol: Trading symbol
            price: Current market price
            broker_capabilities: Broker's trading capabilities and constraints
            account_value: Total account value
            available_cash: Available cash for trading
            current_position: Current position size (for position adjustments)
            portfolio_manager: Portfolio manager instance
            **kwargs: Additional parameters
            
        Returns:
            Tuple of (executable_quantity, reasoning) where:
            - executable_quantity: Final quantity to trade (in units)
            - reasoning: Human-readable explanation of sizing decision
        """
        # Get the sizing intent from the signal
        sizing_intent = signal.get_sizing_intent()
        
        if sizing_intent is None:
            # No explicit sizing intent, use legacy strategy
            dollar_size = self.strategy.calculate_size(
                signal.strategy_id, symbol, signal, price, portfolio_manager, 
                account_value=account_value, **kwargs
            )
            raw_quantity = dollar_size / price
            final_quantity, reasoning = self._apply_broker_constraints(
                raw_quantity, price, broker_capabilities, available_cash
            )
            return final_quantity, f"Legacy sizing: {reasoning}"
        
        intent_type, intent_value = sizing_intent
        
        if intent_type == "units":
            # Direct unit specification
            raw_quantity = intent_value
            final_quantity, reasoning = self._apply_broker_constraints(
                raw_quantity, price, broker_capabilities, available_cash
            )
            return final_quantity, f"Direct units ({intent_value}): {reasoning}"
            
        elif intent_type == "equity_pct":
            # Percentage of equity
            if intent_value < 0 or intent_value > 1:
                raise ValueError(f"equity_pct must be between 0 and 1, got {intent_value}")
            
            dollar_size = account_value * intent_value
            raw_quantity = dollar_size / price
            final_quantity, reasoning = self._apply_broker_constraints(
                raw_quantity, price, broker_capabilities, available_cash
            )
            return final_quantity, f"Equity {intent_value*100:.1f}% (${dollar_size:.2f}): {reasoning}"
            
        elif intent_type == "notional":
            # Dollar amount
            dollar_size = intent_value
            raw_quantity = dollar_size / price
            final_quantity, reasoning = self._apply_broker_constraints(
                raw_quantity, price, broker_capabilities, available_cash
            )
            return final_quantity, f"Notional ${intent_value:.2f}: {reasoning}"
            
        else:
            raise ValueError(f"Unknown sizing intent type: {intent_type}")
    
    def _apply_broker_constraints(
        self, 
        raw_quantity: float, 
        price: float, 
        capabilities: "BrokerCapabilities",
        available_cash: float
    ) -> tuple[float, str]:
        """
        Apply broker constraints to raw quantity calculation
        
        Args:
            raw_quantity: Raw calculated quantity
            price: Current market price
            capabilities: Broker capabilities
            available_cash: Available cash for trading
            
        Returns:
            Tuple of (constrained_quantity, reasoning)
        """
        reasoning_parts = []
        
        # Check minimum notional value
        notional_value = abs(raw_quantity) * price
        if notional_value < capabilities.min_notional:
            reasoning_parts.append(f"below min notional ${capabilities.min_notional}")
            return 0.0, f"rejected - {', '.join(reasoning_parts)}"
        
        # Check available cash
        required_cash = abs(raw_quantity) * price
        if required_cash > available_cash:
            # Reduce quantity to fit available cash
            max_affordable_quantity = available_cash / price
            raw_quantity = max_affordable_quantity if raw_quantity > 0 else -max_affordable_quantity
            reasoning_parts.append(f"reduced to fit available cash ${available_cash:.2f}")

        # NEW: Enforce at least 1 whole share/contract when fractional shares are not allowed
        if not capabilities.fractional_shares and 0 < abs(raw_quantity) < 1:
            raw_quantity = 1 if raw_quantity > 0 else -1
            reasoning_parts.append("rounded up to minimum whole share")

        # Apply lot size constraints
        if capabilities.min_lot_size > 0:
            # Round to nearest lot size
            lots = round(raw_quantity / capabilities.min_lot_size)
            constrained_quantity = lots * capabilities.min_lot_size
            if abs(constrained_quantity - raw_quantity) > 0.001:  # Significant rounding
                reasoning_parts.append(f"rounded to lot size {capabilities.min_lot_size}")
            raw_quantity = constrained_quantity
        
        # Apply step size constraints
        if capabilities.step_size > 0:
            # Round to nearest step
            steps = round(raw_quantity / capabilities.step_size)
            constrained_quantity = steps * capabilities.step_size
            if abs(constrained_quantity - raw_quantity) > 0.001:  # Significant rounding
                reasoning_parts.append(f"rounded to step size {capabilities.step_size}")
            raw_quantity = constrained_quantity
        
        # Handle fractional shares
        if not capabilities.fractional_shares:
            # Round to whole shares
            whole_quantity = round(raw_quantity)
            if abs(whole_quantity - raw_quantity) > 0.001:  # Significant rounding
                reasoning_parts.append("rounded to whole shares")
            raw_quantity = whole_quantity
        
        # Apply maximum position size
        if capabilities.max_position_size is not None:
            if abs(raw_quantity) > capabilities.max_position_size:
                raw_quantity = capabilities.max_position_size if raw_quantity > 0 else -capabilities.max_position_size
                reasoning_parts.append(f"capped at max position {capabilities.max_position_size}")
        
        # Final check - ensure we still meet minimum notional after constraints
        final_notional = abs(raw_quantity) * price
        if final_notional < capabilities.min_notional and raw_quantity != 0:
            reasoning_parts.append(f"final notional ${final_notional:.2f} below min ${capabilities.min_notional}")
            return 0.0, f"rejected - {', '.join(reasoning_parts)}"
        
        if not reasoning_parts:
            reasoning_parts.append("no constraints applied")
            
        return raw_quantity, ', '.join(reasoning_parts)

    def get_position_size(
        self,
        strategy_id: str | None,
        symbol: str,
        signal: TradingSignal,
        price: float,
        portfolio_manager: SimplePortfolioManager | None = None,
        **kwargs
    ) -> float:
        """
        Get position size for a trading signal (legacy method)

        Args:
            strategy_id: Strategy identifier (None for single strategy)
            symbol: Trading symbol
            signal: Trading signal
            price: Current price
            portfolio_manager: Portfolio manager instance
            **kwargs: Additional parameters (e.g., account_value)

        Returns:
            Position size in dollars
        """
        try:
            # Check if signal already has a size specified
            if signal.size is not None and signal.size > 0:
                logger.debug(f"Using strategy-specified size for {symbol}: ${signal.size:.2f}")
                return signal.size

            # Calculate size using the configured strategy
            position_size = self.strategy.calculate_size(
                strategy_id, symbol, signal, price, portfolio_manager, **kwargs
            )

            logger.debug(
                f"Calculated position size for {symbol} using {self.strategy.__class__.__name__}: "
                f"${position_size:.2f}"
            )

            return max(position_size, 1.0)  # Ensure minimum $1 position

        except Exception as e:
            logger.error(f"Error calculating position size for {symbol}: {e}")
            # Emergency fallback
            return 100.0

    def set_strategy(self, strategy: PositionSizingStrategy):
        """
        Change the position sizing strategy

        Args:
            strategy: New position sizing strategy
        """
        old_strategy = self.strategy.__class__.__name__
        self.strategy = strategy
        logger.info(f"Changed position sizing strategy: {old_strategy} → {strategy.__class__.__name__}")


# Default instance for backward compatibility
default_position_sizer = PositionSizer() 