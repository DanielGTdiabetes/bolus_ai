# PROJECT ANALYSIS — Bolus AI

> Generated from deep exploration session. Contains architecture understanding, service relationships, and identified bugs.

---

## 1. Architecture Overview

Bolus AI is an intelligent diabetes management assistant with a **dual-instance deployment** (NAS primary + Render backup). It calculates insulin boluses, analyzes food photos with AI vision, and synchronizes with Nightscout.

### Dual-Instance HA

| | NAS (primary) | Render (backup) |
|---|---|---|
| **Hosting** | Docker via Portainer on home NAS | Render.com cloud service |
| **Database** | Local PostgreSQL | Neon (cloud PostgreSQL) |
| **Telegram bot** | Dedicated token, always POLLING | Separate token, DISABLED in standby |
| **DB Sync** | → Neon every 4h (unidirectional) | Receives sync from NAS |
| **Failover** | — | Manual: `EMERGENCY_MODE=true` |
| **Leader Lock** | DB-based distributed lock with TTL + heartbeat | Same lock — acquires when NAS dies |

### Two Telegram Bots

- **NAS bot**: Always active in POLLING mode
- **Render bot**: Disabled (send-only) in normal operation; activates as WEBHOOK or POLLING when `EMERGENCY_MODE=true`

Bot mode selection (`bot/service.py`):
- `RENDER` env + `EMERGENCY_MODE=false` → `BotMode.DISABLED`
- `RENDER` env + `EMERGENCY_MODE=true` → `BotMode.WEBHOOK` or `BotMode.POLLING`
- NAS (no `RENDER`) → `BotMode.POLLING` always

### DB Sync Safety Valve

Before syncing NAS → Neon, checks if Neon has `treatment_audit_log` records created during Emergency Mode in the last 24h. If detected, backup **aborts** and sends critical Telegram alert to prevent overwriting emergency data.

---

## 2. Backend Architecture

### Directory Structure

```
backend/app/
├── main.py                 # FastAPI app, startup/shutdown, SPA serving
├── jobs.py                 # APScheduler background job definitions
├── jobs_state.py           # Job state tracking
├── api/                    # 28+ FastAPI route modules
├── bot/                    # Telegram bot (service, tools, proactive, AI, webhook)
├── services/               # 43 business logic services
├── models/                 # 28 SQLAlchemy ORM + Pydantic schemas
├── dtos/                   # Data transfer objects
├── core/                   # DB engine, settings, auth, migrations, logging
└── utils/                  # Utility functions
```

### Startup Sequence (`main.py`)

1. Configure logging, load settings
2. Create FastAPI app with CORS middleware
3. Register routers: `/api/*`, `/api/webhook/*`, `/api/bot/telegram/*`
4. **Startup event**:
   - Validate JWT_SECRET and APP_SECRET_KEY
   - Import models, init async DB engine
   - Wait for DB readiness with retry (10 attempts, 3s delay)
   - Create tables via `Base.metadata.create_all`
   - Run idempotent schema migrations
   - Seed admin user
   - **Background tasks** (non-blocking):
     - Rescue sync from Nightscout (last 6h treatments)
     - ML model sync from database
     - Setup APScheduler periodic jobs
     - Initialize Telegram bot
5. **Shutdown**: Clean shutdown of Telegram bot
6. **SPA serving**: In production, serves React frontend from `app/static/`

### Configuration Hierarchy (lowest → highest priority)

1. Pydantic model defaults in `app/core/settings.py`
2. `config/config.json` file values
3. Environment variables

### Database Setup (`core/db.py`)

- **Engine**: SQLAlchemy 2.0 async with `asyncpg` (PostgreSQL) or `aiosqlite` (SQLite for tests)
- **Pool**: pool_size=20, max_overflow=20, pool_pre_ping=True
- **SSL**: Extracts sslmode from URL for asyncpg compatibility
- **Retry**: 10 attempts, 3s delay for container startup race conditions
- **Safety**: Refuses to start without DATABASE_URL in production (prevents insulin stacking)
- **Migration**: Dual approach — Alembic for formal migrations + idempotent `migrate_schema()` with `IF NOT EXISTS`

---

## 3. Bolus Calculation System

### Three-Layer Architecture

```
BolusRequestV2 → bolus_calc_service.py (orchestrator) → bolus_engine.py (math) → iob.py (IOB/COB)
```

### `bolus_calc_service.py` — Orchestrator

**Settings resolution** (3 tiers):
1. Full `CalcSettings` object from payload
2. Flat overrides (cr_g_per_u, isf_mgdl_per_u)
3. DB/Store fallback via `settings_service` → `DataStore` JSON

**Glucose resolution**:
- Manual `bg_mgdl` if provided
- Otherwise fetch from Nightscout (`get_latest_sgv()` or `get_sgv_range()`)
- Compute BG age; mark stale if >10 minutes
- Run `CompressionDetector` for CGM compression artifacts

**Last bolus detection**:
- Query local DB for recent treatments with insulin > 0
- Calculate minutes since last bolus → stacking warnings

**Hybrid Autosens** (lines 356-422):
```
effective_ratio = clamp(TDD_ratio × local_autosens_ratio, min_ratio, max_ratio)
```
Example: TDD 1.10 × Local 0.95 = 1.045 → clamped to [0.7, 1.3]

**IOB/COB computation**:
```python
iob_u, breakdown, iob_info, iob_warning = await compute_iob_from_sources(...)
cob_total, cob_info, cob_source_status = await compute_cob_from_sources(...)
```

**Safety confirmations**:
- IOB "unavailable" → HTTP 424, requires `confirm_iob_unknown=true`
- IOB "stale" → HTTP 424, requires `confirm_iob_stale=true`
- After confirmation: IOB assumed 0.0 with warning flags

### `bolus_engine.py` — Math Core

**Step 1: Autosens Adjustment**
```python
effective_ratio = clamp(autosens_ratio, 0.7, 1.3)
cr = inp.cr / effective_ratio    # Higher ratio = more resistant = more insulin
isf = inp.isf / effective_ratio   # Higher ratio = each unit drops more mg/dL
```
Safety: CR min 10.0, ISF min 30.0

**Step 2: Meal Bolus**
```python
meal_u = eff_carbs / cr
```

Fiber deduction:
- If `fiber_g >= carbs_g`: NO deduction (high fiber rule), no auto-split
- If `fiber_g > fiber_threshold` and deduction enabled: `eff_carbs = carbs_g - fiber_g * fiber_factor`
- High fiber → triggers 50/50 split (half upfront, half extended)

**Warsaw Method (Fat/Protein)**:
```python
kcal_fat = fat_g * 9
kcal_prot = protein_g * 4
total_kcal = kcal_fat + kcal_prot
fpu_count = total_kcal / 100.0  # Each 100 kcal = 1 FPU
```
- Dual Mode (auto-split): `warsaw_ins = (fpu_count * 10.0 * warsaw_factor_dual) / cr` → goes to `later_u`
- Simple Mode: `warsaw_ins = (fpu_count * 10.0 * warsaw_factor_simple) / cr` → adds to `meal_u`

**Step 3: Correction Bolus**
```python
diff = bg_mgdl - target_mgdl
corr_u = diff / isf
corr_u = min(corr_u, max_correction_u)  # Hard cap
```
Skipped if BG stale (>10 min). Negative correction allowed (BG < target).

**Step 4: IOB Subtraction**
```python
total_base_upfront = meal_u + corr_u
upfront_net = max(0.0, total_base_upfront - iob_u)  # IOB only reduces upfront
later_base = warsaw_later_u + fiber_extension_u      # IOB does NOT reduce extended
```
If `ignore_iob=true` (dessert mode): IOB completely skipped.

**Step 4b: Bolus Stacking Warning**
```python
if last_bolus_minutes < min_bolus_interval_min:
    warnings.append("STACKING_WARNING")
```

**Step 4c: Max IOB Ceiling**
```python
projected_iob = iob_u + upfront_net + later_base
if projected_iob > max_iob_u:
    allowed = max_iob_u - iob_u
    # Reduce upfront first, then later
```

**Step 5: Exercise Reduction**
```python
reduction = calculate_exercise_reduction(minutes, intensity)  # 0.0 to 0.9
final_upfront = upfront_net * (1.0 - reduction)
final_later = later_base * (1.0 - reduction)
```

Exercise reduction table (interpolated):
| Duration | Low | Moderate | High |
|----------|-----|----------|------|
| 60 min | 15% | 30% | 45% |
| 120 min | 30% | 55% | 75% |

**Step 6: Rounding & Limits**

**Techne Rounding** (`_smart_round`):
- Rising trend (DoubleUp, SingleUp, FortyFiveUp) → **Ceil** (aggressive)
- Falling trend (DoubleDown, SingleDown, FortyFiveDown) → **Floor** (conservative)
- Flat/None → **Nearest** (standard)
- **Safety override**: If BG < 100, disables Ceil behavior
- Max deviation guard: if proposed rounding differs from raw by > `techne_max_step`, fallback to standard

**Hard Stop Hypo**:
```python
if bg_mgdl < 70:
    final_upfront = 0.0
    final_later = 0.0
    final_total = 0.0
```

**Max bolus cap**: Scales down proportionally, reducing upfront first.

### `iob.py` — IOB/COB Calculations

**IOB Math — 5 Curve Models**:

| Model | Formula |
|-------|---------|
| **Walsh/Exponential** | `IOB = (FD - Ft) / (FD - F0)` where `F(t) = τ·e^(-t/τ)·(τ/D - 1 + t/D)`, `τ = peak·(1-peak/D) / (1 - 2·peak/D)` |
| **Bilinear** | Triangle area calculation |
| **Fiasp** | Interpolated from clinical EPAR data (21 points) |
| **NovoRapid** | Interpolated from clinical EPAR data (21 points) |
| **Linear** | `max(0, 1 - t/D)` |

```python
compute_iob(now, boluses, profile) = Σ(units_i × insulin_activity_fraction(elapsed_i, profile))
```

**COB Math**:
- **Linear**: `fraction = 1.0 - (elapsed / duration_min)`, default 4h decay
- **Biexponential (carbcurves)**: `rate(t) = f × hovorka(t, t_max_r) + (1-f) × hovorka(t, t_max_l)`
  - Fiber: reduces fast fraction `f`, delays absorption
  - Fat/Protein: `fp_units = fat + protein*0.5`, extends `t_max_l` by `fp_units * 1.5`

**Source Priority** for IOB/COB:
1. Local DB (PostgreSQL `treatments` table) — primary
2. Local store (JSON events file) — catches pending uploads
3. Extra boluses (passed from caller)

**Deduplication**:
- Exact match: same units (±0.01) and time within 15 minutes
- Timezone glitch guard: detects 1h or 2h offsets (CET/CEST bugs) with 5min tolerance

**Square wave / extended bolus**:
- Discretizes into 5-minute chunks
- Future (undelivered) chunks count as 100% IOB
- Delivered chunks decay normally

### `bolus_split.py` — Split Bolus Planning

**`create_plan()`**:
- Manual mode: user specifies `now_u` and `later_u` directly
- Dual mode: splits by percentage, rounds each to step

**`recalc_second()`**:
1. Fetches current BG from Nightscout
2. Computes current IOB (hardcoded DIA=4h, Walsh curve)
3. Calculates: `u2_net = (meal2_u + corr2_u) - iob_now`

### Full Bolus Formula Summary

```
effective_ratio = clamp(autosens_ratio, 0.7, 1.3)
cr_eff = cr / effective_ratio
isf_eff = isf / effective_ratio

# Net carbs (after fiber deduction)
if fiber_g > threshold and deduction_enabled:
    eff_carbs = max(0, carbs_g - fiber_g × fiber_factor)
else:
    eff_carbs = carbs_g

meal_u = eff_carbs / cr_eff

# Warsaw (fat/protein)
kcal = fat_g × 9 + protein_g × 4
if kcal >= trigger and strategy != "normal":
    warsaw_u = (kcal/100 × 10 × factor_dual) / cr_eff  → later_u
else:
    warsaw_u = (kcal/100 × 10 × factor_simple) / cr_eff → meal_u

# Correction
if bg not stale:
    corr_u = min((bg - target) / isf_eff, max_correction_u)

# IOB subtraction (upfront only)
upfront_net = max(0, meal_u + warsaw_simple + corr_u - iob_u)
later_base = warsaw_dual + fiber_extension

# Exercise
reduction = lookup(minutes, intensity)
final_upfront = upfront_net × (1 - reduction)
final_later = later_base × (1 - reduction)

# Rounding + safety caps
final_upfront = smart_round(final_upfront, step, trend, max_change)
if bg < 70: final = 0
if total > max_bolus: scale down
```

---

## 4. Telegram Bot System

### Initialization (`service.py`)

**Mode Decision** (`decide_bot_mode()`):
- Render + Emergency OFF → `BotMode.DISABLED` (send-only)
- Render + Emergency ON → `BotMode.WEBHOOK` (if `PUBLIC_BOT_URL`) or `POLLING`
- NAS (no RENDER) → `BotMode.POLLING` always

**Startup**:
1. Acquire leader lock (DB-based distributed lock)
2. If lock held by another → go to DISABLED/standby
3. Create `telegram.ext.Application` (even in standby for outgoing messages)
4. Register all handlers
5. Start polling (with exponential backoff [1, 2, 5, 10, 20, 30]s) or webhook

**Webhook Guardian**: Background task every 15s in polling mode — detects and deletes rogue webhooks (split-brain protection).

### Message Processing Flow

**Handler Registration**:
```
CommandHandler: /ping, /start, /morning, /status, /capabilities, /tools, /jobs, /run, /bolo, /corrige, /whatif, /stats, /btn
MessageHandler: TEXT → handle_message, PHOTO → handle_photo, VOICE|AUDIO → handle_voice
CallbackQueryHandler: handle_callback
Error: error_handler
```

**Text Message Routing** (waterfall of interceptors):
1. Auth check (`ALLOWED_TELEGRAM_USER_ID`)
2. Bot enabled check (`user_settings.bot.enabled`)
3. Exercise flow intercept
4. Pending bolus edit intercept
5. Pending combo followup intercept
6. Rename treatment intercept
7. Save favorite intercept
8. Macro edit intercept (parses `C F P` format)
9. Basal edit intercept
10. Hardcoded commands (ping, status, debug)
11. LLM Router → `router.handle_text()` with function-calling tools

### Bolus Workflow (Bot)

1. **Entry**: `/bolo 50`, natural language, photo, or proactive detection
2. **Build Request**: resolve settings, determine meal slot by time
3. **Calculate**: `calculate_bolus_for_bot()` → `BolusResponseV2`
4. **Format Message**: structured breakdown with explain[]
5. **Save Snapshot**: `SNAPSHOT_STORAGE[request_id]` — **IN-MEMORY dict**
6. **Build Keyboard**: Accept | Edit Dose | Cancel | Dual | Exercise | Meal Slot
7. **Send with Injection Site Image**: gets next site, generates overlay, sends as photo

**User Actions**:
- **Accept** → `tools.add_treatment()` → save to DB + Nightscout → rotate injection site
- **Edit dose** → sets `editing_bolus_request` → next text = new dose → confirmation
- **Edit macros** → expects `C F P` text → recalculate → new card
- **Exercise** → multi-step: intensity → duration → recalculate with exercise flag
- **Set slot** → changes meal_slot → recalculate with different ICR/ISF
- **Cancel** → deletes treatment from DB if has origin_id

### LLM Function Calling

**18 Tools** declared in `AI_TOOL_DECLARATIONS`:
- `get_status_context`, `calculate_bolus`, `calculate_correction`, `simulate_whatif`
- `get_nightscout_stats`, `set_temp_mode`, `add_treatment`, `get_optimization_suggestions`
- `save_favorite_food`, `search_food`, `get_injection_site`, `get_last_injection_site`, `set_injection_site`
- `start_restaurant_session`, `add_plate_to_session`, `end_restaurant_session`
- `check_supplies_stock`, `update_supply_quantity`

**Dual Execution Paths**:
1. **LLM-driven**: `router.handle_text()` → LLM decides → `tools.execute_tool()`
2. **Command-driven**: `/bolo 50` → `tool_wrapper_bolo()` → `_exec_tool()` → capability registry

### Proactive Notification System (`proactive.py`)

| Event | Trigger | Cooldown |
|-------|---------|----------|
| **Basal Reminder** | Scheduled time reached; smart timing (historical avg + 35min) | Per-schedule, daily tracking |
| **Premeal Nudge** | BG > threshold AND delta > threshold | Configurable silence_minutes |
| **Combo Followup** | Dual/combo bolus detected, delay_minutes elapsed | Per-treatment, snooze support |
| **Morning Summary** | Manual `/morning` or scheduled | 60s anti-spam |
| **Trend Alert** | Slope exceeds rise/drop thresholds over window | Configurable + 6h soft mode |
| **ISF Suggestions** | New ISF suggestion generated in last 5min | 2h |
| **App Notifications** | Unread items in NotificationService | 2h |
| **Supplies Check** | Low stock (needles <10, sensors <3) | ~21h |
| **Active Plans** | Dual bolus second part is due | Per-plan (removes after firing) |
| **Post-Meal Feedback** | Meal >3h ago, asks for outcome | Per-treatment |

**Pattern**: Load config → Check enabled → Resolve chat ID → Check cooldown → Fetch data → Evaluate heuristics → Delegate to LLM Router → Send via `bot_send()` → Record status

### Leader Lock (`leader_lock.py`)

Single-row DB table (`bot_leader_lock`) with columns: `key`, `owner_id`, `acquired_at`, `expires_at`, `updated_at`.

**Acquisition**:
1. `SELECT ... FOR UPDATE` — row-level lock
2. If I am owner → renew TTL
3. If expired → steal it
4. If held by another → fail (standby)
5. If no row → INSERT (handles IntegrityError race)

**Heartbeat**: Background task sleeps `renew_seconds` (half TTL) → re-acquires lock → if fails, sets mode to DISABLED → calls shutdown()

**Instance ID**: `BOT_INSTANCE_ID` env → `RENDER_INSTANCE_ID` env → `{hostname}-{pid}`

---

## 5. Frontend Architecture

### Routing System

**Two-phase mount**:
1. **Registration** (`main.js`): `registerView(route, handler)` → lazy import `bridge.jsx` → `mountReactPage()`
2. **Resolution** (`router.js`): `hashchange` events → strip query params → auth guard → global hook
3. **Mounting** (`bridge.jsx`): `PAGE_LOADERS` maps → dynamic `import()` → mountToken for race protection → single `ReactDOM.createRoot` → ErrorBoundary + ToastContainer

**Routes**: `#/`, `#/home`, `#/scan`, `#/bolus`, `#/basal`, `#/scale`, `#/food-db`, `#/history`, `#/notifications`, `#/learning`, `#/suggestions`, `#/forecast`, `#/status`, `#/settings`, `#/nightscout-settings`, `#/login`, `#/change-password`, `#/profile`, `#/menu`, `#/bodymap`, `#/favorites`, `#/restaurant`, `#/manual`, `#/supplies`

### State Management (`store.js`)

**Proxy-based global store**:
```javascript
export const state = new Proxy(internalState, {
    set(target, prop, value) {
        if (target[prop] !== value) {
            target[prop] = value;
            notify();
        }
        return true;
    }
});
```

**React Integration** (`useStore.js`):
```javascript
export function useStore(selector = (s) => s) {
    useSyncExternalStore(subscribe, getSnapshot);
    return selector(state);
}
```

**Settings Sync**:
- `saveCalcParams()` → localStorage + `CustomEvent('bolusai-settings-changed')` + backend sync
- Conflict resolution: native `<dialog>` modal with "use server" or "overwrite server"
- `syncSettings()` on startup: fetch server → if none, push local up

**Dual Bolus Plan**: localStorage with 6h TTL, `getDualPlanTiming()` calculates elapsed/remaining

### API Client (`api.ts` + `apiClientCore.js`)

**Auth Flow**:
1. `getToken()` reads JWT from localStorage
2. `Authorization: Bearer <token>` header
3. Public endpoints skip auth
4. Missing token → dispatches `auth:logout` event
5. 401 → clears token, dispatches `auth:logout`, throws error

**Error Handling**:
- Network errors: user-friendly Spanish error
- CORS/server down: `status === 0` → specific error
- 401: auto-logout
- 409: special conflict error with server version/settings
- Bolus errors: extracts `error_code`, `required_flag` for CONFIRM_REQUIRED flow

**No retry logic** — any transient failure surfaces immediately.

### HomePage Data Fetching

| Component | Interval | Endpoint |
|-----------|----------|----------|
| GlucoseHero | 60s | `/api/nightscout/current` + `/api/forecast/current` |
| MetricsGrid | 60s | `/api/bolus/iob` + `/api/nightscout/treatments` |
| DualBolusPanel | 1s | `getDualPlan()` (localStorage) |
| RestaurantActivePanel | 5s | localStorage check |

**No SSE, no WebSocket** — polling only.

### Bolus Calculation Flow (Frontend)

1. Read `state.temp*` properties (vision, scale, favorites, restaurant)
2. Fetch glucose, IOB, favorites, check orphan carb entries
3. Auto-dual bolus if: learning hint, fat ≥ 15g, protein ≥ 20g, or vision AI suggests
4. `useBolusCalculator.calculate()`:
   - Validate inputs
   - Get calc params from store
   - Apply sick mode multiplier (0.83x on ICR/ISF)
   - Build payload
   - Call `calculateBolusWithOptionalSplit()` → POST `/api/bolus/calc`
   - If dual enabled → `createBolusPlan()` → POST `/api/bolus/plan`
5. If CONFIRM_REQUIRED → show modal → retry with flag
6. Save: build treatment → save dual plan to store → save to backend → decrement needles → navigate home

---

## 6. Background Jobs (`jobs.py`)

### Emergency Mode
Only `StabilityMonitor.check_health` runs (every minute). All other jobs skipped.

### Normal Operation

| Job | Schedule | Purpose |
|-----|----------|---------|
| `auto_night_scan` | Daily 07:00 | Overnight BG basal pattern analysis |
| `data_cleanup` | Daily 04:00 | Delete data > 90 days old |
| `learning_eval` | Every 30 min | Evaluate past meal outcomes |
| `meal_learning` | Every 30 min | Update absorption clusters |
| `ml_training_snapshot` | Every 5 min | Collect ML training features |
| `ml_training` | Daily 03:00 | Train CatBoost models |
| `ml_model_sync` | Every 30 min | Sync ML models from DB to disk |
| `guardian_check` | Every 5 min | Glucose monitoring alerts |
| `basal_reminder` | Every 45 min | Basal insulin reminders |
| `premeal_nudge` | Every 30 min | Pre-meal nudges |
| `combo_followup` | Every 30 min | Combo bolus follow-up |
| `app_notifications` | Every 2 hours | In-app notification checks |
| `isf_check` | Daily 08:00 | ISF suggestion analysis |
| `active_plans_check` | Every 2 min | Active injection plan monitoring |
| `trend_alert` | Every 10 min | BG trend alerts |
| `supplies_check` | Daily 09:00 | Supply inventory checks |

---

## 7. ML and Forecast

### Forecast Engine (`forecast_engine.py`)

Deterministic physics-based BG simulator (time-stepped, 5-min steps):

1. **Momentum**: Linear regression on recent BG series, capped at ±1.5 mg/dL/min
2. **Insulin activity**: Insulin curves (Ricker/Wieland/etc.) applied to boluses, including extended/square-wave (chunked into 5-min sub-boluses)
3. **Carb absorption**: Biexponential, triangle, or linear models with dynamic profile selection (fast/med/slow) based on fat/protein/fiber
4. **Basal drift**: Active basal vs reference basal rate
5. **Deviation correction**: Gap between observed momentum and model-predicted slope, exponential decay integration

**Anti-panic gating (V3)**: When meal + bolus pair detected (±90 min), insulin impact progressively scaled (0.35 → 1.0) over 45-120 min. Prevents false hypo predictions during post-meal absorption. Orphan boluses get gentler gating (0.75 → 1.0 over 60 min).

**Auto-harmonization**: If bolus dose exceeds declared carbs requirement, inflates effective carbs to match (trusting bolus over input), capped at 3× theoretical FPU maximum.

**Safety**: Quality degradation system, massive deviation damping (±3.5 mg/dL/min), BG clamped to [20, 600], bolus intervention detection (dampen positive deviation 80% when recent bolus > 1.5U).

### ML Inference (`ml_inference_service.py`)

**Residual approach**: CatBoost models predict *residuals* (errors) of physics model, not absolute BG.
```
Final prediction = baseline + residual
```

**Model discovery**: env-configured dir → `backend/ml_training_output` → `/app/backend/ml_training_output`

**Model loading**: `metadata.json` → horizons (e.g., [30, 60, 120, 240, 360]) + quantiles (p10, p50, p90) → `.cbm` files → `CatBoostRegressor`

**DB sync**: `sync_models_from_db()` checks `ml_models_store` table for newer versions → downloads binary → writes to disk → triggers reload

**Inference**: Features dict + baseline series → single-row DataFrame → prediction per horizon/quantile → interpolate residuals into 5-min series → add to baseline → safety clamps [20, 400]

### ML Training (`ml_training_pipeline.py`)

**Phase 1 — `build_training_snapshot()`**:
1. Fetch settings, NS config, create NS client
2. Get latest SGV (value + trend) and recent series (45 min)
3. Fetch treatments from DB (24h) and Nightscout (24h)
4. Reconcile treatments (detect overlaps and conflicts)
5. Compute IOB/COB from data store
6. Aggregate rolling totals: bolus 3h/6h, carbs 3h/6h, basal 24h/48h, exercise 6h/24h
7. Run physics forecast for baseline predictions at 5 horizons
8. Return feature dict with ~40 fields + quality flags

**Phase 2 — `persist_training_snapshot()`**:
- Creates `ml_training_data_v2` table if not exists (raw SQL DDL)
- Insert with `ON CONFLICT DO NOTHING` (idempotent per `feature_time + user_id`)
- Sanitizes timezone-aware timestamps to naive UTC

---

## 8. Nightscout Client (`nightscout_client.py`)

Stateless async HTTP client wrapping `httpx.AsyncClient`:

**Auth strategy**:
- Tokens with `.` and length > 20 → JWT Bearer
- Everything else → SHA1-hashed as `API-SECRET` header

**Clock skew**: `_update_clock_skew()` parses RFC 1123 `Date` headers → calculates offset → stored in `_clock_skew_ms` (computed but **never consumed** — dead code).

**Retry**: `get_recent_treatments()` has manual 2-retry loop with backoff (250ms → 750ms).

---

## 9. Stability Monitor (`stability_monitor.py`)

Class-method-based health checker, runs only in `EMERGENCY_MODE`:

- Polls NAS `/api/health/check` every minute
- **Hysteresis**: 2 consecutive failures → NAS down alert; 15 consecutive successes → recovery alert
- State in class attributes (`_consecutive_failures`, `_consecutive_successes`, `_is_nas_down`)

---

## 10. Rescue Sync (`rescue_sync.py`)

One-time sync on NAS startup after outage:

- Fetches last 6h treatments from Nightscout
- Upserts into local PostgreSQL
- **Dedup**: exact ID match → fuzzy match (±1 min, same insulin/carbs)
- New treatments get `[Rescue]` suffix in notes, `is_uploaded=True`

---

## 11. Identified Bugs and Issues

### Critical

| # | Issue | Location | Detail |
|---|-------|----------|--------|
| 1 | **~1000 lines dead duplicate code** | `bot/proactive.py` | `basal_reminder`, `premeal_nudge`, `combo_followup`, `trend_alert` each have 2 complete implementations. Second copy unreachable. |
| 2 | **SNAPSHOT_STORAGE is in-memory** | `bot/service.py:43` | Process restart loses all pending bolus confirmations. User clicks "Accept" after restart → "Sesión caducada." |
| 3 | **IOB = 0 fallback** | `bolus_calc_service.py:484` | When IOB unavailable and user confirms, assumes 0 active insulin — could lead to overdosing. |
| 4 | **Proxy doesn't detect nested mutations** | `store.js:89-97` | `state.scale.connected = true` won't trigger re-render. Must reassign whole object. |

### High

| # | Issue | Location | Detail |
|---|-------|----------|--------|
| 5 | **Double autosens clamping** | `calc_service.py:398` + `engine.py:151` | Clamped in both layers with potentially different bounds. |
| 6 | **DIA hardcoded = 4h** | `bolus_split.py:162` | `recalc_second` ignores user settings, always uses DIA=4, Walsh curve, peak=75. |
| 7 | **COB dedup merges nearby meals** | `iob.py:664-672` | Two meals within 5 minutes lose the smaller entry. |
| 8 | **No retry on API calls** | `apiClientCore.js` | Any transient network failure surfaces immediately to user. |
| 9 | **estimateCarbsFromImage bypasses auth error handling** | `api.ts:375` | Uses raw `fetch`, manual auth header, doesn't benefit from 401 auto-logout flow. |
| 10 | **Clock skew computed but never used** | `nightscout_client.py` | `_clock_skew_ms` tracked but no method applies it to timestamps. Dead code. |
| 11 | **Duplicate field `last_llm_ok`** | `bot/state.py:38-39` | Declared twice in BotHealthState dataclass. |
| 12 | **Duplicate `return "admin"`** | `bot/tools.py:226-228` | Unreachable second return statement. |

### Medium

| # | Issue | Location | Detail |
|---|-------|----------|--------|
| 13 | **Duration hardcoded 240min** | `bolus_engine.py:383` | All dual boluses get 4h duration regardless of Warsaw vs fiber origin. |
| 14 | **No idempotency on saveTreatment** | `useBolusCalculator.js` | Double-clicking could create duplicate treatments. |
| 15 | **useStore causes full re-render** | `useStore.js` | `getSnapshot` returns version number — every state change triggers re-render of ALL useStore components. |
| 16 | **No job overlap protection** | `jobs.py` | If job takes longer than interval, APScheduler queues second instance. No `max_instances=1`. |
| 17 | **Duplicate `await conn.commit()`** | `core/db.py:442-443` | Called twice — harmless but copy-paste error. |
| 18 | **`datetime.utcnow()` deprecated** | `core/db.py:518` | Should use `datetime.now(timezone.utc)`. |
| 19 | **Polling continues in background tabs** | `HomePage.jsx` | No visibility API integration — wastes resources when tab is hidden. |
| 20 | **localStorage.clear() on logout** | `router.js:71` | Wipes ALL localStorage including unrelated keys. |
| 21 | **No snapshot TTL/eviction** | `bot/service.py:43` | SNAPSHOT_STORAGE grows unbounded. Old snapshots only removed on accept/cancel. |
| 22 | **Race condition in basal guardrail** | `service.py:3386` | Check-then-insert pattern for basal doses has 12h window. |
| 23 | **context.user_data is per-chat** | `bot/service.py` | Exercise flows and edit states collide if two users interact simultaneously. |
| 24 | **_escape_md_v1 incomplete** | `service.py:64` | Only escapes `_`, `*`, `` ` ``, `[` — missing `]`, `(`, `)`. |
| 25 | **`momentum_duration` assigned twice** | `forecast_engine.py:81,182` | First assignment is dead code. |
| 26 | **Singleton thread safety incomplete** | `ml_inference_service.py` | `_lock` protects `get_instance()` but `load_models()` and `sync_models_from_db()` not thread-safe. |
| 27 | **Treatment reconciliation O(n²)** | `ml_training_pipeline.py` | Nested iteration over DB × NS treatments. 200 each = 40,000 comparisons. |
| 28 | **Extended bolus chunking O(n²)** | `forecast_engine.py` | 5-min chunks × simulation steps. 4h bolus (48 chunks) × 360min (72 steps) = 3,456 curve evals per bolus. |
| 29 | **`check_db_health` hardcodes "neondb"** | `core/db.py:199` | Always reports "neondb" regardless of actual database name. |
| 30 | **InMemorySession.execute() is no-op** | `core/db.py:523-528` | Returns `pass`. SQL queries in in-memory mode silently fail. |

---

## 12. Key Service Relationships

```
NightscoutClient ──┐
                   ├──> IOB Service ──> BolusCalcService ──> BolusEngine
DexcomClient   ──┘                    │
                                      ├──> AutosensService (dynamic ISF/ICR)
TreatmentRetrieval ───────────────────┤
                                      ├──> ForecastEngine (BG prediction)
                                      │       └──> MLInferenceService (CatBoost)
                                      │
                                      ├──> LearningService (meal outcomes)
                                      ├──> MealLearningService (absorption clusters)
                                      ├──> SuggestionEngine (parameter suggestions)
                                      ├──> BasalEngine (basal analysis)
                                      └──> SmartFilter (CGM compression)

Vision Service (OpenAI/Gemini) ──> Food photo analysis ──> Carbs/Fat/Protein/Fiber estimation

Telegram Bot (service.py) ──> Tools (tools.py) ──> LLM Router ──> Function calling
                           ──> Proactive (proactive.py) ──> Scheduled notifications
                           ──> Leader Lock (leader_lock.py) ──> Distributed lock
```

---

## 13. Critical Safety Design

1. **Hypo hard stop**: BG < 70 → bolus = 0
2. **IOB confirmation gate**: Unavailable/stale IOB requires explicit user confirmation (HTTP 424)
3. **Max bolus cap**: Global `max_bolus_u` limit enforced after all calculations
4. **Max correction cap**: `max_correction_u` limits correction component
5. **Max IOB ceiling**: `max_iob_u` prevents total active insulin from exceeding threshold
6. **Bolus stacking warning**: Alerts if bolus given within `min_bolus_interval_min` of previous
7. **CGM compression detection**: Flags suspected compression artifacts
8. **Stale BG guard**: BG > 10 min old → no correction calculated
9. **Techne safety override**: BG < 100 disables aggressive "ceil" rounding
10. **Anti-panic gating**: Prevents hypo alerts when pending meals haven't been absorbed
