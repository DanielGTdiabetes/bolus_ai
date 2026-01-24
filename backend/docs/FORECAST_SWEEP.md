# Forecast Sweep Diagnostics

This document describes how to run the forecast sweep diagnostics to validate carb/bolus sensitivity and clamp behavior.

## What it does

The sweep runs a grid of simulations directly against `ForecastEngine` (no HTTP), varying:

- **Meal slot:** breakfast, lunch, dinner
- **Carbs:** 0/15/30/60 g
- **Bolus:** 0/2/4/6/8/12 U
- **Basal cases:** no basal injection vs. latest basal injection (if available)

Each run captures:

- `bg_min`, `bg_max`, `t_min`
- `bg_t30`, `bg_t60`, `bg_t120`, `bg_t180`
- `slope_0_15`, `delta_0_60`
- `clamp_hits` (points <= 20 or >= 600 mg/dL)

The sweep writes **CSV** and **JSON** files under `backend/data/diagnostics/` and prints a console summary.

## Running locally

```bash
python -m backend.scripts.forecast_sweep --user admin
```

## Running in Docker

```bash
docker compose exec backend python backend/scripts/forecast_sweep.py --user admin
```

## Environment variables

- `FORECAST_DIAGNOSTICS=1`: enables the protected API endpoint.
- `PREDICTION_DEBUG=1`: includes `prediction_diagnostics` metadata in forecast responses.

## Protected API endpoint (optional)

When `FORECAST_DIAGNOSTICS=1` **and** the caller is an admin user:

```
GET /api/forecast/diagnostics/sweep?user_id=admin
```

Response includes summary + paths to the generated CSV/JSON files.

## Issue detection rules

The JSON summary marks `issue_detected=true` if any of the following are met:

- **Clamp domination:** `clamp_hits > 0` in more than 20% of runs.
- **Bolus insensitivity:** `bg_min(12U)` vs `bg_min(6U)` differs by `< 5 mg/dL` for carbs=30.
- **Basal drift issue:** for carbs=0, bolus=0, `|delta_0_60| >= 30 mg/dL`.
- **Carbs ignored:** for carbs=60, bolus=0, `delta_0_60 < 10 mg/dL`.

All thresholds are configurable in `SweepConfig` (see `app/services/forecast_diagnostics.py`).
