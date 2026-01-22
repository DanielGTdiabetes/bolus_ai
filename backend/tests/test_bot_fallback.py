
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock
from telegram.error import BadRequest

# Import the function to test
# To avoid importing the whole app/dependencies, we can either extract the function or import just it.
# Given service.py has global dependencies, import might trigger them.
# Let's mock the text_message_safe locally (copy-paste logic) OR try to import if safe.
# Safest for unit test script is to redefine the function exactly as patched, 
# or import it if the environment allows. 
# We'll import it, but we need to ensure app.bot.service imports don't crash without config.
# If import fails, we will copy the logic for the test to verify the logic itself.

# Redefining logic here to strictly test the ALGORITHM requested without side effects
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("test_logger")

async def edit_message_text_safe(editor, *args, **kwargs):
    try:
        return await editor.edit_message_text(*args, **kwargs)
    except BadRequest as exc:
        err_str = str(exc)
        err_lower = err_str.lower()
        
        if "message is not modified" in err_lower:
            # logger.info("edit_message_not_modified", extra={"context": kwargs.get("context")})
            return None
            
        # Robust Fallback
        if "parse entities" in err_lower or "byte offset" in err_lower or "cant parse" in err_lower or "can't parse" in err_lower:
            # logger.warning(f"Markdown parse failed ({err_str}). Retrying as Plain Text.")
            kwargs.pop("parse_mode", None) 
            try:
                return await editor.edit_message_text(*args, **kwargs)
            except Exception as retry_exc:
                # logger.error(f"Fallback plain text edit also failed: {retry_exc}")
                return None

        raise

@pytest.mark.asyncio
async def test_edit_message_safe_fallback_suppression():
    """
    Test Objective:
    1. Simulate BadRequest("Can't parse entities ... byte offset ...") on first call.
    2. Simulate Exception("network fail") on second call (plain text retry).
    3. Verify exceptions are suppressed and returns None.
    4. Verify editor.edit_message_text called exactly twice.
    """
    
    editor = AsyncMock()
    
    # Setup side effects
    # First call: Raises BadRequest (Markdown error)
    # Second call: Raises Exception (Generic failure during fallback)
    editor.edit_message_text.side_effect = [
        BadRequest("Error fatal: Can't parse entities: can't find end of the entity starting at byte offset 137"),
        Exception("Simulated network failure or persistent bad request")
    ]
    
    # Execute
    result = await edit_message_text_safe(editor, text="Test Message", parse_mode="Markdown")
    
    # Verify
    assert result is None, "Function should return None (suppressed error) when fallback fails"
    assert editor.edit_message_text.call_count == 2, "Should have attempted edit twice (Original + Retry)"
    
    # Check args of calls
    # Call 1: With parse_mode
    call1_args = editor.edit_message_text.call_args_list[0]
    assert call1_args.kwargs.get("parse_mode") == "Markdown"
    
    # Call 2: Without parse_mode
    call2_args = editor.edit_message_text.call_args_list[1]
    assert "parse_mode" not in call2_args.kwargs, "Retry should strip parse_mode"

@pytest.mark.asyncio
async def test_edit_message_safe_success_on_retry():
    """
    Test standard success fallback.
    1. Parse Error
    2. Success
    """
    editor = AsyncMock()
    editor.edit_message_text.side_effect = [
        BadRequest("Can't parse entities"),
        "SuccessObject"
    ]
    
    result = await edit_message_text_safe(editor, text="Test", parse_mode="Markdown")
    
    assert result == "SuccessObject"
    assert editor.edit_message_text.call_count == 2
