import pytest
from types import SimpleNamespace

from app.bot import service


class DummyCallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.edited_text = None

    async def edit_message_text(self, text, **kwargs):
        self.edited_text = text


class DummyUpdate:
    def __init__(self, data: str):
        self.callback_query = DummyCallbackQuery(data)
        self.effective_chat = SimpleNamespace(id=123)
        self.effective_user = SimpleNamespace(id=999)
        self.message = None


@pytest.mark.asyncio
async def test_voice_callback_yes_routes_transcript(monkeypatch):
    captured = {}

    async def fake_handle_message(update, context):
        captured["text"] = getattr(update.message, "text", None)

    update = DummyUpdate("voice_confirm_yes")
    context = SimpleNamespace(user_data={"pending_voice_text": "hola mundo"})

    monkeypatch.setattr(service, "handle_message", fake_handle_message)

    await service._handle_voice_callback(update, context)

    assert captured["text"] == "hola mundo"
    assert update.callback_query.edited_text.startswith("✅")
    assert "pending_voice_text" not in context.user_data


@pytest.mark.asyncio
async def test_voice_callback_cancel_clears_pending():
    update = DummyUpdate("voice_confirm_cancel")
    context = SimpleNamespace(user_data={"pending_voice_text": "cualquier cosa"})

    await service._handle_voice_callback(update, context)

    assert update.callback_query.edited_text == "❌ Transcripción descartada."
    assert "pending_voice_text" not in context.user_data


def test_sanitize_url_removes_query_and_fragment():
    url = "https://example.com/path?token=abc#frag"
    assert service._sanitize_url(url) == "https://example.com/path"
