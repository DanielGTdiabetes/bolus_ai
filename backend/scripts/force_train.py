import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.db import init_db, get_engine
from app.services.ml_trainer_service import MLTrainerService
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def force_train():
    print("🚀 --- FORZADO DE ENTRENAMIENTO ML ---")
    
    # Init DB
    init_db()
    engine = get_engine()
    
    if not engine:
        print("❌ Error: No se pudo obtener el motor de Base de Datos.")
        return

    # Check Catboost
    try:
        import catboost
        print(f"✅ CatBoost versión: {catboost.__version__}")
    except ImportError:
        print("❌ CatBoost NO está instalado. El entrenamiento fallará.")
        return

    async with AsyncSession(engine) as session:
        trainer = MLTrainerService(session)
        
        # Get users
        print("🔍 Buscando usuarios con datos...")
        try:
            res = await session.execute(text("SELECT DISTINCT user_id FROM ml_training_data_v2"))
            users = res.scalars().all()
        except Exception as e:
            print(f"❌ Error leyendo usuarios: {e}")
            return

        if not users:
            print("⚠️ No se encontraron usuarios en ml_training_data_v2.")
            return

        print(f"👥 Usuarios encontrados: {users}")
        
        for u in users:
            print(f"\n🧠 Entrenando modelo para: {u}...")
            try:
                # Force flags locally to bypass checks if possible, 
                # but better to see if it respects the env vars.
                result = await trainer.train_user_model(u)
                print(f"🏁 Resultado: {result}")
            except Exception as e:
                print(f"❌ Excepción durante el entrenamiento: {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(force_train())
