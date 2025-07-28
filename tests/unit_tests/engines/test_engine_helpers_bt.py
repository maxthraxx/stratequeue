"""
Unit tests for bt strategy detection in engine helpers
"""

import pytest
from unittest.mock import patch, mock_open
from src.StrateQueue.engines.engine_helpers import (
    analyze_strategy_file,
    detect_engine_from_analysis,
    _detect_engine_from_imports
)


class TestBtStrategyDetection:
    """Test bt strategy detection patterns"""
    
    def test_detect_bt_import_basic(self):
        """Test detection of basic bt import"""
        content = "import bt"
        result = _detect_engine_from_imports(content)
        assert result == 'bt'
    
    def test_detect_bt_import_from(self):
        """Test detection of from bt import"""
        content = "from bt import algos"
        result = _detect_engine_from_imports(content)
        assert result == 'bt'
    
    def test_detect_bt_import_submodule(self):
        """Test detection of bt submodule import"""
        content = "from bt.algos import SelectAll"
        result = _detect_engine_from_imports(content)
        assert result == 'bt'
    
    def test_detect_backtrader_not_bt(self):
        """Test that backtrader import is not detected as bt"""
        content = "import backtrader as bt"
        result = _detect_engine_from_imports(content)
        assert result == 'backtrader'
    
    def test_detect_backtesting_not_bt(self):
        """Test that backtesting import is not detected as bt"""
        content = "from backtesting import Strategy"
        result = _detect_engine_from_imports(content)
        assert result == 'backtesting'
    
    def test_detect_unknown_for_no_imports(self):
        """Test that unknown is returned when no trading engine imports found"""
        content = "import pandas as pd\nimport numpy as np"
        result = _detect_engine_from_imports(content)
        assert result == 'unknown'
    
    def test_detect_first_import_wins(self):
        """Test that first trading engine import is detected"""
        content = """
import bt
import backtrader
"""
        result = _detect_engine_from_imports(content)
        assert result == 'bt'  # bt comes first
    
    def test_detect_engine_from_analysis_bt(self):
        """Test that bt is correctly identified as the primary engine"""
        bt_strategy_content = """
import bt

def my_strategy():
    return bt.Strategy('test', [])
"""
        
        with patch('builtins.open', mock_open(read_data=bt_strategy_content)):
            with patch('os.path.exists', return_value=True):
                analysis = analyze_strategy_file('test_bt_strategy.py')
                detected_engine = detect_engine_from_analysis(analysis)
        
        assert detected_engine == 'bt'
    
    def test_syntax_error_returns_unknown(self):
        """Test that syntax errors return unknown"""
        content = "import bt\nthis is not valid python"
        result = _detect_engine_from_imports(content)
        assert result == 'unknown'