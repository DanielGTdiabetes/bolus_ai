import logging
import json
import asyncio
from typing import Optional, List, Any, Dict
from dataclasses import dataclass

import google.generativeai as genai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core import config
from app.bot.state import health
from app.bot.capabilities.registry import build_registry, Permission
from app.bot.tools import execute_tool, ToolError
from app.bot.llm.prompt import get_system_prompt
from app.bot.llm.memory import memory

logger = logging.getLogger(__name__)

@dataclass
class BotReply:
    text: str
    buttons: Optional[List[List[InlineKeyboardButton]]] = None
    pending_action: Optional[Dict[str, Any]] = None

def _is_admin(user_id: int) -> bool:
    allowed = config.get_allowed_telegram_user_id()
    return allowed is not None and user_id == allowed

from google.ai.generativelanguage_v1beta.types import content

def to_gemini_schema(json_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursive conversion from standard JSON Schema (lowercase) to Gemini Schema (Enums/Uppercase).
    Reference: google.ai.generativelanguage_v1beta.types.Schema
    """
    # 1. Type Mapping
    original_type = json_schema.get("type", "object")
    type_map = {
        "string": content.Type.STRING,
        "number": content.Type.NUMBER,
        "integer": content.Type.INTEGER,
        "boolean": content.Type.BOOLEAN,
        "array": content.Type.ARRAY,
        "object": content.Type.OBJECT,
    }
    
    # Defaults to OBJECT if unknown, or STRING if primitive context implied but missing
    gemini_type = type_map.get(original_type, content.Type.OBJECT)

    result = {
        "type": gemini_type,
        "nullable": json_schema.get("nullable", False),
    }

    # 2. Descriptions (critical)
    if "description" in json_schema:
        result["description"] = json_schema["description"]
    
    # 3. Enum
    if "enum" in json_schema:
        result["enum"] = json_schema["enum"]

    # 4. Properties (for Object)
    if "properties" in json_schema:
        props = {}
        for k, v in json_schema["properties"].items():
            props[k] = to_gemini_schema(v)
        result["properties"] = props
        
    # 5. Required
    if "required" in json_schema:
        result["required"] = json_schema["required"]
        
    # 6. Items (for Array)
    if "items" in json_schema:
        result["items"] = to_gemini_schema(json_schema["items"])

    return result

def _map_tool_to_gemini(tool_def) -> Dict[str, Any]:
    try:
        # Convert Pydantic/JSON schema to Gemini Schema Node
        parameters_node = to_gemini_schema(tool_def.input_schema)
        
        return genai.types.FunctionDeclaration(
            name=tool_def.name,
            description=tool_def.description,
            parameters=parameters_node
        )
    except Exception as e:
        logger.warning(f"Failed to map tool {tool_def.name} to Gemini: {e}")
        return None

async def handle_text(username: str, chat_id: int, user_text: str, context_data: Dict[str, Any]) -> BotReply:
    """
    Main Router: Text -> LLM -> Tools -> Reply
    """
    user_id = chat_id # Assuming 1:1 map for simplicity in this context
    
    # 1. Config & Registry
    api_key = config.get_google_api_key()
    if not api_key:
        return BotReply("⚠️ Error: API Key de IA no configurada.")
    
    genai.configure(api_key=api_key)
    registry = build_registry()
    
    # 2. Filter Tools
    allowed_tools = []
    for tool in registry.tools:
        if tool.permission == Permission.admin_only and not _is_admin(user_id):
            continue
        allowed_tools.append(tool)
    
    gemini_tools = []
    for t in allowed_tools:
        converted = _map_tool_to_gemini(t)
        if converted:
            gemini_tools.append(converted)
            
    if not gemini_tools:
        gemini_tools = None # Pass None if empty list to avoid API error
    
    # 3. Build Prompt
    system_prompt = get_system_prompt()
    
    # Add Context Validation to System Prompt
    context_str = json.dumps(context_data, indent=2, default=str)
    system_prompt += f"\n\nCONTEXTO ACTUAL (JSON):\n{context_str}\n"

    # 4. Chat History
    history = memory.get_context(chat_id)
    # Convert to Gemini format
    # user -> user, assistant -> model
    # tool -> function_response (handled in loop, but here is past conversation)
    # Gemini 1.5/Flash history structure is slightly complex with Function calls history. 
    # For simplicity, we will append history as text in the prompt or use simple turn-based if no tools involved previously.
    # To properly support multi-turn with tools in history, we'd need to store function_call/response objects.
    # "memory.py" stores simple strings. We will inject them as "Previous conversation" block to avoid validation errors.
    
    conversation_block = ""
    if history:
        conversation_block = "\nHISTORIAL RECIENTE:\n"
        for m in history:
            role = "User" if m["role"] == "user" else "Assistant"
            conversation_block += f"{role}: {m['content']}\n"
        system_prompt += conversation_block

    # 5. Initialize Model
    model_name = config.get_gemini_model()
    model = genai.GenerativeModel(model_name, tools=gemini_tools)
    
    # 6. Loop (max 2 rounds)
    # We use chat session for the loop
    chat = model.start_chat(enable_automatic_function_calling=False) # We handle calling manually for control
    
    # Initial Message
    # We combine system prompt + User text because `start_chat` history is empty initially.
    # Actually, system_instruction should be set on model init? 
    # Gemini python sdk: model = genai.GenerativeModel(..., system_instruction=...)
    model = genai.GenerativeModel(model_name, tools=gemini_tools, system_instruction=system_prompt)
    chat = model.start_chat()

    reply_text = "..."
    final_buttons = None
    
    # Track execution for UI
    last_bolus_result = None
    last_bolus_args = {}

    try:
        # Round 0: Send User Text
        response = await chat.send_message_async(user_text)
        
        # Round 1 & 2: Check for function calls
        for _ in range(2):
            call = None
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        call = part.function_call
                        break
            
            if not call:
                break # No tool needed
            
            # Execute Tool
            tool_name = call.name
            tool_args = dict(call.args)
            health.record_llm(True, tools_used=[tool_name])
            
            tool_res = await execute_tool(tool_name, tool_args)
            
            # Capture specific results for UI
            if tool_name == "calculate_bolus" and not isinstance(tool_res, ToolError):
                last_bolus_result = tool_res
                last_bolus_args = tool_args

            # Serialize result
            if isinstance(tool_res, ToolError):
                tool_output = f"Error: {tool_res.message}"
                health.record_llm(False, error=tool_res.message)
            else:
                if hasattr(tool_res, "model_dump"):
                    tool_output = json.dumps(tool_res.model_dump())
                elif hasattr(tool_res, "dict"):
                    tool_output = json.dumps(tool_res.dict())
                else:
                    tool_output = str(tool_res)

            # Feed back to model
            response = await chat.send_message_async(
                genai.protos.Content(
                    parts=[genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=tool_name,
                            response={"result": tool_output}
                        )
                    )]
                )
            )

        # Final Response extraction
        reply_text = response.text
        
        # Add Buttons if we calculated a bolus
        if last_bolus_result and last_bolus_result.units > 0:
            import uuid
            req_id = str(uuid.uuid4())[:8]
            final_buttons = [
                [
                    InlineKeyboardButton(f"✅ Poner {last_bolus_result.units} U", callback_data=f"accept|{req_id}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel|{req_id}")
                ]
            ]
            
            # Construct the action for snapshot
            carbs = float(last_bolus_args.get("carbs", 0) or 0)
            
            pending_action_data = {
                "id": req_id,
                "type": "bolus",
                "units": last_bolus_result.units,
                "carbs": carbs,
                "notes": "AI Suggestion",
                "timestamp": 0 # filled safely by service
            }
            return BotReply(reply_text, final_buttons, pending_action=pending_action_data)

    except Exception as e:

        logger.error(f"Router LLM Error: {e}")
        health.record_llm(False, error=str(e))
        return BotReply("😵‍💫 Mi cerebro está desconectado. Intenta comandos directos.")

    # Memory Update
    memory.add(chat_id, "user", user_text)
    memory.add(chat_id, "assistant", reply_text)
    
    return BotReply(reply_text, final_buttons)
