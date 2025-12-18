import base64
import json
import logging
import re
from typing import Optional

from openai import AsyncOpenAI

from app.core.settings import Settings
from app.core.config import get_gemini_model
from app.models.vision import FoodItemEstimate, VisionEstimateResponse, GlucoseUsed

logger = logging.getLogger(__name__)


PROMPT_SYSTEM = """
You are an expert nutritionist and diabetes educator. 
Analyze the image of food provided. 
Estimate carbohydrates, fats, and proteins precisely.
If the image is a RESTAURANT MENU, list the distinct dishes visible.

**FIDUCIAL MARKER INSTRUCTION:**
If you detect a **RED INSULIN PEN** (NovoPen Echo Plus style, cylindrical, dark red metallic) in the image, use it as a **FIDUCIAL MARKER** for scale.
- The pen measures **exactly 16.5 cm (165 mm)** in length.
- Use this precise length to calculate the real world dimensions (diameter/volume) of the plates and food portions.
- If present, explicitly mention in the "assumptions" field that you used the insulin pen for scale calibration.

Output STRICT JSON (RFC 8259 compliant).
- NO comments // or /* */
- NO trailing commas
- NO markdown if possible, just raw JSON
- Concise notes (max 10 words)
Structure:
{
  "items": [{"name": "...", "carbs_g": number, "fat_g": number, "protein_g": number, "notes": "..."}],
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

def _safe_json_load(content: str) -> dict:
    if not content:
        raise RuntimeError("Empty response from vision provider")

    # 1. Try direct load
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Markdown cleanup (```json ... ```)
    cleaned = content.strip()
    if "```" in cleaned:
        # Pattern to extract content between ```json (optional) and ```
        # We use dotall to match newlines
        match = re.search(r"```(?:\w+)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
             # Manual fallback if regex fails but ``` detected
             if cleaned.startswith("```"):
                 cleaned = cleaned.split("\n", 1)[-1]
             if cleaned.endswith("```"):
                 cleaned = cleaned.rsplit("\n", 1)[0]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
        
    # 3. Last resort: Find outermost braces
    match = re.search(r'(\{.*\})', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 4. Failure
    # Log the content so we can see what went wrong (truncated if too long)
    log_content = content[:1000] + "..." if len(content) > 1000 else content
    logger.error(f"JSON Parse Error. Raw content: {log_content!r}")
    raise RuntimeError("Invalid JSON response from vision provider (Syntax Error)")

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
    
    # Calculate total fat and protein for logic
    total_fat = sum(getattr(i, 'fat_g', 0) or 0 for i in items)
    total_prot = sum(getattr(i, 'protein_g', 0) or 0 for i in items)

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
        bolus=None,
        # We can attach raw totals in comments or logging if needed, 
        # but for now we rely on items having them.
    )


async def _estimate_with_openai(image_bytes: bytes, mime_type: str, hints: dict, settings: Settings) -> dict:
    api_key = settings.vision.openai_api_key
    if not api_key:
        raise RuntimeError("OpenAI API Key not configured")

    client = AsyncOpenAI(api_key=api_key, timeout=settings.vision.timeout_seconds)

    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64_image}"

    user_prompt = _build_user_prompt(hints)

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
        raise RuntimeError(f"OpenAI error: {str(exc)}") from exc

    content = response.choices[0].message.content
    return _safe_json_load(content)


async def _estimate_with_gemini(image_bytes: bytes, mime_type: str, hints: dict, settings: Settings) -> dict:
    api_key = settings.vision.google_api_key
    if not api_key:
        raise RuntimeError("Google API Key not configured")

    genai.configure(api_key=api_key)
    
    generation_config = {
        "temperature": 0.0,
        "max_output_tokens": 4096,
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
    
    # Critical instruction for specific weight scenario
    if hints.get("plate_weight_grams"):
        weight = hints['plate_weight_grams']
        user_prompt += (
            f" I am adding a SPECIFIC ingredient or items to a plate. "
            f"The NET weight of the NEW item(s) I am adding is exactly {weight} grams. "
        )
        
        if hints.get("existing_items"):
            user_prompt += f" The plate ALREADY contains: {hints['existing_items']}. Ignore these items, they are NOT the new addition. "
        else:
            user_prompt += " Ignore other items on the plate that might be visible in the background. "

        user_prompt += f"Focus on identifying the main food item(s) that corresponds to this {weight}g portion."
    
    if hints.get("image_description"):
        user_prompt += f" User description of the food: '{hints['image_description']}'. Use this to identify the item accurately."

    return user_prompt


def calculate_extended_split(
    total_u: float, 
    fat_score: float, 
    slow_score: float,
    items_hints: list[str],
    total_fat_g: float = 0.0,
    total_protein_g: float = 0.0
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

    # High Fat/Protein Logic
    # 20g fat or 25g protein is substantial
    high_fpu = (total_fat_g > 20 or total_protein_g > 25)

    if is_pizza_burger:
        upfront_pct = 0.60
        delay = 150 # 120-180 -> 150 avg
    elif is_creamy_pasta:
        upfront_pct = 0.70
        delay = 105 # 90-120 -> 105
    elif is_dessert:
        upfront_pct = 0.62
        delay = 105 
    elif (fat_score > 0.8 or slow_score > 0.8) or high_fpu:
        # Trigger extended if explicitly high scores or high grams
        upfront_pct = 0.60
        delay = 150
    
    upfront = round(total_u * upfront_pct, 2) # rounding step handled later or here? user said round step 0.05
    # let's do precision 2 here, final rounding in caller
    later = total_u - upfront
    
    return upfront, later, delay
