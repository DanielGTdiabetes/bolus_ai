# Night Pattern Prediction (Personal Night Pattern)

## Purpose
The Night Pattern adjustment is an **opt-in** feature that blends the existing model-based forecast with a user-specific overnight pattern to reduce false hyperglycemia spikes during the night. It is deliberately conservative and designed to fail safe, falling back to the existing model whenever context is unclear.

## Safety Constraints
- Applied **only** in the user local timezone `Europe/Madrid`.
- Windows:
  - **Window A:** 00:00–02:00 (may apply if context is clean)
  - **Window B:** 02:00–03:45 (ultra-conservative; must be clean **and** no slow digestion signals)
  - **>= 04:00:** never applies
- Never applied if IOB/COB are missing or ambiguous.
- Never applied when glucose trend is strongly rising.
- Never applied if recent meals/boluses are detected within the configured lookback windows.

## Pattern Computation
- Uses the last **N days** of CGM data (default 18).
- Buckets per 15 minutes between 00:00 and 03:45.
- For each bucket, compute:
  - Median delta over the next 75 minutes
  - Dispersion (IQR) for transparency
- Excludes “dirty” nights:
  - Meals/treatments/boluses within the lookback windows
  - Hypoglycemia treatments
  - Compression lows (if the flag exists in future)
- Stored in DB (`night_pattern_profiles`) with `computed_at` and sample counts.

## Pattern Blending (Bounded Modulation)
```
forecast_adj = forecast_model + clamp(w * delta_pattern, -cap, +cap)
```
- Weight `w` defaults:
  - Window A: `0.30`
  - Window B: `0.20`
- Cap defaults: `25 mg/dL`
- Never reduces predicted glucose if trend is strongly rising.

## Clean Context Requirements
All must be true:
- No active nutrition draft.
- No recent meal within `NIGHT_PATTERN_MEAL_LOOKBACK_H`.
- No recent bolus within `NIGHT_PATTERN_BOLUS_LOOKBACK_H`.
- IOB is low (`<= NIGHT_PATTERN_IOB_MAX_U`) **and available**.
- COB is low (`<= 1g`) **and available**.
- Trend is not strongly rising (`NIGHT_PATTERN_SLOPE_MAX_MGDL_PER_MIN`).

### Slow Digestion Signals (Window B disables if any)
- Recent meal within lookback window.
- High fat/protein meal (if macros present).
- COB not near zero.
- Sustained rise in the last 30–60 minutes.
- Active nutrition draft.

## Configuration (Defaults)
| Env var | Default |
| --- | --- |
| `NIGHT_PATTERN_ENABLED` | `false` |
| `NIGHT_PATTERN_DAYS` | `18` |
| `NIGHT_PATTERN_BUCKET_MIN` | `15` |
| `NIGHT_PATTERN_HORIZON_MIN` | `75` |
| `NIGHT_PATTERN_WEIGHT_A` | `0.30` |
| `NIGHT_PATTERN_WEIGHT_B` | `0.20` |
| `NIGHT_PATTERN_CAP_MGDL` | `25` |
| `NIGHT_PATTERN_WINDOW_A_START` | `00:00` |
| `NIGHT_PATTERN_WINDOW_A_END` | `02:00` |
| `NIGHT_PATTERN_WINDOW_B_START` | `02:00` |
| `NIGHT_PATTERN_WINDOW_B_END` | `03:45` |
| `NIGHT_PATTERN_DISABLE_AT` | `04:00` |
| `NIGHT_PATTERN_MEAL_LOOKBACK_H` | `6` |
| `NIGHT_PATTERN_BOLUS_LOOKBACK_H` | `4` |
| `NIGHT_PATTERN_IOB_MAX_U` | `0.3` |
| `NIGHT_PATTERN_SLOPE_MAX_MGDL_PER_MIN` | `0.4` |

## API Metadata
Forecast responses include:
```json
prediction_meta: {
  "pattern": {
    "enabled": true,
    "applied": true,
    "window": "A",
    "reason_not_applied": null,
    "weight": 0.3,
    "cap_mgdl": 25,
    "sample_days": 18,
    "sample_points": 120,
    "dispersion": 8.4,
    "computed_at": "2026-02-10T00:00:00Z"
  }
}
```

## How to Test on Render
> These calls only *read* forecasts and metadata; they do not change integrations.

1) **Enable flag for your instance**
```bash
curl -X POST "$RENDER_URL/api/admin/env" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "NIGHT_PATTERN_ENABLED=true"
```

2) **Get current forecast (check pattern metadata)**
```bash
curl -s "$RENDER_URL/api/forecast/current" | jq '.prediction_meta.pattern'
```
Expected: `enabled: true` and either `applied: true` or a clear `reason_not_applied`.

3) **Verify pattern does not apply after 04:00 local**
```bash
curl -s "$RENDER_URL/api/forecast/current" | jq '.prediction_meta.pattern.window'
```
Expected: `null` when local time is >= 04:00.
