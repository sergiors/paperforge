import logging
import os

LOG_FORMAT = '%(asctime)s | %(levelname)s | %(name)s | %(message)s'


def configure_logging() -> None:
    """Configure application and Uvicorn logging based on ``LOG_LEVEL``.

    The level defaults to ``INFO`` and applies to both the application loggers
    and Uvicorn's loggers. Uvicorn's access log handlers are left untouched.
    """
    level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(level=level, format=LOG_FORMAT)

    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        logging.getLogger(name).setLevel(level)
