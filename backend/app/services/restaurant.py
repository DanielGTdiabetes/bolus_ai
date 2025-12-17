import json
import logging
import os
import re
from typing import Optional

import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory
from pydantic import BaseModel, Field

from app.core.config import get_gemini_model, get_google_api_key, get_vision_timeout

logger = logging.getLogger(__name__)

PROMPT_ANALYZE_MENU = """
Eres un asistente para diabetes y nutrición.
Recibirás una imagen de una CARTA DE RESTAURANTE (texto impreso o escrito).
Objetivo: ofrecer una estimación CONSERVADORA de carbohidratos, grasas y proteínas para un plato típico.

Instrucciones:
- Identifica hasta 3 platos plausibles con sus macronutrientes (gramos) por ración.
- Usa rangos conservadores (no sobreestimes; asume porciones estándar).
- Si la carta es confusa o no legible, sé explícito en advertencias y baja la confianza.
- NO generes dosis de insulina.

Devuelve JSON estricto:
{
  "expectedCarbs": number, // carbohidratos recomendados
  "expectedFat": number,   // grasas estimadas (opcional, 0 si desconocido)
  "expectedProtein": number, // proteínas estimadas (opcional, 0 si desconocido)
  "confidence": number,    // 0.0 a 1.0
  "items": [{"name": "...", "carbs_g": number, "fat_g": number, "protein_g": number, "notes": "..."}],
  "reasoning_short": "texto breve",
  "warnings": ["..."]
}
"""

PROMPT_COMPARE_PLATE = """
Eres un asistente para diabetes. Recibirás:
- expectedCarbs: carbohidratos que el usuario planificó a partir del menú.
- Una foto del plato REAL servido.

Debes COMPARAR (no recalcular desde cero la carta) y estimar si el plato tiene más o menos carbohidratos que lo esperado.

Devuelve JSON estricto:
{
  "actualCarbs": number, // carbohidratos estimados del plato servido
  "actualFat": number,   // grasas estimadas
  "actualProtein": number, // proteínas estimadas
  "confidence": number,  // 0.0 a 1.0
  "reasoning_short": "texto breve",
  "warnings": ["..."]
}

Reglas: sé conservador, indica dudas en warnings, NO propongas dosis de insulina ni órdenes de comida.
"""

PROMPT_ANALYZE_PLATE_SIMPLE = """
Eres un asistente para diabetes. Recibirás una foto de un plato servido.

Objetivo: estimar carbohidratos, grasas y proteínas de forma conservadora.

Devuelve JSON estricto:
{
  "carbs": number,         // carbohidratos estimados
  "fat": number,           // grasas estimadas (g)
  "protein": number,       // proteínas estimadas (g)
  "confidence": number,    // 0.0 a 1.0
  "reasoning_short": "texto breve",
  "warnings": ["..."]
}

Reglas: sé conservador y explícito en tus dudas. NO sugieras insulina.
"""

DEFAULT_MAX_MICRO_BOLUS_U = float(os.getenv("RESTAURANT_MAX_MICRO_BOLUS_U", "1.0"))
DEFAULT_CONFIDENCE_FLOOR = 0.55
DEFAULT_CARB_SUGGESTION = int(os.getenv("RESTAURANT_CORRECTION_CARBS", "12"))
DELTA_ACTION_THRESHOLD = float(os.getenv("RESTAURANT_DELTA_ACTION_THRESHOLD", "8"))
LARGE_DELTA = float(os.getenv("RESTAURANT_LARGE_DELTA", "60"))


class RestaurantMenuResult(BaseModel):
    expectedCarbs: Optional[float] = None
    expectedFat: Optional[float] = 0.0
    expectedProtein: Optional[float] = 0.0
    confidence: float
    items: list = Field(default_factory=list)
    reasoning_short: str = ""
    warnings: list[str] = Field(default_factory=list)


class SuggestedAction(BaseModel):
    type: str
    units: Optional[float] = None
    carbsGrams: Optional[int] = None


class RestaurantPlateEstimate(BaseModel):
    carbs: Optional[float] = None
    fat: Optional[float] = 0.0
    protein: Optional[float] = 0.0
    confidence: float
    reasoning_short: str = ""
    warnings: list[str] = Field(default_factory=list)


class RestaurantPlateResult(BaseModel):
    expectedCarbs: float
    actualCarbs: Optional[float]
    deltaCarbs: Optional[float]
    confidence: float
    reasoning_short: str
    warnings: list[str] = Field(default_factory=list)
    suggestedAction: SuggestedAction = Field(default_factory=lambda: SuggestedAction(type="NO_ACTION"))


def _repair_json(json_str: str) -> str:
    """
    Attempts to repair truncated JSON by closing open brackets/braces in correct order.
    """
    stack = []
    in_string = False
    escape = False
    
    for char in json_str:
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == '{':
                stack.append('}')
            elif char == '[':
                stack.append(']')
            elif char == '}' or char == ']':
                if stack and stack[-1] == char:
                    stack.pop()
                    
    # Close any open string first
    if in_string:
        json_str += '"'
        
    # Close structures in reverse order (LIFO)
    while stack:
        json_str += stack.pop()
        
    return json_str


def _safe_json_load(content: str) -> dict:
    if not content:
        raise RuntimeError("Empty response from vision provider")

    # 1. Try direct load
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Markdown cleanup
    cleaned = content.strip()
    if "```" in cleaned:
        match = re.search(r"```(?:\w+)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("\n", 1)[0]
    
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Aggressive extraction (outermost braces)
    match = re.search(r'(\{.*\})', content, re.DOTALL)
    if match:
        candidate = match.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try repairing the extracted candidate
            try:
                repaired = _repair_json(candidate)
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    # 4. Attempt repair on the cleaned content
    try:
        repaired = _repair_json(cleaned)
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    logger.error("JSON Parse Error (restaurant). Raw content: %s", content[:500])
    raise RuntimeError("Invalid JSON response from vision provider (Syntax Error)")


def _float_value(val: Optional[float], default: float = 0.0) -> float:
    try:
        if isinstance(val, str):
            lowered = val.lower()
            if lowered == "high":
                return 0.85
            if lowered == "medium":
                return 0.65
            if lowered == "low":
                return 0.35
        return float(val)
    except Exception:
        return default


def _configure_model():
    api_key = get_google_api_key()
    if not api_key:
        raise RuntimeError("Google API Key not configured")
    genai.configure(api_key=api_key)
    generation_config = {
        "temperature": 0.1,
        "max_output_tokens": 2048,
        "response_mime_type": "application/json",
    }
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }
    model = genai.GenerativeModel(get_gemini_model(), generation_config=generation_config, safety_settings=safety_settings)
    return model


def _timeout_kwargs():
    timeout = get_vision_timeout()
    return {"request_options": {"timeout": timeout}}


def _normalize_warnings(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(w) for w in raw]
    return [str(raw)]


async def analyze_menu_with_gemini(image_bytes: bytes, mime_type: str) -> RestaurantMenuResult:
    model = _configure_model()
    parts = [
        PROMPT_ANALYZE_MENU,
        {"mime_type": mime_type, "data": image_bytes},
    ]
    try:
        response = await model.generate_content_async(parts, **_timeout_kwargs())
        # Check for safety blocking or other issues
        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"Gemini Vision blocked content: {response.prompt_feedback}")
             raise RuntimeError(f"Content blocked by safety filters: {response.prompt_feedback.block_reason}")
             
        content = response.text
    except Exception as e:
        logger.error(f"Gemini generation error: {e}")
        # If it's a blocked response, the .text attribute access raises ValueError
        if "parts" in str(e) or "empty" in str(e):
             raise RuntimeError("Gemini returned empty response (likely blocked by safety settings)")
        raise

    data = _safe_json_load(content)

    expected = data.get("expectedCarbs")
    expected_fat = _float_value(data.get("expectedFat"), 0.0)
    expected_protein = _float_value(data.get("expectedProtein"), 0.0)
    confidence = _float_value(data.get("confidence"), 0.4)
    items = data.get("items", []) or []
    reasoning_short = data.get("reasoning_short", "")
    warnings = _normalize_warnings(data.get("warnings"))

    if expected is None and items:
        try:
            expected = sum(float(i.get("carbs_g", 0) or 0) for i in items) / max(1, len(items))
            # Optional: average fat/protein too if missing from top level
            if not expected_fat:
                expected_fat = sum(float(i.get("fat_g", 0) or 0) for i in items) / max(1, len(items))
            if not expected_protein:
                expected_protein = sum(float(i.get("protein_g", 0) or 0) for i in items) / max(1, len(items))
        except Exception:
            expected = None

    if expected is not None:
        try:
            expected = round(float(expected), 1)
        except Exception:
            expected = None

    return RestaurantMenuResult(
        expectedCarbs=expected,
        expectedFat=round(expected_fat, 1),
        expectedProtein=round(expected_protein, 1),
        confidence=confidence,
        items=items,
        reasoning_short=reasoning_short,
        warnings=warnings,
    )


async def analyze_plate_with_gemini(image_bytes: bytes, mime_type: str) -> RestaurantPlateEstimate:
    model = _configure_model()
    parts = [
        PROMPT_ANALYZE_PLATE_SIMPLE,
        {"mime_type": mime_type, "data": image_bytes},
    ]
    response = await model.generate_content_async(parts, **_timeout_kwargs())
    content = response.text
    data = _safe_json_load(content)

    carbs = data.get("carbs")
    fat_val = _float_value(data.get("fat"), 0.0)
    prot_val = _float_value(data.get("protein"), 0.0)
    confidence = _float_value(data.get("confidence"), 0.4)
    reasoning_short = data.get("reasoning_short", "")
    warnings = _normalize_warnings(data.get("warnings"))

    try:
        carbs_val = round(float(carbs), 1) if carbs is not None else None
    except Exception:
        carbs_val = None

    return RestaurantPlateEstimate(
        carbs=carbs_val,
        fat=round(fat_val, 1),
        protein=round(prot_val, 1),
        confidence=confidence,
        reasoning_short=reasoning_short,
        warnings=warnings,
    )


def _apply_guardrails(result: RestaurantPlateResult) -> RestaurantPlateResult:
    warnings = list(result.warnings or [])
    action = SuggestedAction(type="NO_ACTION")
    delta = result.deltaCarbs or 0

    if result.confidence < DEFAULT_CONFIDENCE_FLOOR:
        warnings.append("Confianza baja: no se aplica acción automática.")
        result.suggestedAction = action
        result.warnings = warnings
        return result

    if delta > DELTA_ACTION_THRESHOLD:
        units = round(delta / 15, 2)
        units = min(max(units, 0.0), DEFAULT_MAX_MICRO_BOLUS_U)
        if delta >= LARGE_DELTA:
            warnings.append("Delta alto: usar micro-ajustes y vigilar glucosa.")
        if units > 0:
            action = SuggestedAction(type="ADD_INSULIN", units=units)
    elif delta < -DELTA_ACTION_THRESHOLD:
        carbs = max(10, min(DEFAULT_CARB_SUGGESTION, 15))
        if abs(delta) >= LARGE_DELTA:
            warnings.append("Delta negativo grande: preferir hidratos en pasos pequeños.")
        action = SuggestedAction(type="EAT_CARBS", carbsGrams=carbs)

    result.suggestedAction = action
    result.warnings = list(dict.fromkeys(warnings))
    return result


def guardrails_from_totals(
    expected_carbs: float,
    actual_carbs: float,
    confidence: Optional[float] = None,
    base_warnings: Optional[list[str]] = None,
    reasoning_short: str | None = None,
) -> RestaurantPlateResult:
    warnings = _normalize_warnings(base_warnings)
    try:
        expected_val = round(float(expected_carbs), 1)
    except Exception as exc:
        raise RuntimeError("expected_carbs_missing") from exc

    try:
        actual_val = round(float(actual_carbs), 1)
    except Exception as exc:
        raise RuntimeError("actual_carbs_missing") from exc

    delta = round(actual_val - expected_val, 1)
    result = RestaurantPlateResult(
        expectedCarbs=expected_val,
        actualCarbs=actual_val,
        deltaCarbs=delta,
        confidence=_float_value(confidence, DEFAULT_CONFIDENCE_FLOOR),
        reasoning_short=reasoning_short or "Ajuste agregado de sesión restaurante",
        warnings=warnings,
    )
    return _apply_guardrails(result)


async def compare_plate_with_gemini(
    image_bytes: bytes,
    mime_type: str,
    expected_carbs: float,
    confidence_override: Optional[float] = None,
) -> RestaurantPlateResult:
    model = _configure_model()
    prompt = PROMPT_COMPARE_PLATE + f"\nexpectedCarbs={expected_carbs}"
    parts = [prompt, {"mime_type": mime_type, "data": image_bytes}]
    response = await model.generate_content_async(parts, **_timeout_kwargs())
    content = response.text
    data = _safe_json_load(content)

    actual = data.get("actualCarbs")
    confidence = _float_value(data.get("confidence"), 0.4)
    reasoning_short = data.get("reasoning_short", "")
    warnings = _normalize_warnings(data.get("warnings"))

    try:
        actual_val = round(float(actual), 1) if actual is not None else None
    except Exception:
        actual_val = None

    delta = None
    if actual_val is not None and expected_carbs is not None:
        try:
            delta = round(actual_val - float(expected_carbs), 1)
        except Exception:
            delta = None

    result = RestaurantPlateResult(
        expectedCarbs=float(expected_carbs),
        actualCarbs=actual_val,
        deltaCarbs=delta,
        confidence=confidence_override if confidence_override is not None else confidence,
        reasoning_short=reasoning_short,
        warnings=warnings,
    )

    return _apply_guardrails(result)
