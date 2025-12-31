import logging
import json
import asyncio
from datetime import datetime
from typing import Optional, List, Any, Dict
from dataclasses import dataclass

import google.generativeai as genai
import google.ai.generativelanguage as glm
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core import config
from app.bot.state import health
from app.bot.tools import execute_tool, ToolError
from app.bot.llm.prompt import get_system_prompt
from app.bot.llm.memory import memory
from app.bot import context_builder
from app.bot import proactive_rules as rules

logger = logging.getLogger(__name__)

@dataclass
class BotReply:
    text: str
    buttons: Optional[List[List[InlineKeyboardButton]]] = None
    pending_action: Optional[Dict[str, Any]] = None

def _is_admin(user_id: int) -> bool:
    allowed = config.get_allowed_telegram_user_id()
    return allowed is not None and user_id == allowed

def to_gemini_schema(json_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursive conversion from standard JSON Schema (lowercase) to Gemini Schema (Enums/Uppercase).
    Reference: google.ai.generativelanguage_v1beta.types.Schema
    """
    # 1. Type Mapping
    original_type = json_schema.get("type", "object")
    # Google API expects uppercased strings for type in JSON definition
    type_map = {
        "string": "STRING",
        "number": "NUMBER",
        "integer": "INTEGER",
        "boolean": "BOOLEAN",
        "array": "ARRAY",
        "object": "OBJECT",
    }
    
    # Defaults to OBJECT if unknown
    gemini_type = type_map.get(original_type, "OBJECT")

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
    
    # Lazy import to avoid circular dependency
    from app.bot.capabilities.registry import build_registry, Permission
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
                glm.Content(
                    parts=[glm.Part(
                        function_response=glm.FunctionResponse(
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

async def handle_event(username: str, chat_id: int, event_type: str, payload: Dict[str, Any]) -> Optional[BotReply]:
    """
    Handle proactive events via LLM.
    Returns BotReply if message should be sent, None otherwise.
    """
    # Mark as seen immediately for observability
    health.mark_event_seen(event_type)

    # 0. Check Heuristic Hint (Pre-calculated reason to skip OR proceed without LLM)
    if payload.get("reason_hint"):
        reason = payload["reason_hint"]
        
        # Special Case: Eligible Candidate for Combo Followup -> Proceed to Manual Construction
        if reason == "eligible_candidate" and event_type == "combo_followup":
            pass
        # Special Case: Trend Alert -> Check Silencing Rules Later
        elif event_type == "trend_alert":
            pass
        else:
            # Default behavior: hint means "skip and log this reason"
            health.record_event(event_type, False, reason)
            logger.info(f"Event {event_type} skipped by heuristic: {reason}")
            return None

    # 0.5. Guard: Premeal Intent Check
    if event_type == "premeal":
        trigger = payload.get("trigger", "auto")
        intent = payload.get("intent")
        
        # If manual or explicit intent, pass
        if trigger == "manual" or intent == "meal_check":
            pass
        else:
            # Check Meal Windows (Local Time)
            # TODO: Load from proactively.premeal.meal_windows in settings if available
            now = datetime.now()
            # Default Windows (Lunch: 12:30-15:30, Dinner: 19:30-22:00)
            windows = [
                (12, 30, 15, 30),
                (19, 30, 22, 00)
            ]
            
            in_window = False
            for (sh, sm, eh, em) in windows:
                start_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                end_dt = now.replace(hour=eh, minute=em, second=0, microsecond=0)
                if start_dt <= now <= end_dt:
                    in_window = True
                    break
            
            if not in_window:
                health.record_event(event_type, False, "silenced_no_meal_intent")
                logger.info(f"Event {event_type} silenced: No Meal Intent (Auto outside window)")
                return None

    # 1. Check Noise Rules
    silence_res = rules.check_silence(event_type)
    if silence_res.should_silence:
        # Check if we should override silence (e.g. high urgency), but for combo we respect it.
        # Construct detailed reason
        detailed_reason = silence_res.reason
        if event_type == "combo_followup":
            detailed_reason = f"silenced_recent(combo_followup, remaining={silence_res.remaining_min}, window={silence_res.window_min})"
            
        health.record_event(
            event_type, 
            False, 
            detailed_reason,
            cooldown_min=silence_res.remaining_min,
            cooldown_details={
                "event_type": event_type,
                "window_min": silence_res.window_min,
                "remaining_min": silence_res.remaining_min
            }
        )
        logger.info(f"Event {event_type} silenced: {detailed_reason}")
        return None

    # 2. Manual Construction for Specific Events (Bypass LLM)
    if event_type == "morning_summary":
        mode = payload.get("mode", "full")  # full or alerts
        range_hours = payload.get("range_hours", 8)
        highlights = payload.get("highlights", [])
        
        # Alerts Mode (we only reach here if there are highlights or we force send, proactiv.py handles the "no events" case usually)
        if mode == "alerts":
            if not highlights:
                 return BotReply(text="Sin eventos.") # Should limit reach
                 
            text = f"⚠️ **Resumen de Alertas ({range_hours}h)**\n\n"
            for h in highlights:
                text += f"- {h}\n"
            return BotReply(text=text)
            
        # Full Mode
        curr = payload.get("bg", 0)
        min_bg = payload.get("min_bg", 0)
        max_bg = payload.get("max_bg", 0)
        hypos = payload.get("hypo_count", 0)
        hypers = payload.get("hyper_count", 0)
        
        stat_line = f"• Rango: {min_bg:.0f} - {max_bg:.0f} mg/dL\n"
        stat_line += f"• Hipos: {hypos} | Hipers: {hypers}"
        
        text = f"☀️ **Resumen Matutino ({range_hours}h)**\n\n"
        text += f"Glucosa actual: **{curr:.0f}** mg/dL\n\n"
        text += f"{stat_line}\n\n"
        
        if highlights:
            text += "**Eventos destacados:**\n"
            # Show max 3 highlights
            for h in highlights[:3]:
                 text += f"{h}\n"
            if len(highlights) > 3:
                 text += f"... y {len(highlights)-3} más.\n"
        
        # Basal placeholder (fetched separate or not included in this MVP)
        # We stick to available payload data to be safe.
        
        return BotReply(text=text)

    if event_type == "trend_alert":
        # Check Noise Rules first (cooldown)
        silence_res = rules.check_silence(event_type)
        if silence_res.should_silence:
            detailed_reason = f"silenced_recent({event_type}, remaining={silence_res.remaining_min}, window={silence_res.window_min})"
            health.record_event(event_type, False, detailed_reason)
            return None
            
        # Construct Message (Determinista)
        curr = payload.get("current_bg", 0)
        direction = payload.get("direction", "stable")
        slope = payload.get("slope", 0.0)
        delta_total = payload.get("delta_total", 0)
        window = payload.get("window_minutes", 30)
        delta_arrow = payload.get("delta_arrow", f"{delta_total:+}")
        
        micro_u = payload.get("suggested_micro_u")
        buttons = []
        
        if direction == "rise":
             text = (
                 f"📈 **Subida rápida sin comida/bolo reciente**\n\n"
                 f"Ahora: **{curr}** mg/dL ({delta_arrow})\n"
                 f"Últimos {window} min: +{abs(delta_total)} (≈ {slope:+.2f} mg/dL/min)\n"
             )
             if micro_u:
                 text += f"\n💡 **Sugerencia:** Un micro-bolo de **{micro_u} U** podría aplanar la curva."
                 buttons.append([InlineKeyboardButton("💉 Calcular Corrección", callback_data="chat_bolus_edit_0")])
                 
             text += f"\n\n¿Ha habido estrés, fallo de infusión o comida no registrada?"
             reason = f"sent_trend_rise(slope={slope}, delta={delta_total}, window={window}, micro={micro_u})"
        else:
             text = (
                 f"📉 **Bajada rápida sin comida/bolo reciente**\n\n"
                 f"Ahora: **{curr}** mg/dL ({delta_arrow})\n"
                 f"Últimos {window} min: {delta_total} (≈ {slope:+.2f} mg/dL/min)\n\n"
                 f"Si notas síntomas, revisa y actúa según tu plan."
             )
             reason = f"sent_trend_drop(slope={slope}, delta={delta_total}, window={window})"
        
        # Log success reason
        health.record_event(event_type, True, reason)
        
        return BotReply(text=text, buttons=buttons if buttons else None)

    if event_type == "combo_followup":
        tid = payload.get("treatment_id", "unknown")
        bolus_at = payload.get("bolus_at", "?")
        units = payload.get("bolus_units", "?")
        
        # Context
        bg = payload.get("bg")
        trend = payload.get("trend", "Flat")
        delta = payload.get("delta", 0)
        
        # Time Formatting
        try:
            from datetime import datetime
            import zoneinfo
            dt = datetime.fromisoformat(bolus_at.replace("Z", "+00:00"))
            tz = zoneinfo.ZoneInfo("Europe/Madrid")
            dt_local = dt.astimezone(tz)
            time_str = dt_local.strftime("%H:%M")
        except Exception:
            time_str = bolus_at

        # Decision Logic (Case 4)
        text = ""
        buttons = []
        
        is_hypo_risk = (bg is not None and bg < 90) or (delta and delta < -5)
        is_rising = (bg is not None and bg > 150) and (delta and delta > 3)
        
        if is_hypo_risk:
            # Scenario B: Critical/Caution
            text = (
                f"⚠️ **CUIDADO (Bolo Extendido)**\n\n"
                f"Toca la 2ª parte del bolo ({units} U), pero estás en **{bg} mg/dL** y bajando ({delta}).\n"
                f"¿Prefieres posponerlo o cancelar?"
            )
            buttons = [
                [InlineKeyboardButton("⏰ Posponer 30m", callback_data=f"combo_later|{tid}")],
                [InlineKeyboardButton("❌ Cancelar dosis", callback_data=f"combo_no|{tid}")]
            ]
        elif is_rising:
            # Scenario A: Early Rise
            text = (
                f"📈 **Nota (Bolo Extendido)**\n\n"
                f"Faltan unos minutos para la 2ª parte ({units} U), pero ya estás subiendo (**{bg}** {trend}).\n"
                f"¿Quieres adelantar el registro ahora?"
            )
            buttons = [
                [InlineKeyboardButton("💉 Registrar AHORA", callback_data=f"combo_yes|{tid}")],
                [InlineKeyboardButton("⏰ Esperar", callback_data=f"combo_later|{tid}")]
            ]
        else:
            # Scenario C: Stable / Normal
            text = (
                f"🔄 **Seguimiento Bolo Extendido**\n\n"
                f"Detectado bolo de **{units} U** a las {time_str}.\n"
                f"Es hora de la 2ª parte. Estás en **{bg or '?'}** {trend}.\n"
                f"¿Registramos?"
            )
            buttons = [
                [InlineKeyboardButton("💉 Registrar 2ª parte", callback_data=f"combo_yes|{tid}")],
                [InlineKeyboardButton("⏰ +30 min", callback_data=f"combo_later|{tid}"), 
                 InlineKeyboardButton("❌ No", callback_data=f"combo_no|{tid}")]
            ]
        
        # Logic Record
        reason = "sent_combo_risk" if is_hypo_risk else ("sent_combo_rise" if is_rising else "sent_combo_normal")
        health.record_event(event_type, True, reason)
        rules.mark_event_sent(event_type)
        
        return BotReply(text=text, buttons=buttons)

    if event_type == "basal":
        # 1. Check Persistence Blocking
        p_status = payload.get("persistence_status")
        if p_status == "blocked":
            reason = payload.get("persistence_reason", "heuristic_persistence_blocked")
            health.record_event(event_type, False, reason)
            return None

        # 2. Check Logic Status
        status_dict = payload.get("basal_status", {})
        status = status_dict.get("status", "unknown")
        
        if status == "taken_today":
            health.record_event(event_type, False, "heuristic_already_taken")
            return None
        
        if status == "not_due_yet":
             health.record_event(event_type, False, "heuristic_not_due")
             return None

        # Allow 'late' or 'due_soon' (if enabled)
        if status not in ["late", "due_soon"]:
             # E.g. insufficient_history
             health.record_event(event_type, False, f"heuristic_status_{status}")
             return None

        # 3. Check System Cooldown / Quiet Hours
        silence_res = rules.check_silence(event_type)
        if silence_res.should_silence:
            health.record_event(event_type, False, f"silenced_recent({event_type}, remaining={silence_res.remaining_min})")
            return None

        # Format Message
        text = "💉 **Basal**\n\n¿Te has puesto la basal de hoy?"
        
        buttons = [
            [InlineKeyboardButton("✅ Registrar", callback_data="basal_yes")],
            [InlineKeyboardButton("⏰ 15 min", callback_data="basal_later"),
             InlineKeyboardButton("❌ No hoy", callback_data="basal_no")]
        ]

        health.record_event(event_type, True, "sent_basal_reminder")
        return BotReply(text=text, buttons=buttons)

    # 3. Build Context (For LLM)
    ctx = await context_builder.build_context(username, chat_id)
    
    # 3. Build Prompt
    # Special system prompt or injected instruction
    system_prompt = get_system_prompt()
    
    event_prompt = (
        f"EVENTO AUTOMÁTICO: {event_type}\n"
        f"DATOS: {json.dumps(payload, indent=2)}\n\n"
        "INSTRUCCIONES:\n"
        "- Decide si es necesario hablar con el usuario.\n"
        "- Sé muy breve y directo.\n"
        "- Usa tono útil y amigable.\n"
        "- Si el usuario ya sabe esto o no es importante, responde 'SKIP'.\n"
        "- Si necesitas acción (ej. bolo), sugiérelo pero NO uses herramientas todavía (solo texto).\n"
        "- Contexto actual adjunto arriba.\n"
    )
    
    # 4. LLM Call (One Shot)
    # We use a simple generation here, no tool loop for simplicity unless needed?
    # Actually, the user requirement implies "router decides". It might want to use tools?
    # "El router decide... si pedir acción".
    # Let's use the same `genai` setup but single prompt.
    
    api_key = config.get_google_api_key()
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    model_name = config.get_gemini_model()
    model = genai.GenerativeModel(model_name) # No tools needed for decision phase usually, or we can add them.
    
    # Combine prompts
    full_prompt = f"{system_prompt}\n\nCONTEXTO:\n{json.dumps(ctx, default=str)}\n\n{event_prompt}"
    
    try:
        response = await model.generate_content_async(full_prompt)
        text = response.text.strip()
        
        if text == "SKIP" or not text:
             health.record_event(event_type, False, "skipped_by_llm")
             return None
             
        # Mark as sent
        rules.mark_event_sent(event_type)
        health.record_event(event_type, True, "sent")
        
        # Add to memory so chat knows
        memory.add(chat_id, "system", f"Event triggered: {event_type}")
        memory.add(chat_id, "assistant", text)
        
        return BotReply(text)

    except Exception as e:
        logger.error(f"Event LLM Error: {e}")
        health.record_event(event_type, False, f"error: {e}")
        return None
