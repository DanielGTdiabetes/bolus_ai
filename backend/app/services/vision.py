import base64
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.core.settings import Settings
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


async def estimate_meal_from_image(
    image_bytes: bytes,
    mime_type: str,
    hints: dict,
    settings: Settings,
) -> VisionEstimateResponse:
    api_key = settings.vision.openai_api_key
    if not api_key:
        raise RuntimeError("OpenAI API Key not configured")

    client = AsyncOpenAI(api_key=api_key, timeout=settings.vision.timeout_seconds)

    # Encode image
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64_image}"

    user_prompt = "Estimate carbs for this meal."
    if hints.get("portion_hint"):
        user_prompt += f" Portion hint: {hints['portion_hint']}."
    if hints.get("meal_slot"):
        user_prompt += f" Meal slot: {hints['meal_slot']}."

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": PROMPT_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1000,
        )
    except Exception as exc:
        logger.error("OpenAI error", exc_info=True)
        raise RuntimeError(f"Vision provider error: {str(exc)}") from exc

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Empty response from Vision provider")

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Invalid JSON from vision: %s", content)
        raise RuntimeError("Vision provider returned invalid JSON")

    # Parse items and range
    items = [FoodItemEstimate(**item) for item in data.get("items", [])]
    total_g = sum(i.carbs_g for i in items)
    
    # Simple range heuristic if not provided
    # If confidence is low, range is +/- 30%. Medium +/- 20%. High +/- 10%
    conf = data.get("confidence", "low")
    margin = 0.3 if conf == "low" else (0.2 if conf == "medium" else 0.1)
    
    # But if specific range logic is desired we can refine. For now simple heuristic.
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
        glucose_used=GlucoseUsed(mgdl=None, source=None), # Placeholder
        bolus=None # Placeholder
    )


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
