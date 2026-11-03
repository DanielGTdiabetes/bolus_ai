import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from app.core import config
from app.core.gemini_models import resolve_gemini_model, migrate_gemini_settings
from app.models.settings import VisionConfig
from app.services.gemini_client import GeminiModel, function_response


URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"


def answer(parts):
    return {"candidates": [{"content": {"role": "model", "parts": parts}}]}


def test_environment_and_saved_settings_migrate(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_MODEL_PRO", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_TRANSCRIBE_MODEL", "gemini-2.0-flash-exp")
    assert config.get_gemini_model() == "gemini-3.5-flash-lite"
    assert config.get_gemini_pro_model() == "gemini-3.8-flash"
    assert config.get_gemini_transcribe_model() == "gemini-3.5-flash-lite"
    saved = VisionConfig(gemini_model="models/gemini-2.5-flash", gemini_transcribe_model="gemini-2.0-flash-exp")
    assert saved.gemini_model == saved.gemini_transcribe_model == config.get_gemini_model()
    assert resolve_gemini_model("gemini-custom-model") == "gemini-custom-model"


@pytest.mark.asyncio
@respx.mock
async def test_chat_preserves_signatures_ids_and_all_parts():
    parts = [{"text": "private reasoning", "thought": True, "thoughtSignature": "opaque-A"},
             {"functionCall": {"name": "lookup", "args": {"item": "test"}, "id": "call-1"},
              "thoughtSignature": "opaque-B"}]
    route = respx.post(URL).mock(side_effect=[
        httpx.Response(200, json=answer(parts)),
        httpx.Response(200, json=answer([{"text": "done"}])),
    ])
    model = GeminiModel("gemini-2.5-flash", api_key="test-key", tools=[{"name": "lookup"}])
    chat = model.start_chat()
    first = await chat.send_message_async("test")
    assert first.text == ""
    call = first.candidates[0].content.parts[1].function_call
    result = await chat.send_message_async({"role": "user", "parts": [function_response(call, {"ok": True})]})
    body = json.loads(route.calls[1].request.content)
    assert body["contents"][1] == {"role": "model", "parts": parts}
    assert body["contents"][2]["parts"][0]["functionResponse"] == {
        "id": "call-1", "name": "lookup", "response": {"ok": True}}
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "medium"
    assert result.text == "done"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("mime", ["image/png", "audio/wav"])
async def test_multimodal_json_request_removes_retired_parameters(mime):
    route = respx.post(URL).respond(200, json=answer([{"text": '{"ok":true}'}]))
    model = GeminiModel("gemini-3.5-flash-lite", api_key="test-key", generation_config={
        "temperature": 0, "top_p": .9, "top_k": 2, "candidate_count": 2,
        "thinking_budget": 100, "response_mime_type": "application/json", "max_output_tokens": 4096})
    response = await model.generate_content_async(["test", {"mime_type": mime, "data": b"bytes"}])
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["generationConfig"] == {"responseMimeType": "application/json", "maxOutputTokens": 4096,
                                        "thinkingConfig": {"thinkingLevel": "minimal"}}
    assert body["contents"][0]["parts"][1]["inlineData"] == {
        "mimeType": mime, "data": base64.b64encode(b"bytes").decode()}
    assert request.headers["x-goog-api-key"] == "test-key"
    assert "test-key" not in str(request.url)
    assert json.loads(response.text) == {"ok": True}


@pytest.mark.asyncio
@respx.mock
async def test_error_does_not_leak_payload_or_commit_chat_turn():
    respx.post(URL).respond(400, json={"error": {"message": "private-data"}})
    chat = GeminiModel("gemini-3.5-flash-lite", api_key="test-key").start_chat()
    with pytest.raises(RuntimeError, match="HTTP 400") as error:
        await chat.send_message_async("private-prompt")
    assert "private" not in str(error.value)
    assert chat.history == []


@pytest.mark.asyncio
@respx.mock
async def test_router_acknowledges_parallel_calls_but_executes_only_one(monkeypatch):
    from app.bot.llm import router
    from app.bot.capabilities import registry
    calls = [{"functionCall": {"name": "safe_lookup", "args": {}, "id": f"call-{i}"},
              "thoughtSignature": f"signature-{i}"} for i in range(2)]
    route = respx.post(URL).mock(side_effect=[httpx.Response(200, json=answer(calls)),
                                            httpx.Response(200, json=answer([{"text": "OK"}]))])
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    tool = SimpleNamespace(name="safe_lookup", description="Lookup", input_schema={"type": "object"}, permission=None)
    monkeypatch.setattr(registry, "build_registry", lambda: SimpleNamespace(tools=[tool]))
    execute = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(router, "execute_tool", execute)
    monkeypatch.setattr(router.memory, "get_context", lambda _: [])
    monkeypatch.setattr(router.memory, "add", lambda *args: None)
    reply = await router.handle_text("test", 987654321, "hola", {})
    assert reply.text == "OK"
    execute.assert_awaited_once_with("safe_lookup", {})
    body = json.loads(route.calls[1].request.content)
    responses = body["contents"][-1]["parts"]
    assert [r["functionResponse"]["id"] for r in responses] == ["call-0", "call-1"]
    assert "error" in responses[1]["functionResponse"]["response"]
    assert body["contents"][-2]["parts"] == calls


@pytest.mark.asyncio
async def test_raw_settings_api_migrates_models_without_changing_profile_or_version():
    from app.services import settings_service
    old = {"lunch": {"icr": 12}, "unknown": {"preserved": True}, "vision": {
        "gemini_model": "gemini-2.5-flash", "gemini_key": "test-only"}}
    row = SimpleNamespace(settings=old, version=7, updated_at=None)
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = row
    db.execute.return_value = result
    read = await settings_service.get_user_settings_service("tester", db)
    assert read["settings"]["vision"]["gemini_model"] == "gemini-3.5-flash-lite"
    assert read["settings"]["lunch"] == old["lunch"]
    assert read["settings"]["unknown"] == old["unknown"]
    assert read["settings"]["vision"]["gemini_key"] == "test-only"
    assert read["version"] == 7
    assert row.settings["vision"]["gemini_model"] == "gemini-2.5-flash"
    db.commit.assert_not_awaited()
    conflict = settings_service.VersionConflictError(7, old)
    assert conflict.server_settings == read["settings"]
    imported = await settings_service.import_user_settings_service("tester", old, db)
    assert not imported["imported"] and imported["settings"] == read["settings"]
    updated = await settings_service.update_user_settings_service("tester", old, 7, db)
    assert updated["version"] == 8 and updated["settings"] == read["settings"]
    assert migrate_gemini_settings(updated["settings"]) == updated["settings"]
