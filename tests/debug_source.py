
import sys
import os
import inspect
from pathlib import Path

# Add backend to sys.path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.append(str(backend_path))

try:
    from app.services.nightscout_client import NightscoutClient
    print(f"File: {inspect.getfile(NightscoutClient)}")
    print("--- Source of _update_clock_skew ---")
    print(inspect.getsource(NightscoutClient._update_clock_skew))
    print("------------------------------------")
except Exception as e:
    print(f"Error: {e}")
