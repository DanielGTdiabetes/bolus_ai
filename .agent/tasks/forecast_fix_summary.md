# Fix Report: UnboundLocalError in Forecast Engine

## Issue
The user reported an `UnboundLocalError: cannot access local variable 'net_bg'` in `app/services/forecast_engine.py`.
This error occurred because `net_bg` was being accessed inside a safety check block (`if is_linked_meal and t < 90`) *before* it was actually calculated/assigned in the main simulation loop.

## Root Cause
The variable `net_bg` represents the final blood glucose for a given time step, calculated by summing components (insulin, carbs, basal, deviation). 
However, the "Anti-Panic Gating" logic (safety guards against rapid simulated drops) attempts to read the predicted BG to decide if it should dampen the insulin impact.
Since `net_bg` is calculated based on the *final* insulin impact, and the safety check is meant to *modify* that insulin impact, there was a circular dependency (or rather, an ordering error where the variable was used before definition).

## Resolution
We introduced a provisional variable `current_predicted_bg` calculated immediately before the safety checks.
This variable sums up the components (current BG, deviation, insulin, carbs, basal) *before* any damping is applied.
This value is then used for the safety checks:
1. Calculating instant slope (`instant_slope = (current_predicted_bg - series[-1].bg)`).
2. Checking for low BG risk (`is_low_risk = current_predicted_bg < 80`).

This ensures the logic has access to the estimated BG state without relying on the uninitialized `net_bg` variable.
The final `net_bg` calculation remains at the end of the loop iteration, utilizing the potentially damped insulin impact, ensuring correct final output.

## Code Change
File: `backend/app/services/forecast_engine.py`
Status: Applied
