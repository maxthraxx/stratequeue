import bt
import pandas as pd


def create_buy_and_hold_strategy():
    """
    Create a simple buy and hold strategy that:
    1. Runs once at the beginning
    2. Selects all available securities
    3. Weights them equally
    4. Rebalances once
    """
    strategy = bt.Strategy(
        'BuyAndHold',
        [
            bt.algos.RunOnce(),
            bt.algos.SelectAll(),
            bt.algos.WeighEqually(),
            bt.algos.Rebalance()
        ]
    )
    
    return strategy


def main():
    # Load data
    data = pd.read_csv('examples/data/AAPL.csv')
    data['Date'] = pd.to_datetime(data['Date'])
    data.set_index('Date', inplace=True)
    data.sort_index(inplace=True)
    
    # Clean numeric columns if needed
    for col in ['Open', 'High', 'Low', 'Close']:
        if data[col].dtype == 'object':
            data[col] = data[col].astype(str).str.replace(',', '').astype(float)
    
    # Use close prices for the backtest
    close_prices = data[['Close']].copy()
    
    # Create strategy
    strategy = create_buy_and_hold_strategy()
    
    # Create and run backtest
    backtest = bt.Backtest(strategy, close_prices)
    results = bt.run(backtest)
    
    # Display results
    results.display()


if __name__ == "__main__":
    main()