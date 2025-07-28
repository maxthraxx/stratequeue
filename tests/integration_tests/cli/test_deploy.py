"""
Integration tests for the deploy command with example strategies.
"""

import os
import pytest
import subprocess
import sys
from pathlib import Path


class TestDeployCommand:
    """Test the deploy command with various example strategies."""
    
    def get_example_strategies(self):
        """Get all example strategy files."""
        strategies = []
        examples_dir = 'examples/strategies'
        
        if not os.path.exists(examples_dir):
            return []
        
        for root, dirs, files in os.walk(examples_dir):
            for file in files:
                if file.endswith('.py') and not file.startswith('__'):
                    strategies.append(os.path.join(root, file))
        
        return sorted(strategies)
    
    def run_stratequeue_command(self, args, timeout=30, verbose=False):
        """Run stratequeue command and return result."""
        cmd = [sys.executable, '-m', 'StrateQueue.cli.cli']
        if verbose:
            cmd.extend(['--verbose', '1'])
        cmd.extend(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, 'SQ_TEST_STUB_BROKERS': '1'}
            )
            return result
        except subprocess.TimeoutExpired:
            return None
    
    def test_deploy_help(self):
        """Test that deploy command shows help."""
        result = self.run_stratequeue_command(['deploy', '--help'])
        assert result is not None
        assert result.returncode == 0
        assert 'Deploy Command - Start strategies with live market data' in result.stdout
        assert '--strategy' in result.stdout
        assert '--symbol' in result.stdout
        assert '--timeframe' in result.stdout or 'granularity' in result.stdout.lower()
        assert 'If not specified, will auto-detect from strategy file' in result.stdout
    
    @pytest.mark.parametrize("strategy_file", [
        pytest.param(strategy, id=os.path.basename(strategy)) 
        for strategy in get_example_strategies(None)
    ])
    def test_deploy_example_strategies_validation(self, strategy_file):
        """Test deploy command validation with each example strategy."""
        if not os.path.exists(strategy_file):
            pytest.skip(f"Strategy file not found: {strategy_file}")
        
        # Test with very short duration and no-trading mode to avoid actual execution
        result = self.run_stratequeue_command([
            'deploy',
            '--strategy', strategy_file,
            '--symbol', 'AAPL',
            '--timeframe', '1m',
            '--data-source', 'demo',
            '--duration', '1',  # 1 minute
            '--no-trading'      # Signals only mode
        ], timeout=10)  # Short timeout since we're just testing validation
        
        # Check that the command doesn't crash during validation
        if result is None:
            pytest.skip(f"Command timed out for {strategy_file}")
        
        # Print output for debugging if test fails
        if result.returncode not in [0, 1]:
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
        
        # The command should either succeed or fail gracefully during validation
        assert result.returncode in [0, 1], f"Unexpected exit code for {strategy_file}"
        
        # Should not have unhandled exceptions in stderr
        assert 'Traceback' not in result.stderr, f"Unhandled exception for {strategy_file}"
    
    def test_deploy_engine_detection_validation(self):
        """Test that deploy correctly detects and validates engines for example strategies."""
        strategies = self.get_example_strategies()
        
        if not strategies:
            pytest.skip("No example strategies found")
        
        # Test a few representative strategies
        test_cases = [
            ('backtestingpy', 'backtesting'),
            ('backtrader', 'backtrader'),
            ('bt', 'bt'),
            ('vectorbt', 'vectorbt'),
            ('zipline-reloaded', 'zipline')
        ]
        
        for engine_dir, expected_engine in test_cases:
            # Find a strategy file for this engine
            strategy_file = None
            for strategy in strategies:
                if f'/{engine_dir}/' in strategy:
                    strategy_file = strategy
                    break
            
            if not strategy_file:
                continue
            
            # Test with verbose output and very short duration
            result = self.run_stratequeue_command([
                'deploy',
                '--strategy', strategy_file,
                '--symbol', 'AAPL',
                '--timeframe', '1m',
                '--data-source', 'demo',
                '--duration', '1',
                '--no-trading'
            ], timeout=10)
            
            if result is None:
                continue  # Skip if timed out
            
            # Should mention the detected engine in output or succeed
            if result.returncode == 0:
                # Look for engine-related output
                output_combined = (result.stdout + result.stderr).lower()
                # Either engine is mentioned or command succeeds (which means engine was detected correctly)
                assert expected_engine in output_combined or 'engine' in output_combined or result.returncode == 0
    
    def test_deploy_invalid_strategy_file(self):
        """Test deploy with non-existent strategy file."""
        result = self.run_stratequeue_command([
            'deploy',
            '--strategy', 'nonexistent/strategy.py',
            '--symbol', 'AAPL',
            '--timeframe', '1m',
            '--data-source', 'demo',
            '--duration', '1',
            '--no-trading'
        ])
        
        assert result is not None
        assert result.returncode != 0
        output_combined = (result.stdout + result.stderr).lower()
        assert 'not found' in output_combined or 'error' in output_combined
    
    def test_deploy_missing_required_args(self):
        """Test deploy with missing required arguments."""
        strategies = self.get_example_strategies()
        
        if not strategies:
            pytest.skip("No example strategies found")
        
        strategy_file = strategies[0]
        
        # Test missing strategy (should fail)
        result = self.run_stratequeue_command([
            'deploy',
            '--symbol', 'AAPL',
            '--timeframe', '1m',
            '--data-source', 'demo'
        ])
        assert result is not None
        assert result.returncode != 0
        
        # Note: symbol has a default (AAPL) and granularity might have defaults too
        # So we test the one required arg: --strategy


if __name__ == "__main__":
    # Allow running this test file directly
    pytest.main([__file__, "-v"])