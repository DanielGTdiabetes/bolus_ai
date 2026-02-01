import asyncio
import os
import sys

# Ensure we can import app modules
sys.path.append(os.getcwd())

from sqlalchemy import text
from app.core.db import get_engine
from app.core.settings import get_settings

async def diagnose():
    print("\n🔍 --- DIAGNÓSTICO DE MACHINE LEARNING --- 🔍\n")
    
    # 1. Check Settings
    try:
        settings = get_settings()
        is_enabled = settings.ml.training_enabled
        min_samples = settings.ml.min_training_samples
        min_days = settings.ml.min_days_history
        
        print(f"1️⃣  CONFIGURACIÓN:")
        print(f"   - ML_TRAINING_ENABLED: {'✅ TRUE' if is_enabled else '❌ FALSE'}")
        print(f"   - Min Samples requeridos: {min_samples}")
        print(f"   - Min Días requeridos: {min_days}")
        
    except Exception as e:
        print(f"❌ Error leyendo settings: {e}")
        return

    # 2. Check Database
    print(f"\n2️⃣  ESTADO DE DATOS (Database):")
    engine = get_engine()
    if not engine:
        print("   ❌ No se pudo conectar a la base de datos.")
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
        print("      👉 Acción: Añade la variable de entorno ML_TRAINING_ENABLED=true en Portainer.")
    elif count < min_samples:
         print(f"   🟠 FALTAN DATOS.")
         print(f"      👉 Acción: Espera a que se recolecten {min_samples} muestras (aprox 3-4 días).")
    elif 'days' in locals() and days < min_days:
         print(f"   🟠 FALTA HISTORIAL.")
         print(f"      👉 Acción: Se requieren {min_days} días de historia mínima.")
    else:
         print("   🟢 TODO CORRECTO. El modelo debería entrenarse en el próximo ciclo (03:00 AM) o reiniciando.")

if __name__ == "__main__":
    asyncio.run(diagnose())
