import logging
import os
from logging.config import dictConfig


def configure_logging() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structured": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "structured",
                    "level": log_level,
                }
            },
            "loggers": {
                "uvicorn": {"handlers": ["console"], "level": log_level},
                "uvicorn.error": {"handlers": ["console"], "level": log_level, "propagate": True},
                "uvicorn.access": {"handlers": ["console"], "level": log_level, "propagate": False},
            },
            "root": {"handlers": ["console"], "level": log_level},
        }
    )
    logging.getLogger(__name__).debug("Logging configured", extra={"level": log_level})


__all__ = ["configure_logging"]
