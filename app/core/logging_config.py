import logging
import sys

from PySide6.QtCore import QtMsgType, qInstallMessageHandler


def configure_logging(debug: bool = False) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    if not any(
        getattr(handler, "_pos_console_handler", False)
        for handler in root_logger.handlers
    ):
        stream = sys.stdout or sys.stderr
        if stream is not None:
            handler = logging.StreamHandler(stream)
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            handler._pos_console_handler = True
            root_logger.addHandler(handler)

    logging.captureWarnings(True)
    sys.excepthook = _handle_uncaught_exception
    qInstallMessageHandler(_handle_qt_message)


def _handle_uncaught_exception(exc_type, exc_value, traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, traceback)
        return
    logging.getLogger("pos").critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, traceback),
    )


def _handle_qt_message(message_type: QtMsgType, context, message: str) -> None:
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    level = levels.get(message_type, logging.WARNING)
    location = ""
    if context is not None and context.file:
        location = f" ({context.file}:{context.line})"
    logging.getLogger("qt").log(level, "%s%s", message, location)
