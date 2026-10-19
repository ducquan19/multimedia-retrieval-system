import logging
import logging.handlers
from pathlib import Path

_FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_HANDLER_MARKER = "_aic_handler"
# Third-party loggers that flood INFO with per-request or import chatter.
_QUIET_LOGGERS = ("httpx", "httpcore", "huggingface_hub", "faiss.loader", "elastic_transport")


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure the root logger once: console plus an optional rotating file.

    Modules only call ``logging.getLogger(__name__)``; calling this again replaces the
    handlers it installed earlier instead of adding duplicates.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_MARKER, False)]:
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    handlers: list[logging.Handler] = [console]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "backend.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        handlers.append(file_handler)
    for handler in handlers:
        setattr(handler, _HANDLER_MARKER, True)
        root.addHandler(handler)
