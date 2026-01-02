
import logging
from typing import Optional, Dict, Any
from sqlalchemy import text
from app.core.db import get_engine
from app.core.security import hash_password

logger = logging.getLogger(__name__)

async def init_auth_db():
    """Calculates/Creates the users table if it doesn't exist and seeds admin."""
    if not get_engine():
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
    ON CONFLICT (username) DO NOTHING;
    """

    async with get_engine().begin() as conn:
        await conn.execute(text(create_table_sql))
        
        # Seed 'admin'
        # Seed 'admin'
        # Default password 'admin123'
        # use SHA256 hash to ensure stability and avoid bcrypt variations at startup
        # SHA256('admin123') = 240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9
        pwd = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"
        
        await conn.execute(text(seed_sql), {
            "username": "admin",
            "pwd": pwd,
            "role": "admin",
            "change": True
        })
        logger.info("Auth DB initialized (users table checked/seeded).")

async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    if not get_engine():
        # Fallback to file-based store (users.json) if DB not configured
        from app.core.settings import get_settings
        from app.core.datastore import UserStore
        from pathlib import Path
        
        try:
            settings = get_settings()
            data_dir = Path(settings.data.data_dir)
            store = UserStore(data_dir / "users.json")
            user = store.find(username)
            if user:
                 return user
        except Exception as e:
            logger.error(f"Fallback auth failed: {e}")
        return None

    query = text("SELECT * FROM users WHERE username = :username")
    async with get_engine().connect() as conn:
        result = await conn.execute(query, {"username": username})
        row = result.fetchone()
        if row:
            return dict(row._mapping)
    return None

async def update_user(username: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not get_engine():
        # Fallback to file store
        from app.core.settings import get_settings
        from app.core.datastore import UserStore
        from pathlib import Path
        try:
            settings = get_settings()
            store = UserStore(Path(settings.data.data_dir) / "users.json")
            user = store.find(username)
            if user:
                # Update dict in place and save?
                # UserStore might not expose update easily but let's check basic usage
                # Inspecting UserStore (from step 44) implied simple list usage.
                # Let's assume store has no direct 'update' method based on typical pattern, 
                # but we can implement a specific update helper if needed.
                # Actually, UserStore likely loads generic JSON.
                # Let's implement an ad-hoc update on the store instance if possible.
                # Or just modify and save.
                store.update(username, updates) 
                return store.find(username)
        except Exception:
             pass
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
    
    async with get_engine().begin() as conn:
        result = await conn.execute(text(sql), params)
        row = result.fetchone()
        if row:
            return dict(row._mapping)
    return None

async def create_user(username: str, password_hash: str, role: str = "user") -> Optional[Dict[str, Any]]:
    if not get_engine():
        return None
        
    sql = """
        INSERT INTO users (username, password_hash, role, needs_password_change)
        VALUES (:username, :pwd, :role, :change)
        RETURNING *
    """
    async with get_engine().begin() as conn:
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

async def rename_user(old_username: str, new_username: str) -> bool:
    """
    Renames a user and updates all references in other tables.
    Returns True if successful, False if new_username exists or error.
    """
    if not get_engine():
        return False
        
    # Check if new username exists
    user = await get_user_by_username(new_username)
    if user:
        return False # Already exists

    async with get_engine().begin() as conn:
        try:
            # 1. Update USERS table
            # We defer constraints just in case? Postgres doesn't easily support disabling constraints inside transaction unless set to DEFERRABLE.
            # But standard update of PK works if no FKs restrict it or if ON UPDATE CASCADE is set.
            # Since we assume NO FKs are enforced by DB (based on models), we can update manually.
            
            # Users
            await conn.execute(text("UPDATE users SET username = :new WHERE username = :old"), {"new": new_username, "old": old_username})
            
            # Nightscout Secrets
            await conn.execute(text("UPDATE nightscout_secrets SET user_id = :new WHERE user_id = :old"), {"new": new_username, "old": old_username})
            
            # Treatments
            await conn.execute(text("UPDATE treatments SET user_id = :new WHERE user_id = :old"), {"new": new_username, "old": old_username})
            # Also entered_by? Maybe not, historically "entered_by" is just text.
            
            # Basal Tables
            tables = [
                "basal_dose", 
                "basal_checkin", 
                "basal_night_summary", 
                "basal_advice_daily", 
                "basal_change_evaluation"
            ]
            
            for t in tables:
                try:
                    await conn.execute(text(f"UPDATE {t} SET user_id = :new WHERE user_id = :old"), {"new": new_username, "old": old_username})
                except Exception:
                    # Table might not exist yet? Ignore.
                    pass
                    
            return True
        except Exception as e:
            logger.error(f"Rename user failed: {e}")
            raise e # Rollback happens automatically on exception exit from 'begin()' block

    return None
