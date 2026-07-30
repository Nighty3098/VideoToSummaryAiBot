import logging
import sys
from datetime import datetime
from pathlib import Path

from config import LOGS_DIR

LOG_FORMAT = "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        original_levelname = record.levelname
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        result = super().format(record)
        record.levelname = original_levelname
        return result


def setup_logger(name: str = "bot") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColorFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    file_handler = logging.FileHandler(
        Path(LOGS_DIR) / f"bot_{datetime.now().strftime('%Y-%m-%d')}.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
