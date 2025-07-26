"""
Logging Setup Utilities

Provides standardized logging configuration for CLI commands.
"""

import logging
import sys


def setup_logging(verbose_level: int = 0, log_file: str | None = None) -> None:
    """
    Setup logging configuration for CLI

    Args:
        verbose_level: Verbosity level (0=standard, 1=info, 2=debug)
        log_file: Optional log file path
    """
    # Determine log level based on verbosity
    if verbose_level == 0:
        log_level = logging.WARNING  # Standard: only warnings and errors
        console_level = logging.WARNING
    elif verbose_level == 1:
        log_level = logging.INFO  # Verbose: info, warnings, and errors
        console_level = logging.INFO
    else:  # verbose_level >= 2
        log_level = logging.DEBUG  # Very verbose: everything
        console_level = logging.DEBUG

    # Create formatter based on verbosity level
    if verbose_level >= 2:
        # Detailed formatter for debug mode
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    elif verbose_level == 1:
        # Simplified formatter for info mode
        formatter = logging.Formatter("%(levelname)s - %(message)s")
    else:
        # Minimal formatter for standard mode
        formatter = logging.Formatter("%(message)s")

    # Setup root logger
    root_logger = logging.getLogger()
    
    # Always configure logging to ensure consistent behavior
    # Clear any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Setup console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # Setup file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Always debug level for file
        file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Configure external library logging based on verbosity
    external_loggers = [
        "urllib3", "requests", "websocket", "uvicorn", "fastapi", 
        "alpaca", "ccxt", "ib_insync", "pandas", "numpy"
    ]
    
    for logger_name in external_loggers:
        external_logger = logging.getLogger(logger_name)
        if verbose_level == 0:
            external_logger.setLevel(logging.ERROR)  # Only errors
        elif verbose_level == 1:
            external_logger.setLevel(logging.WARNING)  # Warnings and errors
        else:  # verbose_level >= 2
            external_logger.setLevel(logging.INFO)  # More verbose for debugging


def get_cli_logger(name: str) -> logging.Logger:
    """
    Get a properly configured logger for CLI components

    Args:
        name: Logger name

    Returns:
        Configured logger instance
    """
    return logging.getLogger(f"StrateQueue.cli.{name}")
