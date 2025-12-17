
import logging
from typing import Optional, Dict, Any
from sqlalchemy import text
from app.core.db import _async_engine
from app.core.security import hash_password

logger = logging.getLogger(__name__)

async def init_auth_db():
    """Calculates/Creates the users table if it doesn't exist and seeds admin."""
    if not _async_engine:
        logger.warning("Auth DB init skipped (in-memory mode)")
        return

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        needs_password_change BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    seed_sql = """
    INSERT INTO users (username, password_hash, role, needs_password_change)
    VALUES (:username, :pwd, :role, :change)
    ON CONFLICT (username) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        role = EXCLUDED.role;
    """

    async with _async_engine.begin() as conn:
        await conn.execute(text(create_table_sql))
        
        # Seed 'admin'
        # Default password 'admin123'
        pwd = hash_password("admin123")
        await conn.execute(text(seed_sql), {
            "username": "admin",
            "pwd": pwd,
            "role": "admin",
            "change": True
        })
        logger.info("Auth DB initialized (users table checked/seeded).")

async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    if not _async_engine:
        # Fallback? No, strictly require DB for persistence now.
        # Check seed memory?
        return None

    query = text("SELECT * FROM users WHERE username = :username")
    async with _async_engine.connect() as conn:
        result = await conn.execute(query, {"username": username})
        row = result.fetchone()
        if row:
            return dict(row._mapping)
    return None

async def update_user(username: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not _async_engine:
        return None
    
    set_clauses = []
    params = {"username": username}
    
    for k, v in updates.items():
        set_clauses.append(f"{k} = :{k}")
        params[k] = v
        
    if not set_clauses:
        return await get_user_by_username(username)
        
    sql = f"""
        UPDATE users
        SET {', '.join(set_clauses)}
        WHERE username = :username
        RETURNING *
    """
    
    async with _async_engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        row = result.fetchone()
        if row:
            return dict(row._mapping)
    return None

async def create_user(username: str, password_hash: str, role: str = "user") -> Optional[Dict[str, Any]]:
    if not _async_engine:
        return None
        
    sql = """
        INSERT INTO users (username, password_hash, role, needs_password_change)
        VALUES (:username, :pwd, :role, :change)
        RETURNING *
    """
    async with _async_engine.begin() as conn:
        try:
            result = await conn.execute(text(sql), {
                "username": username,
                "pwd": password_hash,
                "role": role,
                "change": True
            })
            row = result.fetchone()
            if row:
                return dict(row._mapping)
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None
    return None
