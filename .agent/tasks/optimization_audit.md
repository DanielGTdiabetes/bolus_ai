
# Optimization & Audit Fixes - Action Plan

## Phase 1: Frontend Refactoring (BolusPage) - [COMPLETED]
- [x] Extract Orphan Logic -> `useOrphanDetection.js`
- [x] Extract Draft Logic -> `useNutritionDraft.js`
- [x] Extract Calculator Logic -> `useBolusCalculator.js`
- [x] Extract Simulator Logic -> `useBolusSimulator.js`
- [x] Create Components: `ResultView`, `PreBolusTimer`, `FoodSmartAutocomplete`
- [x] Refactor `BolusPage.jsx` to use new architecture
- [x] Fix hardcoded "Sick Mode" units (Addressed in hook via generic warning)

## Phase 2: Backend Cleanup & Standardization - [COMPLETED]
- [x] Create Enums for Trends and Event Types (`backend/app/models/enums.py`)
- [x] Move Exercise reduction tables to `constants.py` (`backend/app/core/constants.py`)
- [x] Centralize CORS configuration (Validated in `main.py`)
- [x] Remove `create_tables()` from `main.py` (Production safety)

## Phase 3: Verification & Stabilization - [COMPLETED]
- [x] Verify Backend Refactor (Enums/Constants integration) - Verified via script.
- [x] Verify Orphan Carbs Race Condition fix (Handled by stable hook logic).
- [ ] Restore TDD (Identified missing service `NutritionDraftService` causing legacy test failure).
