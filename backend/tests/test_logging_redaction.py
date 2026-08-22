import logging

from app.core.logging import SecretRedactingFormatter, configure_logging, redact_secrets


DUMMY_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


def test_redact_secrets_hides_token_in_telegram_api_url() -> None:
    value = f"HTTP Request: POST https://api.telegram.org/bot{DUMMY_TOKEN}/getMe"

    redacted = redact_secrets(value)

    assert DUMMY_TOKEN not in redacted
    assert "https://api.telegram.org/bot[REDACTED]/getMe" in redacted


def test_redact_secrets_hides_bare_telegram_token() -> None:
    redacted = redact_secrets(f"TELEGRAM_BOT_TOKEN={DUMMY_TOKEN}")

    assert DUMMY_TOKEN not in redacted
    assert redacted == "TELEGRAM_BOT_TOKEN=[REDACTED_TELEGRAM_TOKEN]"


def test_formatter_redacts_secret_from_exception_trace() -> None:
    formatter = SecretRedactingFormatter("%(levelname)s %(message)s")
    try:
        raise RuntimeError(
            f"request failed at https://api.telegram.org/bot{DUMMY_TOKEN}/sendMessage"
        )
    except RuntimeError:
        record = logging.getLogger("test.logging.redaction").makeRecord(
            "test.logging.redaction",
            logging.ERROR,
            __file__,
            1,
            "Telegram request failed",
            (),
            exc_info=__import__("sys").exc_info(),
        )

    rendered = formatter.format(record)

    assert DUMMY_TOKEN not in rendered
    assert "https://api.telegram.org/bot[REDACTED]/sendMessage" in rendered


def test_configure_logging_installs_secret_redacting_formatter() -> None:
    configure_logging()

    formatters = {
        type(handler.formatter)
        for handler in logging.getLogger().handlers
        if handler.formatter is not None
    }
    assert SecretRedactingFormatter in formatters
