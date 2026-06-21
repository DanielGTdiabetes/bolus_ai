# Android Companion offline bolus

Companion includes a local "Bolo" screen for basic offline bolus calculation on Android tablets and phones.

## Flow

1. The user syncs the local profile from Bolus AI when the NAS or backup server is reachable.
2. Companion stores only calculation-safe fields locally:
   - carb ratios (`cr`)
   - correction factors (`cf`)
   - glucose targets
   - insulin duration metadata
   - fiber subtraction settings
   - rounding and max bolus limits
3. When offline, the app calculates from the last saved profile without calling the NAS, Render, Neon, Nightscout, or Hermes.

## Backend endpoint

`GET /api/integrations/mobile/bolus-settings`

Authentication uses the existing `X-Ingest-Key` integration key. The endpoint deliberately does not return Nightscout tokens, API keys, Dexcom credentials, or vision provider secrets.

## Current calculation scope

The first offline version calculates:

```text
meal bolus = net carbs / CR
correction = max(glucose - target, 0) / CF
final = round(meal bolus + correction - manual IOB)
```

The final bolus is capped by `max_bolus_u`; correction is capped by `max_correction_u`.

IOB is manual in this first version. The app does not yet reconstruct real IOB offline from Nightscout/treatment history, so the UI labels it clearly as manual input.

## When to use backend instead

Use the full Bolus AI web/backend flow when connected for:

- dual or extended bolus decisions
- Warsaw/high-fat meal logic
- restaurant mode
- automatic IOB/COB context
- Nightscout-backed treatment history
