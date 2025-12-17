
import asyncio
import os
import sys
from datetime import datetime

# Setup paths (hacky but works for scripts in root)
sys.path.append(os.path.join(os.getcwd(), "backend"))

# Load env vars explicitly
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), "backend", ".env"))

from app.services.nightscout_secrets_service import get_ns_config
from app.services.nightscout_client import NightscoutClient
from app.core.db import get_db_session_context

async def diagnose():
    print("--- DIAGNOSTICO BOLUS AI ---")
    
    # 1. Check DB Connection & Config
    print("\n1. Verificando Configuración en BD...")
    async with get_db_session_context() as session:
        # Assuming username is 'admin' or finding first user
        try:
            config = await get_ns_config(session, "admin")
            if config:
                print(f"✅ Config encontrada para 'admin'")
                print(f"   URL: {config.url}")
                print(f"   Enabled: {config.enabled}")
                print(f"   Token: {'***' if config.api_secret else 'None'}")
                
                if not config.enabled:
                    print("❌ ERROR: La configuración existe pero está DESHABILITADA (enabled=False).")
                    return
                if not config.url:
                    print("❌ ERROR: La URL está vacía en la base de datos.")
                    return
            else:
                print("❌ ERROR: No se encontró configuración de Nightscout para el usuario 'admin'.")
                print("   Esto confirma por qué pide manual: El backend no tiene datos.")
                return
                
            # 2. Test Connection
            print("\n2. Probando Conexión Real a Nightscout...")
            client = NightscoutClient(base_url=config.url, token=config.api_secret)
            try:
                sgv = await client.get_latest_sgv()
                print(f"✅ CONEXIÓN EXITOSA!")
                print(f"   Glucosa: {sgv.sgv} mg/dL")
                print(f"   Fecha: {datetime.fromtimestamp(sgv.date/1000)}")
                print(f"   Tendencia: {sgv.direction}")
            except Exception as e:
                print(f"❌ ERROR DE CONEXIÓN: {e}")
                print("   El backend tiene la URL, pero no puede conectar con ella.")
            finally:
                await client.aclose()
                
        except Exception as e:
            print(f"❌ ERROR GENERAL DE BD: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose())
