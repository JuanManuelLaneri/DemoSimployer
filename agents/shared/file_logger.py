"""
File Logger Utility

Configures logging to write to both console and files in the output directory.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler


def setup_file_logger(
    service_name: str,
    log_level: str = "INFO",
    output_dir: str = "/app/output",
    console_output: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Set up logging to write to both console and file.

    Args:
        service_name: Name of the service (e.g., "orchestrator", "analyzer")
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        output_dir: Directory to write log files
        console_output: Whether to also output to console
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup files to keep

    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove any existing handlers
    logger.handlers.clear()

    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_formatter = logging.Formatter(
        fmt='[%(name)s] %(levelname)s: %(message)s'
    )

    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # File handler with rotation
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_path / f"{service_name}_{timestamp}.log"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)  # Capture all levels in file
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)

    # Console handler (if enabled)
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    logger.info(f"File logging initialized: {log_file}")

    return logger


def get_logger(service_name: str) -> logging.Logger:
    """
    Get an existing logger by service name.

    Args:
        service_name: Name of the service

    Returns:
        Logger instance
    """
    return logging.getLogger(service_name)
