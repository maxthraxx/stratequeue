import bt
import pandas as pd
import numpy as np


class WeighTarget(bt.Algo):
    def __init__(self, target_weights):
        self.tw = target_weights
    
    def __call__(self, target):
        if target.now in self.tw.index:
            w = self.tw.loc[target.now]
            target.temp['weights'] = w.dropna()
        return True


def create_mean_reversion_strategy(data, lookback_period=20, entry_threshold=1.5, exit_threshold=0.5):
    rolling_mean = data.rolling(lookback_period).mean()
    rolling_std = data.rolling(lookback_period).std()
    z_score = (data - rolling_mean) / rolling_std
    
    tw = data.copy()
    tw[:] = 0.0
    
    tw[z_score <= -entry_threshold] = 1.0
    tw[z_score >= entry_threshold] = -1.0
    
    for col in tw.columns:
        for i in range(1, len(tw)):
            current_z = z_score.iloc[i][col]
            prev_weight = tw.iloc[i-1][col]
            
            if abs(current_z) <= exit_threshold:
                tw.loc[tw.index[i], col] = 0.0
            elif abs(current_z) < entry_threshold and prev_weight != 0:
                tw.loc[tw.index[i], col] = prev_weight
    
    tw[rolling_mean.isnull()] = 0.0
    tw[rolling_std.isnull()] = 0.0
    
    strategy = bt.Strategy(
        'MeanReversion',
        [WeighTarget(tw), bt.algos.Rebalance()]
    )
    
    return strategy


def main():
    data = pd.read_csv('examples/data/AAPL.csv')
    data['Date'] = pd.to_datetime(data['Date'])
    data.set_index('Date', inplace=True)
    data.sort_index(inplace=True)
    
    for col in ['Open', 'High', 'Low', 'Close']:
        if data[col].dtype == 'object':
            data[col] = data[col].astype(str).str.replace(',', '').astype(float)
    
    close_prices = data[['Close']].copy()
    
    strategy = create_mean_reversion_strategy(close_prices)
    backtest = bt.Backtest(strategy, close_prices)
    results = bt.run(backtest)
    results.display()


if __name__ == "__main__":
    main()