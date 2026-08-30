import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from typing import Any, Dict

from core.ports import LoggerPort


class StructuredLogger(LoggerPort):
    """Writes structured logs to stdout, truncated file, and full file."""

    def __init__(self, truncated_path="logs/truncated.log", full_path="logs/full.log"):
        os.makedirs(os.path.dirname(truncated_path), exist_ok=True)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        self.truncated_logger = logging.getLogger("truncated")
        self.full_logger = logging.getLogger("full")
        self._configure_truncated_logger(self.truncated_logger, truncated_path)
        self._configure_full_logger(self.full_logger, full_path)

    def _configure_truncated_logger(self, logger, path):
        logger.setLevel(logging.INFO)
        if logger.hasHandlers():
            logger.handlers.clear()

        # Console handler for live Render logs
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console.setFormatter(console_formatter)
        logger.addHandler(console)

        # Rotating file handler (truncated)
        file_handler = RotatingFileHandler(
            path, maxBytes=5*1024*1024, backupCount=2, encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)

    def _configure_full_logger(self, logger, path):
        logger.setLevel(logging.DEBUG)
        if logger.hasHandlers():
            logger.handlers.clear()

        file_handler = RotatingFileHandler(
            path, maxBytes=20*1024*1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    def log_truncated(self, component: str, message: str, **kwargs) -> None:
        log_entry = f"[{component}] {message}"
        if kwargs:
            log_entry += " " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        self.truncated_logger.info(log_entry)

    def log_full(self, component: str, message: str, payload: Any = None) -> None:
        log_entry = f"[{component}] {message}"
        if payload is not None:
            import json
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
            log_entry += f"\n--- payload ---\n{pretty}\n---------------"
        self.full_logger.debug(log_entry)
        # Also log a truncated version to the truncated stream
        self.log_truncated(component, message, payload_size=len(str(payload)) if payload else 0)