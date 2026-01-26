
import asyncio
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import from backend properly
from backend.app.core.db import get_db_session_context, init_db
from sqlalchemy import text, select
from backend.app.models.meal_learning import MealCluster

async def check_learning():
    # Make sure DB is initialized
    init_db()
    
    async with get_db_session_context() as session:
        if not session:
            print("ERROR: No database session available (Check DATABASE_URL environment variable)")
            return

        print("--- VERIFICACIÓN DEL APRENDIZAJE (CLUSTERING) ---")
        print(f"Time: {datetime.now()}")
        
        try:
            # 1. Check Raw Experiences
            result_exp = await session.execute(text("SELECT count(*) FROM meal_experiences"))
            count_exp = result_exp.scalar()
            print(f"\n1. Experiencias Registradas (Comidas analizadas): {count_exp}")
            
            if count_exp > 0:
                # Show breakdown by status
                result_status = await session.execute(text("SELECT window_status, count(*) FROM meal_experiences GROUP BY window_status"))
                print("   Estado de las experiencias:")
                for row in result_status:
                    print(f"   - {row[0]}: {row[1]}")
            else:
                print("   (El sistema aún no ha procesado ninguna comida histórica. Puede requerir que pase el Job de aprendizaje).")

            # 2. Check Clusters
            result_clusters = await session.execute(text("SELECT count(*) FROM meal_clusters"))
            count_clusters = result_clusters.scalar()
            print(f"\n2. Clústeres Formados (Patrones aprendidos): {count_clusters}")
            
            if count_clusters > 0:
                print("   Top 5 Clústeres más usados:")
                stmt = select(MealCluster).order_by(MealCluster.n_ok.desc()).limit(5)
                clusters = (await session.execute(stmt)).scalars().all()
                for c in clusters:
                    print(f"   - Key: {c.cluster_key}")
                    print(f"     Éxitos (n_ok): {c.n_ok} | Confianza: {c.confidence}")
                    print(f"     Perfil Aprendido: Duración {c.absorption_duration_min}m (Pico {c.peak_min}m)")
                    print("     ---")
            else:
                print("   (No hay clústeres aún. Se crean automáticamente cuando una comida 'ok' se procesa).")
        except Exception as e:
            print(f"Error querying database: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv() # Load .env if present
    asyncio.run(check_learning())
