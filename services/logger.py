"""Central logging utilities that unify console and file output."""

import logging
from pathlib import Path
from typing import Optional

from datetime import datetime


LOG_DIR_NAME = "logs"
LOG_FILE_BASENAME = "mineru-client"
RECENT_SUFFIX = "_recent"


def setup_logging(log_directory: Path | str | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure application-wide logging with per-run file rotation."""
    log_dir = Path(log_directory).expanduser() if log_directory else Path(".") / LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = _prepare_log_file(log_dir)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root_logger = logging.getLogger("mineru")
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.propagate = False

    root_logger.info("日志输出初始化：%s", log_path.name)
    return root_logger


def _prepare_log_file(log_dir: Path) -> Path:
    """Rotate existing run-specific logs and return the path for the current run."""
    for recent_file in log_dir.glob(f"*{RECENT_SUFFIX}.log"):
        new_name = recent_file.name.replace(RECENT_SUFFIX, "")
        target = recent_file.with_name(new_name)
        counter = 1
        while target.exists():
            target = recent_file.with_name(f"{target.stem}_{counter}.log")
            counter += 1
        recent_file.rename(target)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f"{LOG_FILE_BASENAME}_{timestamp}{RECENT_SUFFIX}.log"
    return log_dir / log_name


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return child logger under the mineru namespace."""
    base_name = "mineru"
    if name:
        return logging.getLogger(f"{base_name}.{name}")
    return logging.getLogger(base_name)
