"""Configuração centralizada de logs para todo o ecossistema do Rock Assistant."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

try:
    from rock_assistant.setup import config
except ImportError:
    from setup import config

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class LogEmitter:
    """Interface abstrata ou callback para emissão de logs para UIs (ex: Qt Signal)."""

    def __init__(self, callback=None) -> None:
        self.callback = callback

    def emit(self, record: logging.LogRecord, formatted_msg: str) -> None:
        if self.callback:
            try:
                self.callback(record, formatted_msg)
            except Exception:
                pass


class BroadcastLogHandler(logging.Handler):
    """Handler de log que envia registros para callbacks ou UIs conectadas."""

    def __init__(self, emitter: Optional[LogEmitter] = None) -> None:
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        if self.emitter:
            try:
                formatted = self.format(record)
                self.emitter.emit(record, formatted)
            except Exception:
                self.handleError(record)


_global_emitter: Optional[LogEmitter] = None
_configured = False


def get_global_log_emitter() -> LogEmitter:
    """Retorna o emissor global de logs."""
    global _global_emitter
    if _global_emitter is None:
        _global_emitter = LogEmitter()
    return _global_emitter


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path | str] = None,
    emitter: Optional[LogEmitter] = None,
    capture_root: bool = True,
) -> logging.Logger:
    """Configura os handlers de log para console, arquivo e emissor de UI."""
    global _configured, _global_emitter
    if emitter is not None:
        _global_emitter = emitter

    root_logger = logging.getLogger() if capture_root else logging.getLogger("rock")
    root_logger.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Evita duplicar handlers se já configurado
    if not _configured:
        # Handler para o Console (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # Handler para Arquivo Rotativo em logs/rock.log
        file_path = Path(log_file) if log_file else getattr(config, "LOG_DIR", Path("logs")) / "rock.log"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(file_path),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Handler para UI / Emitter
        active_emitter = _global_emitter or get_global_log_emitter()
        broadcast_handler = BroadcastLogHandler(active_emitter)
        broadcast_handler.setLevel(level)
        broadcast_handler.setFormatter(formatter)
        root_logger.addHandler(broadcast_handler)

        _configured = True

    return root_logger
