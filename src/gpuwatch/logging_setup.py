from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .config import LOG_DIR, LOG_LEVELS, LOG_PATH

logger = logging.getLogger(__name__)

LOG_FORMAT = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
)


class QtLogBridge(QObject):
    record = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: QtLogBridge):
        super().__init__()
        self._bridge = bridge
        self.setFormatter(LOG_FORMAT)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bridge.record.emit(self.format(record))
        except Exception:
            pass


_bridge: QtLogBridge | None = None
_qt_handler: QtLogHandler | None = None
_file_handler: RotatingFileHandler | None = None
_stream_handler: logging.Handler | None = None


def setup_logging(level: str = "INFO") -> None:
    global _bridge, _qt_handler, _file_handler, _stream_handler

    level = level if level in LOG_LEVELS else "INFO"
    root = logging.getLogger()
    root.setLevel(getattr(logging, level))

    if _file_handler is None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(LOG_FORMAT)
        root.addHandler(handler)
        _file_handler = handler

    if _bridge is None and QApplication.instance() is not None:
        _bridge = QtLogBridge()
    if _bridge is not None and _qt_handler is None:
        _qt_handler = QtLogHandler(_bridge)
        root.addHandler(_qt_handler)

    # windowed 打包后 stderr 为 None，只写文件
    if _stream_handler is None and sys.stderr is not None:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(LOG_FORMAT)
        root.addHandler(handler)
        _stream_handler = handler

    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("keyring").setLevel(logging.WARNING)
    logger.info("logging initialized at %s", level)


def get_log_bridge() -> QtLogBridge | None:
    return _bridge
