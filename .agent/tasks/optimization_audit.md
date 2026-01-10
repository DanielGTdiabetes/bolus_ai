
# Optimization & Audit Fixes - Action Plan

## Phase 1: Frontend Refactoring (BolusPage) - [COMPLETED]
- [x] Extract Orphan Logic -> `useOrphanDetection.js`
- [x] Extract Draft Logic -> `useNutritionDraft.js`
- [x] Extract Calculator Logic -> `useBolusCalculator.js`
- [x] Extract Simulator Logic -> `useBolusSimulator.js`
- [x] Create Components: `ResultView`, `PreBolusTimer`, `FoodSmartAutocomplete`
- [x] Refactor `BolusPage.jsx` to use new architecture
- [x] Fix hardcoded "Sick Mode" units (handled in logic or pending backend check? - Addressed in hook via generic warning, refined in backend phase)

## Phase 2: Backend Cleanup & Standardization - [NEXT]
- [ ] Create Enums for Trends and Event Types
- [ ] Move Exercise reduction tables to `constants.py` or config
- [ ] Centralize CORS configuration
- [ ] Remove `create_tables()` from `main.py` (Production safety)
- [ ] Add `clean_db` script or workflow for dev reset

## Phase 3: Verification & Stabilization
- [ ] Restore TDD / Run Tests
- [ ] Verify Orphan Carbs Race Condition fix (handled by `useOrphanDetection` useEffect logic)
- [ ] Verify Fiber Deduction Logic
