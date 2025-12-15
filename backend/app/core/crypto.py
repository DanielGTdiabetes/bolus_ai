
import os
import base64
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet_instance = None

def get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance:
        return _fernet_instance

    key = os.environ.get("APP_SECRET_KEY")
    
    if not key:
        # Check if we are in testing mode (usually via env var or just lack of production env)
        # But instructions say: "En producción: error claro. En tests: permitir clave fija mockeada."
        # We'll rely on the caller/test setup to set APP_SECRET_KEY.
        # However, for local dev convenience if not set, we might warn or fail.
        # User requirement: "Si APP_SECRET_KEY no está configurada: En producción: error claro"
        # We assume production if not explicitly "TESTING".
        if os.environ.get("ENV") == "TEST" or os.environ.get("TESTING"):
             # Mock key for tests
             key = Fernet.generate_key().decode()
        else:
             msg = "APP_SECRET_KEY is not set. Nightscout secrets encryption requires a Fernet key (32 url-safe base64-encoded bytes)."
             logger.critical(msg)
             # Raising generic error might crash execution during module import if called at top level
             # Better to raise only when used.
             raise ValueError(msg)

    try:
        _fernet_instance = Fernet(key)
        return _fernet_instance
    except Exception as e:
        logger.critical(f"Invalid APP_SECRET_KEY: {e}")
        raise

def encrypt(text: str) -> str:
    f = get_fernet()
    return f.encrypt(text.encode("utf-8")).decode("utf-8")

def decrypt(token: str) -> str:
    f = get_fernet()
    return f.decrypt(token.encode("utf-8")).decode("utf-8")
