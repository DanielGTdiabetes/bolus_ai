"""Small async generateContent transport; retain opaque model parts unchanged.

The legacy google-generativeai 0.5 SDK cannot round-trip Gemini 3 thought
signatures or function IDs. Raw REST keeps these fields without coupling this
migration to upgrades of the application's Pydantic and HTTP dependencies.
"""

import base64
import copy
from types import SimpleNamespace
from urllib.parse import quote

import httpx

from app.core.config import get_vision_timeout
from app.core.gemini_models import resolve_gemini_model


class GeminiResponse:
    def __init__(self, data: dict):
        self.raw = data
        self.prompt_feedback = data.get("promptFeedback")
        self.candidates = []
        for candidate in data.get("candidates", []):
            parts = []
            for part in candidate.get("content", {}).get("parts", []):
                call = part.get("functionCall")
                parts.append(SimpleNamespace(
                    text=part.get("text", "") if not part.get("thought") else "",
                    function_call=SimpleNamespace(
                        name=call["name"], args=call.get("args", {}), id=call.get("id")
                    ) if call else None,
                ))
            self.candidates.append(SimpleNamespace(
                content=SimpleNamespace(parts=parts),
                avg_logprob=candidate.get("avgLogprobs"),
            ))

    @property
    def text(self):
        if not self.candidates:
            return ""
        return "".join(p.text for p in self.candidates[0].content.parts)


def _user_content(value):
    if isinstance(value, dict) and "parts" in value:
        return copy.deepcopy(value)
    values = value if isinstance(value, list) else [value]
    parts = []
    for part in values:
        if isinstance(part, str):
            parts.append({"text": part})
        elif "data" in part and "mime_type" in part:
            parts.append({"inlineData": {
                "mimeType": part["mime_type"],
                "data": base64.b64encode(part["data"]).decode("ascii"),
            }})
        else:
            parts.append(copy.deepcopy(part))
    return {"role": "user", "parts": parts}


def function_response(call, result):
    response = {"name": call.name, "response": result}
    if call.id is not None:
        response["id"] = call.id
    return {"functionResponse": response}


class GeminiModel:
    def __init__(self, model_name, *, api_key, tools=None, system_instruction=None,
                 generation_config=None, safety_settings=None):
        if not api_key:
            raise ValueError("Google API Key not configured")
        self.model_name = resolve_gemini_model(model_name)
        self.api_key = api_key
        self.options = {}
        if system_instruction:
            self.options["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if tools:
            self.options["tools"] = [{"functionDeclarations": tools}]
        generation = {}
        for key, value in (generation_config or {}).items():
            if key in {"temperature", "top_p", "top_k", "candidate_count", "thinking_budget"}:
                continue
            generation[{"max_output_tokens": "maxOutputTokens",
                        "response_mime_type": "responseMimeType"}.get(key, key)] = value
        if self.model_name.startswith("gemini-3"):
            generation["thinkingConfig"] = {
                "thinkingLevel": "minimal" if not tools and "flash-lite" in self.model_name else "medium"
            }
        self.options["generationConfig"] = generation
        if safety_settings:
            self.options["safetySettings"] = [
                {"category": category, "threshold": threshold}
                for category, threshold in safety_settings.items()
            ]

    async def _generate(self, contents):
        body = {**self.options, "contents": contents}
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(self.model_name, safe="-._") + ":generateContent"
        async with httpx.AsyncClient(timeout=get_vision_timeout()) as client:
            response = await client.post(url, headers={"x-goog-api-key": self.api_key}, json=body)
        if response.is_error:
            # Do not put provider payloads, private prompts or credentials in logs.
            raise RuntimeError(f"Gemini {self.model_name}: HTTP {response.status_code}")
        return GeminiResponse(response.json())

    async def generate_content_async(self, contents):
        return await self._generate([_user_content(contents)])

    def start_chat(self):
        return GeminiChat(self)


class GeminiChat:
    def __init__(self, model):
        self.model = model
        self.history = []

    async def send_message_async(self, message):
        contents = [*self.history, _user_content(message)]
        response = await self.model._generate(contents)
        candidates = response.raw.get("candidates", [])
        if candidates and candidates[0].get("content", {}).get("parts"):
            # Preserve ALL original parts, including thoughtSignature and IDs.
            self.history = [*contents, copy.deepcopy(candidates[0]["content"])]
        return response
