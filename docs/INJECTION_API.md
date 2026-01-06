# Manual verification for injection endpoints

Use these commands to validate the JSON contract and persistence for the injection endpoints:

```bash
# Save a manual rapid site
curl -X POST 'https://bolus-ai-1.onrender.com/api/injection/manual' \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"insulin_type":"rapid","point_id":"abd_r_top:1"}'

# The response must be JSON similar to:
# { "ok": true, "insulin_type": "rapid", "point_id": "abd_r_top:1", "updated_at": "...", "source": "manual", "suggested_point_id": "..." }

# Read the state and verify persistence
curl -X GET 'https://bolus-ai-1.onrender.com/api/injection/state' \
  -H 'Authorization: Bearer <token>'

# The GET response must reflect the saved point_id in states.bolus.last_point_id (and at the top-level "bolus" field).

# Nota: "insulin_type": "rapid" se mapea internamente al tipo "bolus" por compatibilidad legacy.
```
