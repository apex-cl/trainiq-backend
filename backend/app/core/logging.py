"""
Logging-Konfiguration für TrainIQ.
Nutzt loguru für strukturierte, farbige Logs.
"""

import sys
from loguru import logger
from app.core.config import settings


def setup_logging():
    """Konfiguriert Loguru für die Anwendung."""
    # Standard-Logger entfernen
    logger.remove()

    # Konsolen-Output (für Docker logs)
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        format=log_format,
        level="DEBUG" if settings.dev_mode else "INFO",
        colorize=True,
    )

    # File-Logging (rotierend, 10MB max, 7 Tage)
    logger.add(
        "/tmp/trainiq.log",
        format="{time} | {level} | {name}:{function}:{line} | {message}",
        level="INFO",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
    )

    return logger
