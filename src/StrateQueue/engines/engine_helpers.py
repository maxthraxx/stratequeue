"""
Engine Detection Utilities

Simple import-based engine detection for trading strategies.
"""

import os
import ast
from typing import Dict
import logging

logger = logging.getLogger(__name__)


def _detect_engine_from_imports(content: str) -> str:
    """
    Detect engine by checking what's actually imported
    
    Returns:
        Engine name or 'unknown'
    """
    try:
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'bt':
                        return 'bt'
                    elif alias.name == 'backtrader':
                        return 'backtrader'
                    elif alias.name == 'backtesting':
                        return 'backtesting'
                    elif alias.name == 'zipline':
                        return 'zipline'
                    elif alias.name in ['vectorbt', 'vectorbtpro']:
                        return 'vectorbt'
            
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    if node.module == 'bt' or node.module.startswith('bt.'):
                        return 'bt'
                    elif node.module == 'backtrader' or node.module.startswith('backtrader.'):
                        return 'backtrader'
                    elif node.module == 'backtesting' or node.module.startswith('backtesting.'):
                        return 'backtesting'
                    elif node.module == 'zipline' or node.module.startswith('zipline.'):
                        return 'zipline'
                    elif node.module in ['vectorbt', 'vectorbtpro'] or node.module.startswith(('vectorbt.', 'vectorbtpro.')):
                        return 'vectorbt'
        
        return 'unknown'
        
    except SyntaxError:
        return 'unknown'


def analyze_strategy_file(strategy_path: str) -> Dict[str, any]:
    """
    Analyze a strategy file to determine its engine compatibility
    
    Args:
        strategy_path: Path to the strategy file
        
    Returns:
        Dictionary with analysis results containing detected engine
    """
    if not os.path.exists(strategy_path):
        raise FileNotFoundError(f"Strategy file not found: {strategy_path}")
    
    try:
        with open(strategy_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Error reading strategy file {strategy_path}: {e}")
        raise
    
    # Simple import-based engine detection
    detected_engine = _detect_engine_from_imports(content)
    
    analysis = {
        'file_path': strategy_path,
        'detected_engine': detected_engine
    }
    
    return analysis


def detect_engine_from_analysis(analysis: Dict[str, any]) -> str:
    """
    Determine engine based on file analysis
    
    Args:
        analysis: Result from analyze_strategy_file()
        
    Returns:
        Engine name ('backtesting', 'backtrader', 'zipline', 'vectorbt', 'bt', 'unknown')
    """
    return analysis['detected_engine']


def validate_strategy_file_for_engine(strategy_path: str, expected_engine: str) -> bool:
    """
    Return True iff the strategy located at `strategy_path` most likely targets
    the engine named in `expected_engine`.

    This consolidates the heuristics so each TradingEngine implementation
    doesn't have to copy-paste its own validation code.
    
    Args:
        strategy_path: Path to the strategy file
        expected_engine: Expected engine name ('backtesting', 'zipline', etc.)
        
    Returns:
        True if the file is compatible with the expected engine
    """
    try:
        analysis = analyze_strategy_file(strategy_path)
        detected_engine = detect_engine_from_analysis(analysis)
        return detected_engine == expected_engine
    except Exception as e:
        logger.warning(f"Engine validation failed for {strategy_path}: {e}")
        return False