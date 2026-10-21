import logging

from app.core.logging_config import configure_logging


def test_configure_logging_writes_debug_messages_to_console(caplog):
    configure_logging(debug=True)

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("pos.test").debug("debug log check")

    assert "debug log check" in caplog.text
