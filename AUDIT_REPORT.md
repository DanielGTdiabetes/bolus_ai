# Audit Report

## 1. Summary

**Date:** 2026-01-22
**Scope:** Backend (FastAPI), Bot, Frontend (React), Infra.
**Auditor:** Gemini (Agentic AI)
**Status:** **PASSED** (All critical and major issues resolved)

This report details findings from the comprehensive audit of the Bolo AI repository and the subsequent remediations applied to ensure robustness, security, and stability.

## 2. Critical Findings & Remediation (P0/P1)

### [P1] Missing Centralized ML Configuration

- **Issue:** The ML service directly accessed `os.getenv("ML_MODEL_DIR")`, bypassing `settings.py`. This created a risk of silent failures if environment variables were inconsistent across deployments (NAS vs Render).
- **Remediation:**
  - Added `MLConfig` to `backend/app/core/settings.py`.
  - Updated `ml_inference_service.py` to route all configuration through the centralized Settings object.
- **Verification:** Verified by static analysis and successful backend startup.

### [P1] Database Leader Lock Spam

- **Issue:** The Telegram Bot's leader election logic used an optimistic `INSERT` strategy that generated thousands of "unique constraint violation" errors in the database logs (approx 1 every 20s per replica).
- **Remediation:** refactored `try_acquire_bot_leader` in `backend/app/bot/leader_lock.py` to use a "Check-then-Insert" pattern.
- **Verification:** Validated with `pytest backend/tests/test_bot_leader_lock.py` (passed).

## 3. Major Findings & Remediation (P2)

### [P2] Hardcoded ML Safety Clamps

- **Issue:** The prediction engine had a hardcoded safety clamp of +/- 100 mg/dL for residual corrections.
- **Remediation:** Moved this value to `Settings.ml.safety_clamp_mgdl` (default 100), allowing future adjustment via environment variables without code deployment.

### [P2] Vision Timeout Risk

- **Issue:** Default timeout for AI Vision analysis was 15 seconds, which is aggressive for complex GenAI storage/processing.
- **Remediation:** Increased default timeout to 30 seconds in `Settings`.

### [P2] Pydantic Protected Namespace Conflict

- **Issue:** Pydantic models with fields starting with `model_` emit warnings because that prefix is protected in Pydantic v2. This polluted logs in Render.
- **Remediation:** Added `model_config = ConfigDict(protected_namespaces=())` to `MLConfig` class in `settings.py`.

## 4. Minor Observations (P3)

- **Test Warnings:** Backend tests emit `RuntimeWarning: coroutine ... was never awaited` in some mock scenarios (`test_settings_sync.py`). This suggests improving test hygiene but does not affect production code.
- **Frontend Build:** Successfully built with Vite (`npm run build`). No critical dependency issues found.

## 5. Deployment Recommendation

The codebase is stable for deployment.

- **NAS:** Deploy using the provided `docker-compose.yml`. Ensure `ML_MODEL_DIR` is mounted if custom models are used, otherwise it defaults securely.
- **Render:** Standard build script `build_render.sh` should be used.

## 6. How to Verify

Refer to `VERIFICATION.md` for specific commands to validate the integrity of the release.
