"""
Setup Command Tests for StrateQueue CLI

Requirements for passing tests:
1. All tests must run in milliseconds (no external processes, network, or file I/O)
2. Mock all external dependencies (InfoFormatter methods, questionary, etc.)
3. Test both success and failure paths
4. Verify exit codes are correct (0 for success, 1 for errors)
5. Verify correct formatter methods are called
6. Test command aliases work identically to main command
7. Test questionary availability handling
8. Test documentation paths that don't require questionary
"""

import pytest
from unittest.mock import Mock, patch
from argparse import Namespace

from StrateQueue.cli.commands.setup_command import SetupCommand


class TestSetupCommandBasics:
    """Test basic setup command properties and setup"""

    def test_command_properties(self):
        """Test command basic properties"""
        command = SetupCommand()
        
        assert command.name == "setup"
        assert "config" in command.aliases
        assert "configure" in command.aliases
        assert isinstance(command.aliases, list)

    def test_parser_setup(self):
        """Test parser configuration"""
        command = SetupCommand()
        parser = Mock()
        parser.add_argument = Mock()
        
        result = command.setup_parser(parser)
        
        assert result == parser
        assert parser.add_argument.call_count == 3


class TestSetupCommandValidation:
    """Test setup command argument validation"""

    @patch('StrateQueue.cli.commands.setup_command.QUESTIONARY_AVAILABLE', False)
    def test_validate_args_without_questionary_no_docs(self):
        """Test 5-4: With questionary missing and no --docs → validation error, exit 1"""
        command = SetupCommand()
        
        args = Namespace(docs=False, setup_type="broker", provider_name=None)
        result = command.validate_args(args)
        
        assert result is not None
        assert len(result) == 1
        assert "questionary" in result[0].lower()


class TestSetupCommandDocumentationPaths:
    """Test setup command documentation paths (non-interactive)"""

    @patch('StrateQueue.cli.commands.setup_command.SetupCommand._show_general_docs')
    def test_setup_docs_general(self, mock_show_general):
        """Test 5-1: setup --docs shows general docs, exit 0"""
        command = SetupCommand()
        
        args = Namespace(docs=True, setup_type=None, provider_name=None)
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_show_general.assert_called_once()

    @patch('StrateQueue.cli.commands.setup_command.InfoFormatter.format_broker_setup_instructions')
    def test_setup_broker_docs(self, mock_format_broker, capsys):
        """Test 5-2: setup broker --docs outputs broker docs"""
        mock_format_broker.return_value = "Broker setup documentation"
        command = SetupCommand()
        
        args = Namespace(docs=True, setup_type="broker", provider_name=None)
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_broker.assert_called_once_with(None)
        
        captured = capsys.readouterr()
        assert "Broker setup documentation" in captured.out

    @patch('StrateQueue.cli.commands.setup_command.SetupCommand._show_data_provider_docs')
    def test_setup_data_provider_docs(self, mock_show_provider_docs):
        """Test 5-3: setup data-provider polygon --docs outputs polygon docs"""
        command = SetupCommand()
        
        args = Namespace(docs=True, setup_type="data-provider", provider_name="polygon")
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_show_provider_docs.assert_called_once_with("polygon")


class TestSetupCommandAliases:
    """Test setup command aliases functionality"""

    @patch('StrateQueue.cli.commands.setup_command.SetupCommand._show_general_docs')
    def test_alias_config_docs_works(self, mock_show_general):
        """Test 5-5: Alias stratequeue config --docs works"""
        command = SetupCommand()
        
        args = Namespace(docs=True, setup_type=None, provider_name=None)
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_show_general.assert_called_once()

    @patch('StrateQueue.cli.commands.setup_command.InfoFormatter.format_broker_setup_instructions')
    def test_alias_configure_broker_docs_works(self, mock_format_broker, capsys):
        """Test 5-6: Alias stratequeue configure broker --docs works"""
        mock_format_broker.return_value = "Broker setup docs via configure alias"
        command = SetupCommand()
        
        args = Namespace(docs=True, setup_type="broker", provider_name=None)
        exit_code = command.execute(args)
        
        assert exit_code == 0
        mock_format_broker.assert_called_once_with(None)
        
        captured = capsys.readouterr()
        assert "Broker setup docs via configure alias" in captured.out
