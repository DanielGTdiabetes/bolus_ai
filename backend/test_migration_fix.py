
from app.models.settings import UserSettings
import json

def test_migration():
    # Simulate legacy frontend payload
    legacy_payload = {
        "breakfast": {"icr": 10, "isf": 50},
        "dia_hours": 5.5,
        "insulin_model": "fiasp",
        "techne": {"enabled": False}
    }
    
    print("Legacy Payload:", json.dumps(legacy_payload, indent=2))
    
    # Run migration
    settings = UserSettings.migrate(legacy_payload)
    
    print("\nMIGRATED SETTINGS (IOB):")
    print(settings.iob.model_dump())
    
    # Assertions
    assert settings.iob.dia_hours == 5.5, f"Expected 5.5, got {settings.iob.dia_hours}"
    assert settings.iob.curve == "fiasp", f"Expected fiasp, got {settings.iob.curve}"
    
    print("\nSUCCESS: Migration logic works correctly.")

if __name__ == "__main__":
    test_migration()
