import logging
import asyncio
import google.generativeai as genai
from typing import Optional, Literal
from app.core import config

logger = logging.getLogger(__name__)

_configured = False

def _configure_genai():
    global _configured
    if _configured:
        return
    
    api_key = config.get_google_api_key()
    if not api_key:
        logger.error("No Google API Key found. AI features disabled.")
        return
        
    genai.configure(api_key=api_key)
    _configured = True

async def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg", api_key: Optional[str] = None) -> str:
    """
    Analyzes an image (food plate) using Gemini Flash (Vision optimized).
    Returns the raw text response (JSON or description).
    """
    if api_key:
        genai.configure(api_key=api_key)
    else:
        _configure_genai()
    
    # Always use Flash for Vision (Cost/Speed efficient)
    primary_model = config.get_gemini_model()
    models_to_try = [primary_model]

    last_error = None

    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            
            # Standard Prompt for Food Analysis
            prompt = (
                "Eres un experto nutricionista diabetológico. Analiza esta imagen.\n"
                "Identifica los alimentos y estima los carbohidratos (en gramos) de cada uno.\n"
                "Devuelve SOLO un JSON con este formato:\n"
                "{\n"
                "  \"alimentos\": [{\"nombre\": \"Patatas\", \"g_carbo\": 30, \"confianza\": \"alta\"}],\n"
                "  \"total_carbs\": 30,\n"
                "  \"consejo\": \"Ojo con la grasa.\"\n"
                "}"
            )
            
            # Prepare content parts
            cookie_picture = {
                'mime_type': mime_type,
                'data': bytes(image_bytes)
            }
            
            # Add Timeout (25s)
            response = await asyncio.wait_for(
                model.generate_content_async([prompt, cookie_picture]),
                timeout=25.0
            )
            return response.text

        except asyncio.TimeoutError:
            logger.error(f"Gemini Vision Timeout ({model_name})")
            last_error = "Timeout"
            # Don't retry on timeout to save time? Or try fallback? Fallback might be faster.
            continue 
        except Exception as e:
            logger.warning(f"Gemini Vision Error ({model_name}): {e}")
            last_error = str(e)
            continue
    
    if last_error == "Timeout":
         return "⚠️ La imagen tardó mucho en procesarse. Intenta con una más pequeña."
         
    logger.error(f"All vision attempts failed. Last error: {last_error}")
    return "Error al analizar la imagen. Verifica tu API Key o intenta de nuevo."
        


async def chat_completion(
    message: str, 
    context: str = None,
    history: list = None, 
    mode: Literal["flash", "pro"] = "flash",
    tools: list = None
) -> dict:
    """
    Chat with the AI.
    Returns: {"text": str, "function_call": dict | None}
    """
    _configure_genai()
    
    # Select Model
    if mode == "pro":
        model_name = config.get_gemini_pro_model() # gemini-3-pro-preview
    else:
        model_name = config.get_gemini_model() # gemini-3-flash-preview
        
    try:
        # System Prompt
        system_instruction = (
            "Eres Bolus AI, un asistente experto en diabetes tipo 1. "
            "Tu objetivo es ayudar al usuario a gestionar su glucosa sin sustituir al médico. "
            "Sé conciso, empático y basa tus respuestas en datos. "
            "No inventes dosis ni hagas cálculos a mano: usa solo las herramientas disponibles para cualquier cálculo. "
            "Si no sabes algo, dilo."
        )

        if context:
            system_instruction += f"\n\nDATOS EN TIEMPO REAL:\n{context}"
        
        full_prompt = f"{system_instruction}\n\nUser: {message}"

        # Initialize Model with Tools if provided
        model = genai.GenerativeModel(model_name, tools=tools)
        
        # Add Timeout (20s) - Prevent infinite typing state
        response = await asyncio.wait_for(
            model.generate_content_async(full_prompt), 
            timeout=20.0
        )
        
        # Parse Response safely
        res_text = ""
        fn_call = None
        
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    res_text += part.text
                if part.function_call:
                    fn_call = {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args)
                    }
        
        # Fallack if simple text extraction fails but we have no function call (safety)
        if not res_text and not fn_call:
             try:
                 res_text = response.text
             except:
                 pass

        return {
            "text": res_text,
            "function_call": fn_call
        }
    
    except asyncio.TimeoutError:
        logger.error(f"Gemini Chat TIMEOUT ({mode})")
        return {"text": "⏳ El cerebro de la IA está lento. Intenta de nuevo.", "function_call": None}
        
    except Exception as e:
        logger.error(f"Gemini Chat Error ({mode}): {e}")
        return {"text": "Lo siento, tuve un problema pensando. ¿Puedes repetirlo?", "function_call": None}
