import logging
import os
import re
from logging.config import dictConfig


_TELEGRAM_API_TOKEN_PATTERN = re.compile(
    r"(?i)(https?://api\.telegram\.org/bot)[^/\s?#]+"
)
_TELEGRAM_BOT_TOKEN_PATTERN = re.compile(r"(?<![\w-])\d{6,12}:[A-Za-z0-9_-]{20,}")


def redact_secrets(value: str) -> str:
    """Remove Telegram bot credentials from text before it reaches a log sink."""
    redacted = _TELEGRAM_API_TOKEN_PATTERN.sub(r"\1[REDACTED]", value)
    return _TELEGRAM_BOT_TOKEN_PATTERN.sub("[REDACTED_TELEGRAM_TOKEN]", redacted)


class SecretRedactingFormatter(logging.Formatter):
    """Format the complete record, then redact secrets including exception text."""

    def __init__(
        self,
        format: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        validate: bool = True,
        defaults: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            fmt=format,
            datefmt=datefmt,
            style=style,
            validate=validate,
            defaults=defaults,
        )

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def configure_logging() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structured": {
                    "()": "app.core.logging.SecretRedactingFormatter",
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


__all__ = ["SecretRedactingFormatter", "configure_logging", "redact_secrets"]
