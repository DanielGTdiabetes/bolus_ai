
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.db import get_db_session
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from app.models.treatment import Treatment
from sqlalchemy import select

async def debug_forecast():
    async for session in get_db_session():
        print("--- Debugging Forecast Trigger ---")
        
        # 1. Load Settings
        user_settings = None
        try:
            data = await get_user_settings_service("admin", session) # Assuming 'admin' is the user or we check all
            if data and data.get("settings"):
                user_settings = UserSettings.migrate(data["settings"])
                print(f"User Settings Loaded.")
                print(f"Absorption Settings: {user_settings.absorption}")
            else:
                print("No user settings found.")
        except Exception as e:
            print(f"Error loading settings: {e}")

        # 2. Fetch Treatments (Last 12 hours)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        print(f"Fetching treatments since: {cutoff}")
        
        stmt = (
            select(Treatment)
            # .where(Treatment.user_id == user.username) # defaulting to fetching all or logic for admin
            .where(Treatment.created_at >= cutoff.replace(tzinfo=None))
            .order_by(Treatment.created_at.desc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        
        print(f"Found {len(rows)} treatments.")
        
        # 3. Simulate Logic
        rows_processed = []
        for row in rows:
            print(f"Treatment: {row.created_at} | Insulin: {row.insulin} | Carbs: {row.carbs} | Notes: {row.notes}")
            
            # Check conditions
            if row.carbs and row.carbs > 0:
                is_slow = False
                reason = []
                
                # Check absorption from settings
                # We need hour
                r_time = row.created_at
                if r_time.tzinfo is None: r_time = r_time.replace(tzinfo=timezone.utc)
                user_hour = (r_time.hour + 1) % 24
                
                base_abs = 180 # default
                if user_settings:
                    if 5 <= user_hour < 11: base_abs = user_settings.absorption.breakfast
                    elif 11 <= user_hour < 17: base_abs = user_settings.absorption.lunch
                    else: base_abs = user_settings.absorption.dinner
                
                current_abs = base_abs
                
                if row.notes:
                    if "alcohol" in row.notes.lower():
                        current_abs = 480
                        reason.append("Alcohol Note")
                    elif "dual" in row.notes.lower() or "combo" in row.notes.lower():
                        current_abs = 360
                        reason.append("Dual/Combo Note")
                    elif "split" in row.notes.lower():
                        current_abs = 300
                        reason.append("Split Note")
                
                # Warsaw check
                fat = getattr(row, "fat", 0) or 0
                protein = getattr(row, "protein", 0) or 0
                if (fat > 0 or protein > 0) and user_settings and user_settings.warsaw.enabled:
                     # Simulate warsaw
                     extra_kcal = fat*9 + protein*4
                     fpu_carbs = extra_kcal/10
                     if fpu_carbs >= 20: 
                         # This creates a NEW carb entry in Forecast, but the original logic also checks 'is_dual'
                         # Forecast.py lines 377+ creates a secondary carb entry.
                         # Line 467 checks: any(c for c in carbs if getattr(c, 'is_dual', False) or ...)
                         
                         w_abs = 0
                         if fpu_carbs < 20: w_abs = 180
                         elif fpu_carbs < 40: w_abs = 240
                         else: w_abs = 300
                         
                         is_dual = extra_kcal >= user_settings.warsaw.trigger_threshold_kcal
                         
                         if w_abs >= 300 or is_dual:
                             reason.append(f"Warsaw (FPU: {fpu_carbs}, Dual: {is_dual})")
                             is_slow = True

                if current_abs >= 300:
                    is_slow = True
                    reason.append(f"High Base/Calc Absorption ({current_abs})")
                
                if is_slow:
                    print(f"  -> TRIGGERS SLOW MODE! Reason: {reason}")
                else:
                    print(f"  -> Normal Mode.")

        break

if __name__ == "__main__":
    asyncio.run(debug_forecast())
