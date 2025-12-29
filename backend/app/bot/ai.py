import logging
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

async def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Analyzes an image (food plate) using Gemini Flash (Vision optimized).
    Returns the raw text response (JSON or description).
    """
    _configure_genai()
    
    # Always use Flash for Vision (Cost/Speed efficient)
    model_name = config.get_gemini_model() # Default: gemini-3.0-flash
    
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
            'data': image_bytes
        }
        
        response = await model.generate_content_async([prompt, cookie_picture])
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini Vision Error: {e}")
        return "Error al analizar la imagen. Inténtalo de nuevo."

async def chat_completion(
    message: str, 
    history: list = None, 
    mode: Literal["flash", "pro"] = "flash"
) -> str:
    """
    Chat with the AI.
    - mode='flash': Fast, daily queries.
    - mode='pro': Deep reasoning, medical doubts.
    """
    _configure_genai()
    
    # Select Model
    if mode == "pro":
        model_name = config.get_gemini_pro_model() # gemini-3.0-pro
    else:
        model_name = config.get_gemini_model() # gemini-3.0-flash
        
    try:
        # System Prompt (Injected if history is empty or via system instruction if supported)
        # Gemini 1.5+ supports system_instruction arg
        system_instruction = (
            "Eres Bolus AI, un asistente experto en diabetes tipo 1. "
            "Tu objetivo es ayudar al usuario a gestionar su glucosa sin sustituir al médico. "
            "Sé conciso, empático y basa tus respuestas en datos. "
            "Si no sabes algo, dilo."
        )
        
        model = genai.GenerativeModel(
            model_name,
            system_instruction=system_instruction
        )
        
        # TODO: Map custom history format to Gemini format if needed
        # For now, simple generation
        chat = model.start_chat(history=[]) # Stateless for now or implementing history mapping later
        
        response = await chat.send_message_async(message)
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini Chat Error ({mode}): {e}")
        return "Lo siento, tuve un problema pensando. ¿Puedes repetirlo?"
