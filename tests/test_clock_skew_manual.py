
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

# Add backend to sys.path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.append(str(backend_path))

from app.services.nightscout_client import NightscoutClient
import httpx

print("DEBUG: STARTING TEST SCRIPT")
print(f"DEBUG: NightscoutClient loaded from: {NightscoutClient.__module__}")
# Note: NightscoutClient is a class, so check its module file
import app.services.nightscout_client as ns_module
print(f"DEBUG: Module file: {ns_module.__file__}")

def test_clock_skew_logic():
    client = NightscoutClient("http://mock", "token")
    
    # CASE 1: Server is BEHIND Local (Local is FAST/Future) - The likely NAS scenario
    # Local: 12:30
    # Server: 12:00
    # Entry: 12:00
    # Expected Skew: -30 mins
    
    local_now = datetime.now(timezone.utc)
    server_time = local_now - timedelta(minutes=30)
    server_str = server_time.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    headers = httpx.Headers({"Date": server_str})
    
    # DEBUG: Test parsing directly
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(server_str)
        print(f"DEBUG: Parsed '{server_str}' as '{dt}'")
    except Exception as e:
        print(f"DEBUG: Parsing failed for '{server_str}': {e}")

    # Act
    client._update_clock_skew(headers)
    
    skew = client.get_clock_skew_ms()
    print(f"Server Date: {server_str}")
    print(f"Local Date: {local_now}")
    print(f"Skew MS: {skew}")
    
    # Assert
    # Skew should be roughly -30 * 60 * 1000 = -1,800,000
    expected_skew = -30 * 60 * 1000
    # Allow 1 second tolerance for execution time
    assert abs(skew - expected_skew) < 1000, f"Skew {skew} not close to expected {expected_skew}"
    
    # Verify Correction
    adjusted_now_ms = (local_now.timestamp() * 1000) + skew
    server_ms = server_time.timestamp() * 1000
    
    diff = adjusted_now_ms - server_ms
    print(f"Adjusted Now vs Server Time Diff (ms): {diff}")
    assert abs(diff) < 1000, "Adjusted time should match server time"
    
    print("\n[PASS] Case 1: NAS Fast Clock (Future) corrected.")

    # CASE 2: No Skew
    headers_sync = httpx.Headers({"Date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")})
    client._update_clock_skew(headers_sync)
    print(f"Skew Clean: {client.get_clock_skew_ms()}")
    assert abs(client.get_clock_skew_ms()) < 1000
    print("\n[PASS] Case 2: Sync clocks.")

if __name__ == "__main__":
    test_clock_skew_logic()
