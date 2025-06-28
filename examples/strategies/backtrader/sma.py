"""
Simple Moving Average Crossover Strategy for Backtrader

This strategy generates BUY signals when the fast SMA crosses above the slow SMA,
and SELL signals when the fast SMA crosses below the slow SMA.
"""

import backtrader as bt


class SMAStrategy(bt.Strategy):
    """Simple Moving Average Crossover Strategy"""
    
    params = (
        ('fast_period', 1),   # fast SMA (1 bar)
        ('slow_period', 3),   # slow SMA (3 bars)
    )
    
    def __init__(self):
        # Create the moving averages
        self.fast_sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.fast_period
        )
        self.slow_sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.slow_period
        )
        
        # Create crossover signal
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
    
    def next(self):
        # Fast SMA crosses above slow SMA → enter long if not already in position
        if self.crossover > 0 and not self.position:
            self.buy()

        # Fast SMA crosses below slow SMA → close long position if it exists
        elif self.crossover < 0 and self.position:
            self.close()


# Example usage with Backtrader directly (for testing)
if __name__ == "__main__":
    import datetime
    
    print("Testing SMACrossover Strategy...")
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SMAStrategy)
    
    # Add some dummy data for testing
    # In real usage, this would be replaced with actual crypto data
    data = bt.feeds.YahooFinanceData(
        dataname='BTC-USD',
        fromdate=datetime.datetime(2023, 1, 1),
        todate=datetime.datetime(2023, 12, 31)
    )
    cerebro.adddata(data)
    
    # Set initial cash and commission
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.001)  # 0.1% commission
    
    print(f'Starting Portfolio Value: ${cerebro.broker.getvalue():.2f}')
    cerebro.run()
    print(f'Final Portfolio Value: ${cerebro.broker.getvalue():.2f}') 