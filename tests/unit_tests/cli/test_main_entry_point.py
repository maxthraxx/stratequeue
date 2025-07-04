"""
Main Entry Point Tests for StrateQueue CLI

Tests the main CLI entry point (cli.py) covering:
- No arguments (welcome message)
- Version flag
- Help flag  
- Unknown commands
- Global verbose flag propagation

Requirements for passing tests:
1. All tests must run in milliseconds (no external processes, network, or file I/O)
2. Mock all external dependencies (subprocess, logging setup, etc.)
3. Test both success and failure paths
4. Verify exit codes are correct (0 for success, 1+ for errors)
5. Verify output contains expected content
6. Test all command aliases and argument combinations
7. Ensure global flags are properly propagated
"""

import pytest
from unittest.mock import Mock, patch
import sys
from io import StringIO

from StrateQueue.cli.cli import main, create_main_parser, show_welcome_message


class TestMainEntryPoint:
    """Test cases for the main CLI entry point"""

    def test_no_args_shows_welcome_message(self, capsys):
        """
        Test 0-1: `stratequeue` with no args → returns 0, prints welcome banner
        
        Requirements:
        - Exit code 0
        - Welcome message printed to stdout
        - Contains supported commands
        """
        exit_code = main([])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        assert "StrateQueue" in captured.out
        assert "Available commands:" in captured.out or "Commands:" in captured.out
        
    def test_version_flag(self, capsys):
        """
        Test 0-2: `stratequeue --version` → returns 0, prints version string
        
        Requirements:
        - Exit code 0 (via SystemExit)
        - Version string contains program name and version
        """
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        
        assert exc_info.value.code == 0
        
        captured = capsys.readouterr()
        assert "stratequeue" in captured.out.lower()
        assert "0.0.1" in captured.out
        
    def test_help_flag(self, capsys):
        """
        Test 0-3: `stratequeue --help` → returns 0, contains every primary command in help/epilog
        
        Requirements:
        - Exit code 0 (via SystemExit)
        - Help text contains all primary commands
        - Help text contains program description
        """
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        
        assert exc_info.value.code == 0
        
        captured = capsys.readouterr()
        help_text = captured.out
        
        # Check for primary commands
        expected_commands = ["daemon", "deploy", "list", "status", "setup", "webui"]
        for command in expected_commands:
            assert command in help_text.lower()
        
        # Check for program description
        assert "stratequeue" in help_text.lower()
        
    def test_unknown_command_returns_error(self, capsys):
        """
        Test 0-4: Unknown command → exit-code 2 (argparse standard for invalid choice)
        
        Requirements:
        - Exit code 2 (argparse standard for invalid arguments)
        - Error message mentions invalid choice
        - Shows available commands in error message
        """
        with pytest.raises(SystemExit) as exc_info:
            main(["frobnicate"])
        
        assert exc_info.value.code == 2
        
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err or "frobnicate" in captured.err
        
    @patch('StrateQueue.cli.cli.setup_logging')
    def test_verbose_flag_propagation(self, mock_setup_logging, capsys):
        """
        Test 0-5: Global `--verbose` flag is propagated
        
        Requirements:
        - setup_logging called with verbose=True when --verbose flag used
        - Works with any command combination
        """
        # Test with no command (should still call setup_logging)
        exit_code = main(["--verbose"])
        
        assert exit_code == 0
        mock_setup_logging.assert_called_once_with(True)
        
        # Reset mock and test with a valid command
        mock_setup_logging.reset_mock()
        
        # Test with a valid command to avoid argparse errors
        with patch('StrateQueue.cli.cli.create_command') as mock_create:
            mock_command = Mock()
            mock_command.run.return_value = 0
            mock_create.return_value = mock_command
            
            exit_code = main(["--verbose", "list"])
            
            assert exit_code == 0
            mock_setup_logging.assert_called_once_with(True)
        
    @patch('StrateQueue.cli.cli.create_main_parser')
    def test_keyboard_interrupt_handling(self, mock_create_parser, capsys):
        """
        Test keyboard interrupt handling returns proper exit code
        
        Requirements:
        - KeyboardInterrupt returns exit code 130
        - Prints cancellation message
        """
        # Mock parser to avoid argparse issues
        mock_parser = Mock()
        mock_args = Mock()
        mock_args.verbose = False
        mock_args.command = 'deploy'
        mock_parser.parse_args.return_value = mock_args
        mock_create_parser.return_value = mock_parser
        
        with patch('StrateQueue.cli.cli.create_command') as mock_create:
            mock_command = Mock()
            mock_command.run.side_effect = KeyboardInterrupt()
            mock_create.return_value = mock_command
            
            exit_code = main(["deploy", "--strategy", "test.py"])
            
            assert exit_code == 130
            
            captured = capsys.readouterr()
            assert "cancelled" in captured.out.lower() or "interrupted" in captured.out.lower()
            
    @patch('StrateQueue.cli.cli.create_main_parser')
    def test_unexpected_error_handling(self, mock_create_parser, capsys):
        """
        Test unexpected error handling
        
        Requirements:
        - Unexpected exceptions return exit code 1
        - Error message printed
        - Suggests verbose mode
        """
        # Mock parser to avoid argparse issues
        mock_parser = Mock()
        mock_args = Mock()
        mock_args.verbose = False
        mock_args.command = 'deploy'
        mock_parser.parse_args.return_value = mock_args
        mock_create_parser.return_value = mock_parser
        
        with patch('StrateQueue.cli.cli.create_command') as mock_create:
            mock_command = Mock()
            mock_command.run.side_effect = RuntimeError("Test error")
            mock_create.return_value = mock_command
            
            exit_code = main(["deploy", "--strategy", "test.py"])
            
            assert exit_code == 1
            
            captured = capsys.readouterr()
            assert "error" in captured.out.lower()
            assert "verbose" in captured.out.lower()


class TestMainParserCreation:
    """Test the main argument parser creation"""
    
    def test_create_main_parser_structure(self):
        """
        Test that the main parser is created with correct structure
        
        Requirements:
        - Parser has correct program name
        - Global arguments are present
        - Subparsers are configured
        """
        parser = create_main_parser()
        
        assert parser.prog == 'stratequeue'
        
        # Check that we can parse global arguments without triggering version exit
        args = parser.parse_args(['--verbose'])
        assert args.verbose is True
        
    def test_global_arguments_present(self):
        """
        Test that global arguments are properly configured
        
        Requirements:
        - --verbose flag available
        - --version flag available  
        - Help is available
        """
        parser = create_main_parser()
        
        # Test verbose flag
        args = parser.parse_args(['--verbose'])
        assert args.verbose is True
        
        # Test short verbose flag
        args = parser.parse_args(['-v'])
        assert args.verbose is True
        
        # Test default verbose
        args = parser.parse_args([])
        assert args.verbose is False


class TestWelcomeMessage:
    """Test the welcome message functionality"""
    
    @patch('StrateQueue.cli.cli.get_supported_commands')
    def test_show_welcome_message(self, mock_get_commands, capsys):
        """
        Test welcome message display
        
        Requirements:
        - Shows formatted welcome message
        - Includes supported commands
        - Calls get_supported_commands
        """
        mock_get_commands.return_value = {
            'daemon': 'Run the daemon server',
            'deploy': 'Deploy strategies',
            'list': 'List resources'
        }
        
        show_welcome_message()
        
        captured = capsys.readouterr()
        assert len(captured.out) > 0
        mock_get_commands.assert_called_once()


class TestMainWithMockedCommands:
    """Test main function with mocked command execution"""
    
    @patch('StrateQueue.cli.cli.create_main_parser')
    @patch('StrateQueue.cli.cli.create_command')
    @patch('StrateQueue.cli.cli.setup_logging')
    def test_successful_command_execution(self, mock_setup_logging, mock_create_command, mock_create_parser):
        """
        Test successful command execution flow
        
        Requirements:
        - Command is created and executed
        - Returns command's exit code
        - Logging is setup
        """
        # Mock parser to avoid argparse issues
        mock_parser = Mock()
        mock_args = Mock()
        mock_args.verbose = False
        mock_args.command = 'list'
        mock_parser.parse_args.return_value = mock_args
        mock_create_parser.return_value = mock_parser
        
        mock_command = Mock()
        mock_command.run.return_value = 0
        mock_create_command.return_value = mock_command
        
        exit_code = main(["list", "brokers"])
        
        assert exit_code == 0
        mock_create_command.assert_called_once_with("list")
        mock_command.run.assert_called_once()
        mock_setup_logging.assert_called_once_with(False)  # verbose=False by default
        
    @patch('StrateQueue.cli.cli.create_main_parser')
    @patch('StrateQueue.cli.cli.create_command')
    @patch('StrateQueue.cli.cli.setup_logging')
    def test_command_failure_propagation(self, mock_setup_logging, mock_create_command, mock_create_parser):
        """
        Test that command failures are properly propagated
        
        Requirements:
        - Command's exit code is returned
        - Non-zero exit codes are preserved
        """
        # Mock parser to avoid argparse issues
        mock_parser = Mock()
        mock_args = Mock()
        mock_args.verbose = False
        mock_args.command = 'deploy'
        mock_parser.parse_args.return_value = mock_args
        mock_create_parser.return_value = mock_parser
        
        mock_command = Mock()
        mock_command.run.return_value = 42  # Custom exit code
        mock_create_command.return_value = mock_command
        
        exit_code = main(["deploy", "--strategy", "test.py"])
        
        assert exit_code == 42
        mock_create_command.assert_called_once_with("deploy")
        mock_command.run.assert_called_once()
        
    @patch('StrateQueue.cli.cli.create_main_parser')
    @patch('StrateQueue.cli.cli.create_command')
    @patch('StrateQueue.cli.cli.get_supported_commands')
    def test_command_not_found(self, mock_get_commands, mock_create_command, mock_create_parser, capsys):
        """
        Test handling when command cannot be created (command exists but factory fails)
        
        Requirements:
        - Returns exit code 1
        - Shows error message
        - Lists available commands
        """
        # Mock parser to avoid argparse issues
        mock_parser = Mock()
        mock_args = Mock()
        mock_args.verbose = False
        mock_args.command = 'list'
        mock_parser.parse_args.return_value = mock_args
        mock_create_parser.return_value = mock_parser
        
        # Mock the command to exist in supported commands but fail creation
        mock_get_commands.return_value = {'list': 'List things', 'status': 'Show status'}
        mock_create_command.return_value = None
        
        exit_code = main(["list"])
        
        assert exit_code == 1
        mock_create_command.assert_called_once_with("list")
        
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out or "unknown command" in captured.out
        assert "list" in captured.out 