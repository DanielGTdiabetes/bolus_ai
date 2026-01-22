# Verification Plan

## 1. Environment Setup

Ensure you have the Python virtual environment active and dependencies installed.

```powershell
# Verify Python
python --version
# Verify Node
node --version
```

## 2. Backend Smoke Tests

Run existing pytest suite to verify core logic and regressions.

```powershell
# Run all tests
pytest
```

## 3. Bot Logic Verification

Specifically verify the Leader Lock mechanism to prevent DB spam.

```powershell
# Test leader lock logic
pytest backend/tests/test_bot_leader_lock.py
```

## 4. Frontend Build

Verify that the frontend builds without errors (no type errors, no lint failures impacting build).

```powershell
cd frontend
npm install
npm run build
```

## 5. Live Server Smoke Test (Local)

Attempt to start the backend and verify health endpoints.

```powershell
# Start backend (Ctrl+C to stop after verification)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Endpoints to Check:**

- `http://127.0.0.1:8000/healthz` (Basic API Health)
- `http://127.0.0.1:8000/api/health/check` (Detailed Health)

## 6. Regression Check

- Ensure that `bot_leader_locks` table is not receiving duplicate key errors.
- Ensure that ML service handles missing `ML_MODEL_DIR` gracefully (logs warning instead of crash).
