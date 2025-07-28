"""
Test engine detection logic for strategy files.
"""

import os
import pytest
from StrateQueue.engines.engine_helpers import _detect_engine_from_imports, analyze_strategy_file


class TestEngineDetection:
    """Test the engine detection functionality."""
    
    def test_detect_engine_from_imports_direct(self):
        """Test engine detection from import statements directly."""
        test_cases = [
            # Backtesting.py
            ("from backtesting import Backtest, Strategy", "backtesting"),
            ("import backtesting", "backtesting"),
            
            # Backtrader
            ("import backtrader as bt", "backtrader"),
            ("from backtrader import Strategy", "backtrader"),
            
            # BT library
            ("import bt", "bt"),
            ("from bt import Backtest", "bt"),
            
            # VectorBT
            ("import vectorbt as vbt", "vectorbt"),
            ("from vectorbt import Portfolio", "vectorbt"),
            ("import vectorbtpro", "vectorbt"),
            
            # Zipline
            ("from zipline.api import order_target_percent", "zipline"),
            ("import zipline", "zipline"),
            
            # Unknown/no engine imports
            ("import pandas as pd", "unknown"),
            ("from datetime import datetime", "unknown"),
        ]
        
        for import_code, expected_engine in test_cases:
            detected = _detect_engine_from_imports(import_code)
            assert detected == expected_engine, f"Failed for: {import_code}"
    
    def test_detect_engine_from_strategy_files(self):
        """Test engine detection from actual strategy files in examples."""
        # Expected mappings based on directory structure
        expected_engines = {
            'backtestingpy': 'backtesting',
            'backtrader': 'backtrader', 
            'bt': 'bt',
            'vectorbt': 'vectorbt',
            'zipline': 'zipline',
            'zipline-reloaded': 'zipline'
        }
        
        examples_dir = 'examples/strategies'
        if not os.path.exists(examples_dir):
            pytest.skip("Examples directory not found")
        
        strategy_files = []
        for root, dirs, files in os.walk(examples_dir):
            for file in files:
                if file.endswith('.py') and not file.startswith('__'):
                    strategy_files.append(os.path.join(root, file))
        
        assert len(strategy_files) > 0, "No strategy files found for testing"
        
        for file_path in strategy_files:
            # Extract expected engine from directory structure
            path_parts = file_path.split('/')
            if len(path_parts) >= 3:
                engine_dir = path_parts[2]  # examples/strategies/[engine_dir]/file.py
                expected_engine = expected_engines.get(engine_dir, 'unknown')
                
                # Analyze the file
                analysis = analyze_strategy_file(file_path)
                detected_engine = analysis['detected_engine']
                
                assert detected_engine == expected_engine, (
                    f"Engine detection failed for {file_path}\n"
                    f"Expected: {expected_engine}, Detected: {detected_engine}"
                )
    
    def test_detect_engine_with_multiple_imports(self):
        """Test that detection works with multiple import statements."""
        code_with_multiple_imports = """
import pandas as pd
import numpy as np
from backtesting import Backtest, Strategy
import matplotlib.pyplot as plt
"""
        detected = _detect_engine_from_imports(code_with_multiple_imports)
        assert detected == "backtesting"
    
    def test_detect_engine_with_syntax_error(self):
        """Test that syntax errors are handled gracefully."""
        invalid_code = "import backtesting\nthis is not valid python syntax"
        detected = _detect_engine_from_imports(invalid_code)
        assert detected == "unknown"
    
    def test_detect_engine_priority_order(self):
        """Test that when multiple engines are imported, the first one found wins."""
        # This tests the current behavior - first import found wins
        code_with_multiple_engines = """
import bt
import backtrader
from backtesting import Strategy
"""
        detected = _detect_engine_from_imports(code_with_multiple_engines)
        # Should detect 'bt' since it appears first in the AST walk
        assert detected == "bt"


if __name__ == "__main__":
    # Allow running this test file directly
    pytest.main([__file__, "-v"])