import pytest

from app.bot.service import bot_send
from app.bot.state import health


class DummyBot:
    def __init__(self, should_raise: bool = False):
        self.should_raise = should_raise
        self.sent = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        if self.should_raise:
            raise RuntimeError("send failed")
        self.sent.append((chat_id, text, kwargs))
        return {"chat_id": chat_id, "text": text, **kwargs}


@pytest.mark.asyncio
async def test_bot_send_success_tracks_health():
    bot = DummyBot()
    health.last_reply_at = None
    health.last_reply_error = "previous"

    await bot_send(chat_id=123, text="ok", bot=bot)

    assert health.last_reply_error is None
    assert health.last_reply_at is not None
    assert bot.sent[0][0] == 123
    assert bot.sent[0][1] == "ok"


@pytest.mark.asyncio
async def test_bot_send_failure_records_error():
    bot = DummyBot(should_raise=True)
    health.last_reply_at = None
    health.last_reply_error = None

    await bot_send(chat_id=456, text="fail", bot=bot)

    assert health.last_reply_error is not None
    assert health.last_reply_at is None
