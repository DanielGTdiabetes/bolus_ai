import asyncio
import os
import sys

# Ensure we can import app modules
sys.path.append(os.getcwd())

from sqlalchemy import text
from app.core.db import get_engine, init_db
from app.core.settings import get_settings

async def diagnose():
    print("\n🔍 --- DIAGNÓSTICO DE MACHINE LEARNING (V2) --- 🔍\n")
    
    # 0. Initialize DB Connection
    try:
        init_db()
    except Exception as e:
        print(f"❌ Error fatal iniciando DB: {e}")
        return

    # 1. Check Settings
    try:
        settings = get_settings()
        is_enabled = settings.ml.training_enabled
        min_samples = settings.ml.min_training_samples
        min_days = settings.ml.min_days_history
        nas_url = settings.nas_public_url
        
        print(f"1️⃣  CONFIGURACIÓN:")
        print(f"   - ML_TRAINING_ENABLED: {'✅ TRUE' if is_enabled else '❌ FALSE'}")
        print(f"   - NAS PUBLIC URL: {nas_url if nas_url else '❌ (Si está vacío, puede que no se detecte como NAS)'}")
        print(f"   - Min Samples requeridos: {min_samples}")
        print(f"   - Min Días requeridos: {min_days}")
        
    except Exception as e:
        print(f"❌ Error leyendo settings: {e}")
        return

    # 2. Check Database
    print(f"\n2️⃣  ESTADO DE DATOS (Database):")
    engine = get_engine()
    if not engine:
        print("   ❌ No se pudo obtener el motor de base de datos (engine is None).")
        return

    async with engine.connect() as conn:
        try:
            # Check table existence
            res = await conn.execute(text("SELECT to_regclass('public.ml_training_data_v2')"))
            if not res.scalar():
                print("   ❌ La tabla 'ml_training_data_v2' NO existe todavía.")
                print("      (El sistema necesita recolectar datos primero. Espera unos 5-10 min).")
                return
            
            # Count rows
            res = await conn.execute(text("SELECT count(*) FROM ml_training_data_v2"))
            count = res.scalar()
            
            emoji_count = "✅" if count >= min_samples else "⚠️"
            print(f"   - Muestras recolectadas: {count} {emoji_count}")
            
            # Check date range
            res = await conn.execute(text("SELECT min(feature_time), max(feature_time) FROM ml_training_data_v2"))
            row = res.fetchone()
            days = 0
            if row and row[0] and row[1]:
                start, end = row
                days = (end - start).total_seconds() / 86400
                emoji_days = "✅" if days >= min_days else "⚠️"
                print(f"   - Rango de tiempo: {days:.2f} días (Desde {start} hasta {end}) {emoji_days}")
            else:
                 print("   ⚠️ No hay suficientes datos temporales.")

        except Exception as e:
            print(f"   ❌ Error consultando la BD: {e}")

    # 3. Conclusion
    print(f"\n3️⃣  CONCLUSIÓN:")
    if not is_enabled:
        print("   🔴 EL ENTRENAMIENTO ESTÁ DESACTIVADO.")
        print("      👉 Acción: Añade ML_TRAINING_ENABLED=true en Portainer.")
    elif count < min_samples:
         print(f"   🟠 FALTAN DATOS (Tienes {count}/{min_samples}).")
         print(f"      👉 Acción: Espera a que se recolecten más muestras (aprox 3-4 días de uso).")
    elif days < min_days:
         print(f"   🟠 FALTA HISTORIAL (Tienes {days:.1f}/{min_days} días).")
         print(f"      👉 Acción: Se requieren {min_days} días de historia mínima.")
    elif not nas_url:
         print("   🟠 NO SE DETECTA URL DEL NAS.")
         print("      👉 Acción: Asegúrate de que NAS_PUBLIC_URL está configurada, o activa ML_ALLOW_EPHEMERAL_TRAINING=true.")
    else:
         print("   🟢 TODO CORRECTO.")
         print("      Si los archivos no aparecen, fuerza el entrenamiento manualmente ejecutando:")
         print("      python backend/scripts/force_train.py (si existe) o espera al cronjob de las 03:00 AM.")

if __name__ == "__main__":
    asyncio.run(diagnose())
