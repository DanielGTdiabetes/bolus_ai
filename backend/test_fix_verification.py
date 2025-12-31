import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv("backend/.env")
sys.path.append(os.getcwd())

from app.core.db import get_engine, init_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2
from app.models.bolus_v2 import BolusRequestV2, GlucoseUsed

async def test_calculation():
    init_db()
    engine = get_engine()
    if not engine:
        print("❌ No DB engine available.")
        return

    async with AsyncSession(engine) as session:
        print("--- Verificando Configuración de Usuario 'admin' ---")
        data = await get_user_settings_service("admin", session)
        
        if not data or not data.get("settings"):
            print("❌ No settings found for admin.")
            return

        settings_dict = data["settings"]
        user_settings = UserSettings.migrate(settings_dict)
        
        mid_target = user_settings.targets.mid
        print(f"✅ Objetivo (Target) en DB: {mid_target} mg/dL")
        
        if mid_target != 110:
             print(f"⚠️  ALERTA: El objetivo no es 110, es {mid_target}. El test fallará.")

        # Simulate the Scenario
        # BG: 134
        # Meal: 8.6g (Carbs)
        # CR: 2.5
        # ISF: 78
        # Warsaw: 344kcal -> Factor 0.1
        
        print("\n--- Simulando Cálculo ---")
        print("Input: Glucosa 134 mg/dL | Carbos 8.6g | CR 2.5 | ISF 78")
        
        # Override settings locally to match the exact screenshot parameters for CR/ISF/Warsaw
        # Just to isolate the Target variable effect.
        # Screenshot says: CR 2.5, ISF 78
        user_settings.cr.lunch = 2.5
        user_settings.cf.lunch = 78.0
        
        # Request
        req = BolusRequestV2(
            carbs_g=8.6,
            current_bg=134.0,
            meal_slot="lunch",
            # We do NOT pass target_mgdl here, ensuring it uses Settings
            fat_g=20, # Estimation for Warsaw trigger
            protein_g=20 
        )
        
        glucose_info = GlucoseUsed(mgdl=134.0, source="manual")
        
        # Execute
        result = calculate_bolus_v2(req, user_settings, iob_u=0.0, glucose_info=glucose_info)
        
        print(f"\nResultados:")
        print(f"• Corrección Calculada: {result.correction_u} U")
        print(f"• Total Final: {result.total_u_final} U")
        
        # Verification
        # Target 110 -> (134-110)/78 = 0.307 -> 0.31 U
        # Target 100 -> (134-100)/78 = 0.435 -> 0.44 U
        
        expected_corr = 0.31
        # Allow small float diff
        if abs(result.correction_u - expected_corr) < 0.02:
             print(f"\n✅ TEST APROBADO: La corrección ({result.correction_u} U) coincide con Target 110.")
        else:
             print(f"\n❌ TEST FALLIDO: La corrección ({result.correction_u} U) NO coincide con Target 110 (Esperado ~0.31).")
             if abs(result.correction_u - 0.44) < 0.02:
                 print("   -> Parece que sigue usando Target 100.")

if __name__ == "__main__":
    asyncio.run(test_calculation())
