"""
Unit tests for backtesting.py strategy detection in engine helpers
"""

import pytest
from unittest.mock import patch, mock_open
from src.StrateQueue.engines.engine_helpers import (
    analyze_strategy_file,
    detect_engine_from_analysis,
    _detect_engine_from_imports
)


class TestBacktestingDetection:
    """Test backtesting.py strategy detection patterns"""
    
    def test_detect_basic_backtesting_strategy(self):
        """Test detection of basic backtesting.py import"""
        content = """
from backtesting import Strategy, Backtest

class MyStrategy(Strategy):
    def init(self):
        pass
    
    def next(self):
        self.buy()
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_detect_complete_backtesting_strategy(self):
        """Test detection of complete backtesting.py strategy"""
        content = """
from backtesting import Strategy, Backtest
from backtesting.lib import crossover

class MyStrategy(Strategy):
    def init(self):
        pass
    
    def next(self):
        if crossover(self.data.Close, self.data.Close.rolling(20).mean()):
            self.buy()
        elif crossover(self.data.Close.rolling(20).mean(), self.data.Close):
            self.sell()
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_detect_aliased_import(self):
        """Test detection with aliased import"""
        content = """
import backtesting as bt

class MyStrategy(bt.Strategy):
    pass
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_detect_strategy_alias(self):
        """Test detection with Strategy alias"""
        content = """
from backtesting import Strategy as BaseStrategy

class MyStrategy(BaseStrategy):
    pass
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_no_false_positives_backtrader(self):
        """Test that backtrader strategies don't trigger backtesting.py detection"""
        content = """
import backtrader as bt

class SMAStrategy(bt.Strategy):
    def next(self):
        self.buy()
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtrader'
    
    def test_no_false_positives_bt(self):
        """Test that bt library strategies don't trigger backtesting.py detection"""
        content = """
import bt

def my_strategy():
    return bt.Strategy('equal_weight', algos)
"""
        result = _detect_engine_from_imports(content)
        assert result == 'bt'
    
    def test_no_false_positives_empty_file(self):
        """Test that empty files don't trigger detection"""
        result = _detect_engine_from_imports("")
        assert result == 'unknown'
    
    def test_no_false_positives_non_strategy(self):
        """Test that non-strategy files don't trigger detection"""
        content = """
import pandas as pd
import numpy as np

def analyze_data(data):
    return data > data.mean()
"""
        result = _detect_engine_from_imports(content)
        assert result == 'unknown'
    
    def test_syntax_error_handling(self):
        """Test that syntax errors are handled gracefully"""
        invalid_content = """
from backtesting import Strategy
class MyStrategy(Strategy
    pass
"""
        result = _detect_engine_from_imports(invalid_content)
        assert result == 'unknown'
    
    def test_imports_only_detection(self):
        """Test that just imports are sufficient for detection"""
        content = """
from backtesting.lib import crossover
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_multiple_strategy_classes(self):
        """Test detection with multiple strategy classes"""
        content = """
from backtesting import Strategy, Backtest

class Strategy1(Strategy):
    def next(self):
        self.buy()

class Strategy2(Strategy):
    def next(self):
        self.sell()
"""
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_detect_engine_from_analysis_backtesting(self):
        """Test that backtesting is correctly identified through full analysis"""
        backtesting_strategy_content = """
from backtesting import Strategy, Backtest

class MyStrategy(Strategy):
    def init(self):
        pass
    
    def next(self):
        self.buy()
"""
        
        with patch('builtins.open', mock_open(read_data=backtesting_strategy_content)):
            with patch('os.path.exists', return_value=True):
                analysis = analyze_strategy_file('test_backtesting_strategy.py')
                detected_engine = detect_engine_from_analysis(analysis)
        
        assert detected_engine == 'backtesting'