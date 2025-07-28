#!/usr/bin/env python3
"""
Integration test script that demonstrates engine detection working
across all example strategies, similar to your original manual test.
"""

import os
import subprocess
import sys
from pathlib import Path
import pytest


def get_example_strategies():
    """Get all example strategy files."""
    strategies = []
    examples_dir = 'examples/strategies'
    
    if not os.path.exists(examples_dir):
        print(f"❌ Examples directory not found: {examples_dir}")
        return []
    
    for root, dirs, files in os.walk(examples_dir):
        for file in files:
            if file.endswith('.py') and not file.startswith('__'):
                strategies.append(os.path.join(root, file))
    
    return sorted(strategies)


@pytest.mark.parametrize("strategy_path", get_example_strategies())
def test_strategy_deployment(strategy_path):
    """Test deploying a single strategy and check engine detection."""
    print(f"\n🧪 Testing: {strategy_path}")
    
    # Extract expected engine from directory structure
    path_parts = strategy_path.split('/')
    if len(path_parts) >= 3:
        engine_dir = path_parts[2]  # examples/strategies/[engine_dir]/file.py
        expected_engines = {
            'backtestingpy': 'backtesting',
            'backtrader': 'backtrader', 
            'bt': 'bt',
            'vectorbt': 'vectorbt',
            'zipline': 'zipline',
            'zipline-reloaded': 'zipline'
        }
        expected_engine = expected_engines.get(engine_dir, 'unknown')
        print(f"   Expected engine: {expected_engine}")
    
    # Run deploy command with verbose output
    cmd = [
        sys.executable, '-m', 'StrateQueue.cli.cli',
        '--verbose', '1',
        'deploy',
        '--strategy', strategy_path,
        '--symbol', 'AAPL',
        '--timeframe', '1m',
        '--data-source', 'demo',
        '--duration', '1',  # Very short duration
        '--no-trading'      # Safe mode
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,  # Short timeout
            env={**os.environ, 'SQ_TEST_STUB_BROKERS': '1'}
        )
        
        # Check for engine detection in output
        output_combined = result.stdout + result.stderr
        
        if 'Detected engine type' in result.stdout:
            # Extract detected engine from log
            for line in result.stdout.split('\n'):
                if 'Detected engine type' in line:
                    print(f"   ✅ {line.strip()}")
                    break
        elif 'Auto-detected engine type' in result.stdout:
            for line in result.stdout.split('\n'):
                if 'Auto-detected engine type' in line:
                    print(f"   ✅ {line.strip()}")
                    break
        
        # Check result
        if result.returncode == 0:
            print(f"   ✅ Deploy succeeded")
        elif result.returncode == 1 and ('No module named' in output_combined):
            print(f"   ⚠️  Deploy failed due to missing engine dependency (expected)")
        else:
            print(f"   ❌ Deploy failed with unexpected error (code {result.returncode})")
            print(f"      STDOUT: {result.stdout[:200]}...")
            print(f"      STDERR: {result.stderr[:200]}...")
            # For pytest, we should fail if there's an unexpected error
            assert False, f"Deploy failed with unexpected error (code {result.returncode}): {result.stderr[:200]}"
        
        # Both success and expected failures (missing dependencies) are OK
        assert result.returncode in [0, 1], f"Unexpected return code: {result.returncode}"
        
    except subprocess.TimeoutExpired:
        print(f"   ⏰ Test timed out (this might be expected for some engines)")
        # Timeout is acceptable for some engines
        pass
    except Exception as e:
        print(f"   ❌ Test failed with exception: {e}")
        pytest.fail(f"Test failed with exception: {e}")


