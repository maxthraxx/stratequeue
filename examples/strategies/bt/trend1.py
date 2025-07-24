"""
Trend Following Strategy - Time Series Momentum

This strategy implements a trend-following approach based on momentum signals.
It compares current prices to prices from a specified lookback period to determine trend direction.

Strategy Logic:
- Calculate momentum (current price vs price N days ago)
- Go long assets with positive momentum (trending up)
- Daily rebalancing with equal weighting

Based on bt library examples: https://pmorissette.github.io/bt/examples.html#trend-example-1
"""

import bt
import pandas as pd
import numpy as np


def load_aapl_data(filepath='examples/data/AAPL.csv'):
    """
    Load AAPL data from CSV file and format for bt library.
    
    Args:
        filepath: Path to AAPL CSV file
        
    Returns:
        DataFrame with price data formatted for bt
    """
    # Read CSV file
    df = pd.read_csv(filepath)
    
    # Convert Date column to datetime and set as index
    df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y')
    df.set_index('Date', inplace=True)
    
    # Sort by date (oldest first)
    df.sort_index(inplace=True)
    
    # Create price DataFrame with just Close price, renamed to AAPL
    price_data = pd.DataFrame(index=df.index)
    price_data['AAPL'] = df['Close']
    
    return price_data


def create_trend_signal(data, lookback_days=50):
    """
    Create trend signal based on momentum over specified lookback period.
    
    Args:
        data: Price data DataFrame
        lookback_days: Number of days to look back for momentum calculation
        
    Returns:
        Boolean DataFrame where True indicates positive trend
    """
    # Calculate momentum: current price vs price N days ago
    momentum = data / data.shift(lookback_days) - 1
    
    # Create trend signal: True where momentum is positive
    trend = momentum > 0
    
    return trend


def create_trend_strategy(lookback_days=50):
    """
    Create the trend following strategy.
    
    Args:
        lookback_days: Momentum lookback period in days
        
    Returns:
        bt.Strategy object
    """
    return bt.Strategy(
        'TrendStrategy',
        [
            bt.algos.RunDaily(),
            bt.algos.SelectWhere('trend'),
            bt.algos.WeighEqually(),
            bt.algos.Rebalance()
        ]
    )


def run_backtest(data, lookback_days=50, initial_capital=100000.0):
    """
    Run the trend following backtest.
    
    Args:
        data: Price data DataFrame
        lookback_days: Momentum lookback period in days
        initial_capital: Starting capital
        
    Returns:
        bt.Result object
    """
    # Create trend signal
    trend = create_trend_signal(data, lookback_days)
    
    # Create strategy
    strategy = create_trend_strategy(lookback_days)
    
    # Create backtest
    backtest = bt.Backtest(
        strategy,
        data,
        initial_capital=initial_capital,
        additional_data={'trend': trend}
    )
    
    # Run backtest
    result = bt.run(backtest)
    
    return result


# Example usage
if __name__ == "__main__":
    print("Loading AAPL data...")
    
    # Load AAPL data
    data = load_aapl_data('examples/data/AAPL.csv')
    print(f"Data loaded: {data.shape[0]} days from {data.index.min().date()} to {data.index.max().date()}")
    
    # Run trend strategy with 50-day lookback
    print("\nRunning trend following strategy...")
    result = run_backtest(data, lookback_days=50)
    
    result.display()
    