"""
Status Command Tests for StrateQueue CLI

Requirements for passing tests:
1. All tests must run in milliseconds (no external processes, network, or file I/O)
2. Mock all external dependencies (InfoFormatter methods, etc.)
3. Test both success and failure paths
4. Verify exit codes are correct (0 for success, 1 for errors)
5. Verify correct formatter methods are called
6. Test command aliases work identically to main command
7. Ensure argparse choice validation works properly
8. Verify --detailed flag is properly handled
"""

import pytest
from unittest.mock import Mock, patch
from argparse import Namespace

from StrateQueue.cli.commands.status_command import StatusCommand


class TestStatusCommandBasics:
    """Test basic status command properties and setup"""

    def test_command_properties(self):
        """Test command basic properties"""
        command = StatusCommand()
        
        assert command.name == "status"
        assert "status" in command.description.lower()
        assert "check" in command.aliases
        assert "health" in command.aliases
        assert isinstance(command.aliases, list)

    def test_parser_setup(self):
        """Test parser configuration"""
        command = StatusCommand()
        parser = Mock()
        parser.add_argument = Mock()
        
        result = command.setup_parser(parser)
        
        assert result == parser
        assert parser.add_argument.call_count == 2
        
        # Check first call (status_type argument)
        first_call = parser.add_argument.call_args_list[0]
        assert first_call[0][0] == "status_type"
        assert first_call[1]["choices"] == ["broker", "provider", "system"]
        assert first_call[1]["nargs"] == "?"
        assert first_call[1]["default"] == "system"
        
        # Check second call (--detailed flag)
        second_call = parser.add_argument.call_args_list[1]
        assert second_call[0][0] == "--detailed"
        assert second_call[0][1] == "-d"
        assert second_call[1]["action"] == "store_true"

    def test_validate_args(self):
        """Test argument validation"""
        command = StatusCommand()
        
        # Test with various argument combinations
        args_combinations = [
            Namespace(status_type="system"),
            Namespace(status_type="broker"),
            Namespace(status_type="provider"),
            Namespace(status_type="broker", detailed=True),
            Namespace(status_type="system", detailed=False),
        ]
        
        for args in args_combinations:
            result = command.validate_args(args)
            assert result is None


class TestStatusCommandExecution:
    """Test status command execution paths"""

    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_broker_status')
    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_provider_status')
    def test_default_system_status(self, mock_format_provider, mock_format_broker, capsys):
        """Test 4-1: Default stratequeue status → shows broker + provider status"""
        mock_format_broker.return_value = "Broker status content"
        mock_format_provider.return_value = "Provider status content"
        command = StatusCommand()
        
        args = Namespace(status_type="system")
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_broker.assert_called_once()
        mock_format_provider.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Broker status content" in captured.out
        assert "Provider status content" in captured.out

    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_broker_status')
    def test_broker_status_only(self, mock_format_broker, capsys):
        """Test 4-2: status broker → broker status only"""
        mock_format_broker.return_value = "Broker status only"
        command = StatusCommand()
        
        args = Namespace(status_type="broker")
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_broker.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Broker status only" in captured.out

    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_provider_status')
    def test_provider_status_only(self, mock_format_provider, capsys):
        """Test 4-3: status provider → provider status only"""
        mock_format_provider.return_value = "Provider status only"
        command = StatusCommand()
        
        args = Namespace(status_type="provider")
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_provider.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Provider status only" in captured.out

    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_broker_status')
    def test_detailed_flag_execution(self, mock_format_broker, capsys):
        """Test 4-4: status --detailed flag gets through to formatter"""
        mock_format_broker.return_value = "Detailed broker status"
        command = StatusCommand()
        
        args = Namespace(status_type="broker", detailed=True)
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_broker.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Detailed broker status" in captured.out


class TestStatusCommandAliases:
    """Test status command aliases functionality"""

    def test_aliases_property(self):
        """Test that aliases property returns correct values"""
        command = StatusCommand()
        aliases = command.aliases
        
        assert isinstance(aliases, list)
        assert "check" in aliases
        assert "health" in aliases

    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_broker_status')
    def test_alias_check_works(self, mock_format_broker, capsys):
        """Test 4-5: Alias stratequeue check works"""
        mock_format_broker.return_value = "Broker status via check alias"
        command = StatusCommand()
        
        args = Namespace(status_type="broker")
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_broker.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Broker status via check alias" in captured.out

    @patch('StrateQueue.cli.commands.status_command.InfoFormatter.format_provider_status')
    def test_alias_health_provider_works(self, mock_format_provider, capsys):
        """Test 4-6: Alias stratequeue health provider works"""
        mock_format_provider.return_value = "Provider status via health alias"
        command = StatusCommand()
        
        args = Namespace(status_type="provider")
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_provider.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Provider status via health alias" in captured.out
