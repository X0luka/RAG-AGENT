"""Logging setup for application observability."""

import sys

from loguru import logger

from src.config import settings


def setup_logging() -> None:
    """Configure loguru console and file logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> <level>{level: <8}</level> "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - {message}"
        ),
    )
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.log_path,
        level="DEBUG",
        rotation="00:00",
        retention="14 days",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )
