import pytest

from app.bot import service as bot_service
from app.bot.state import BotMode


@pytest.mark.parametrize(
    "env,expected_mode,expected_reason",
    [
        ({"ENABLE_TELEGRAM_BOT": "false"}, BotMode.DISABLED, "feature_flag_off"),
        ({"ENABLE_TELEGRAM_BOT": "true"}, BotMode.DISABLED, "missing_token"),
        (
            {"ENABLE_TELEGRAM_BOT": "true", "TELEGRAM_BOT_TOKEN": "dummy"},
            BotMode.POLLING,
            "forced_polling_on_prem",
        ),
        (
            {
                "ENABLE_TELEGRAM_BOT": "true",
                "TELEGRAM_BOT_TOKEN": "dummy",
                "PUBLIC_URL": "https://example.com",
            },
            BotMode.POLLING,
            "forced_polling_on_prem",
        ),
    ],
)
def test_decide_bot_mode(monkeypatch, env, expected_mode, expected_reason):
    monkeypatch.delenv("ENABLE_TELEGRAM_BOT", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("BOT_PUBLIC_URL", raising=False)

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    mode, reason = bot_service.decide_bot_mode()
    assert mode == expected_mode
    assert reason == expected_reason
