import base64
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.core.settings import Settings
from app.core.config import get_gemini_model
from app.models.vision import FoodItemEstimate, VisionEstimateResponse, GlucoseUsed

logger = logging.getLogger(__name__)


PROMPT_SYSTEM = """
You are an expert nutritionist and diabetes educator. 
Analyze the image of food provided. 
Estimate carbohydrates precisely.
Output STRICT JSON.
Structure:
{
  "items": [{"name": "...", "carbs_g": number, "notes": "..."}],
  "confidence": "low"|"medium"|"high",
  "fat_score": 0.0 to 1.0 (1.0 = very high fat/protein content like pizza, burger, creamy pasta),
  "slow_absorption_score": 0.0 to 1.0 (1.0 = very slow absorption expected),
  "assumptions": ["assumption1", ...],
  "needs_user_input": [{"id": "q1", "question": "...", "options": ["..."]}] (only if critical ambiguity exists)
}
Be conservative. If portion is unclear, state assumptions.
"""


import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

async def estimate_meal_from_image(
    image_bytes: bytes,
    mime_type: str,
    hints: dict,
    settings: Settings,
) -> VisionEstimateResponse:
    provider = settings.vision.provider.lower()
    
    if provider == "gemini":
        data = await _estimate_with_gemini(image_bytes, mime_type, hints, settings)
    else:
        data = await _estimate_with_openai(image_bytes, mime_type, hints, settings)

    return _parse_estimation_data(data)


def _parse_estimation_data(data: dict) -> VisionEstimateResponse:
    items = [FoodItemEstimate(**item) for item in data.get("items", [])]
    total_g = sum(i.carbs_g for i in items)
    
    conf = data.get("confidence", "low")
    margin = 0.3 if conf == "low" else (0.2 if conf == "medium" else 0.1)
    
    range_min = round(total_g * (1 - margin))
    range_max = round(total_g * (1 + margin))

    return VisionEstimateResponse(
        carbs_estimate_g=total_g,
        carbs_range_g=(range_min, range_max),
        confidence=conf,
        items=items,
        fat_score=data.get("fat_score", 0.0),
        slow_absorption_score=data.get("slow_absorption_score", 0.0),
        assumptions=data.get("assumptions", []),
        needs_user_input=data.get("needs_user_input", []),
        glucose_used=GlucoseUsed(mgdl=None, source=None),
        bolus=None
    )
# ... lines omitted ...
async def _estimate_with_gemini(image_bytes: bytes, mime_type: str, hints: dict, settings: Settings) -> dict:
    api_key = settings.vision.google_api_key
    if not api_key:
        raise RuntimeError("Google API Key not configured")

    genai.configure(api_key=api_key)
    
    generation_config = {
        "temperature": 0.0,
        "max_output_tokens": 1000,
        "response_mime_type": "application/json",
    }
    
    # Safety settings to avoid blocking food images
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }

    model_name = get_gemini_model()
    model = genai.GenerativeModel(model_name, generation_config=generation_config, safety_settings=safety_settings)

    user_prompt = _build_user_prompt(hints)
    
    # Gemini accepts dict for image parts if using raw bytes is tricky, but the python SDK 
    # supports: parts=[text, {'mime_type': 'image/jpeg', 'data': bytes}]
    
    prompt_parts = [
        PROMPT_SYSTEM + "\n\n" + user_prompt,
        {"mime_type": mime_type, "data": image_bytes}
    ]

    try:
        # Generate content is sync in the generic sdk wrapper but we should run it in threadpool if it blocks
        # However, for simplicity here (and since it's "async def"), we can rely on standard executor if libraries block?
        # genai.GenerativeModel.generate_content_async exists in newer versions.
        response = await model.generate_content_async(prompt_parts)
    except Exception as exc:
        logger.error("Gemini error", exc_info=True)
        raise RuntimeError(f"Gemini error: {str(exc)}") from exc

    return _safe_json_load(response.text)


def _build_user_prompt(hints: dict) -> str:
    user_prompt = "Estimate carbs for this meal."
    if hints.get("portion_hint"):
        user_prompt += f" Portion hint: {hints['portion_hint']}."
    if hints.get("meal_slot"):
        user_prompt += f" Meal slot: {hints['meal_slot']}."
    return user_prompt


def _safe_json_load(content: str) -> dict:
    if not content:
        raise RuntimeError("Empty response from vision provider")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Sometimes providers wrap in ```json ... ``` despite instructions?
        # OpenAI JSON mode handles this usually. Gemini response_mime_type also handles it.
        # Simple cleanup backup
        clean = content.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.endswith("```"):
            clean = clean[:-3]
        return json.loads(clean)


def calculate_extended_split(
    total_u: float, 
    fat_score: float, 
    slow_score: float,
    items_hints: list[str]
) -> tuple[float, float, int]:
    """
    Returns (upfront_u, later_u, delay_min) based on scores and logic.
    Defaukts: 65% / 35% / 120min
    """
    if total_u <= 0:
        return 0.0, 0.0, 0

    # Base heavy meal logic
    upfront_pct = 0.65
    delay = 120

    is_pizza_burger = False
    is_creamy_pasta = False
    is_dessert = False

    combined_text = " ".join(items_hints).lower()
    
    if any(x in combined_text for x in ["pizza", "burger", "hamburguesa", "frito", "cheese","queso"]):
        is_pizza_burger = True
    elif "pasta" in combined_text and ("cream" in combined_text or "carbonara" in combined_text or "nata" in combined_text):
        is_creamy_pasta = True
    elif any(x in combined_text for x in ["ice cream", "helado", "cake", "tarta", "chocolate"]):
        is_dessert = True

    if is_pizza_burger:
        upfront_pct = 0.60
        delay = 150 # 120-180 -> 150 avg
    elif is_creamy_pasta:
        upfront_pct = 0.70
        delay = 105 # 90-120 -> 105
    elif is_dessert:
        upfront_pct = 0.62
        delay = 105 
    elif fat_score > 0.8 or slow_score > 0.8:
        upfront_pct = 0.60
        delay = 150
    
    upfront = round(total_u * upfront_pct, 2) # rounding step handled later or here? user said round step 0.05
    # let's do precision 2 here, final rounding in caller
    later = total_u - upfront
    
    return upfront, later, delay
