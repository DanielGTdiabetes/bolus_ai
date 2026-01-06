from contextvars import ContextVar
from typing import Optional

# Almacena el ID de usuario (username) del contexto actual del bot
# Esto permite que las herramientas (tools) sepan a qué usuario pertenecen
# sin necesidad de pasar el argumento explícitamente en cada función.
bot_user_context: ContextVar[Optional[str]] = ContextVar("bot_user_context", default=None)
