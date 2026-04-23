# CLAUDE.md — Bolus AI

## Project Overview

Bolus AI is an intelligent diabetes management assistant that calculates insulin boluses, analyzes food photos with AI vision, and synchronizes with Nightscout. It features a dual-architecture deployment model: a primary NAS instance (Docker via Portainer) and a cloud-based Render + Neon backup, with periodic DB sync from NAS to Neon and automatic failover detection.

## Modo Restaurante (Carta)

Funcionalidad para comidas en restaurante con múltiples platos y absorción lenta:

**Flujo completo:**
1. **Foto de la carta/menú** → Gemini estima HC totales del menú completo (grasas, proteínas, HC)
2. **Cálculo de bolo dual/extendido** → Útil para comidas largas con alta grasa
3. **Usuario inyecta bolo inicial** → Basado en estimación de la carta
4. **Cada plato servido** → Foto individual → Gemini estima HC reales de ESE plato
5. **Acumulación secuencial** → Suma platos servidos vs estimado inicial
6. **Al finalizar** → Comparación esperado vs real → sugiere ajuste (micro-bolo o carbohidratos)

**Archivos clave:**
- `backend/app/api/restaurant.py` — Endpoints: `analyze_menu`, `analyze_menu_text`, `analyze_plate`, `compare_plate`
- `backend/app/services/restaurant.py` — Lógica de visión (Gemini), guardrails, sugerencias
- `backend/app/models/restaurant_session.py` — persistencia en BD (`restaurant_sessions_v2`)
- `frontend/src/pages/RestaurantPage.jsx` — Página principal
- `frontend/src/components/restaurant/RestaurantSession.jsx` — Componente de sesión
- `frontend/src/lib/restaurantApi.js` — Cliente API

**Seguridad:**
- Usa ISF del usuario (no hardcoded) para calcular ajustes
- Check de IOB antes de sugerir insulina adicional (alerta si IOB > 0.5U)
- Confianza mínima (default 0.55) para sugerir acciones
- Delta mínimo de 8g HC para recomendar acción

**Endpoints:**
```
POST /api/restaurant/analyze_menu      # Foto de carta → HC totales
POST /api/restaurant/analyze_menu_text # Texto de menú → HC totales
POST /api/restaurant/analyze_plate     # Foto de plato → HC individuales
POST /api/restaurant/compare_plate     # Esperado vs Real → Ajuste sugerido
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI 0.111, Uvicorn, SQLAlchemy 2.0 (async) |
| Database | PostgreSQL (asyncpg) primary, SQLite (aiosqlite) fallback |
| Frontend | React 19, Vite 7, JavaScript/JSX, wouter (hash routing) |
| Bot | python-telegram-bot 21.4, OpenAI GPT for conversational AI |
| ML | CatBoost, pandas, numpy |
| Vision | OpenAI GPT-4o or Google Gemini for food photo analysis |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Testing | pytest 8.2 (backend), Jest (frontend) |

## Repository Structure

```
bolus_ai/
├── backend/
│   ├── app/
│   │   ├── api/           # 28 FastAPI route modules
│   │   ├── bot/           # Telegram bot (service, tools, proactive, AI, webhook)
│   │   ├── services/      # 42 business logic services
│   │   ├── models/        # 28 SQLAlchemy models + Pydantic schemas
│   │   ├── dtos/          # Data transfer objects
│   │   ├── core/          # DB, auth, config, migrations, logging
│   │   ├── utils/         # Utility functions
│   │   └── main.py        # FastAPI app, startup/shutdown, SPA serving
│   ├── tests/             # 69+ pytest test files
│   ├── alembic/           # Database migrations
│   ├── requirements.txt   # Python dependencies
│   └── Dockerfile         # Python 3.11 slim container
├── frontend/
│   ├── src/
│   │   ├── pages/         # 23 page components
│   │   ├── components/    # Reusable React components
│   │   ├── modules/       # Router and store modules
│   │   ├── lib/           # API client, feature flags, food DB
│   │   ├── hooks/         # Custom React hooks
│   │   └── styles/        # CSS styling
│   ├── tests/             # Frontend tests
│   ├── vite.config.js     # Vite config (dev proxy to :8000)
│   └── package.json       # Node dependencies
├── config/                # config.json, nginx.conf
├── docs/                  # 28 documentation files
├── scripts/               # Migration and utility scripts
├── deploy/                # NAS deployment configs
├── docker-compose.yml     # Local dev stack (backend + nginx)
├── render.yaml            # Render.com deployment
├── build_render.sh        # Render build script
└── pytest.ini             # Pytest configuration
```

## Common Commands

### Backend

```bash
# Run backend (dev)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
pytest backend/tests/ -q

# Run specific test file
pytest backend/tests/test_bolus_calc.py -v

# Run tests matching a pattern
pytest backend/tests/ -k "test_iob"

# Run with async mode explicitly
pytest backend/tests/ --asyncio-mode=auto -q
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # Dev server on :5173, proxies /api to :8000
npm run build      # Production build to dist/
npm run preview    # Preview built site
npm run smoke      # Smoke test
```

### Docker

```bash
docker-compose up --build    # Full local stack
```

### Production Build (Render)

```bash
./build_render.sh   # npm ci + vite build + pip install + copies dist to backend/app/static/
```

## Testing Conventions

- **Framework:** pytest with `asyncio_mode = auto` (see `pytest.ini`)
- **Test directory:** `backend/tests/`
- **Conftest:** `backend/tests/conftest.py` sets up test env vars (SQLite test DB, dummy keys)
- **Fixtures:** Session-scoped `_init_test_db` auto-creates tables and seeds admin user
- **Async tests:** Use `@pytest.mark.asyncio` — mode is auto so it's optional
- **HTTP mocking:** Use `respx` for httpx-based services (Nightscout, Dexcom)
- **Mocking:** Use `pytest-mock` / `unittest.mock.patch` for service isolation
- **Test naming:** `test_<module>_<scenario>.py` or `test_<feature>.py`

### Key environment variables set by conftest:
```
JWT_SECRET=test-secret-autofix-12345
DATABASE_URL=sqlite+aiosqlite:///...test.db
VISION_PROVIDER=none
APP_SECRET_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=
```

## Architecture Patterns

### Backend Layers

1. **Routes** (`app/api/`) — FastAPI routers, request validation, dependency injection
2. **Services** (`app/services/`) — Business logic, stateless where possible
3. **Models** (`app/models/`) — SQLAlchemy ORM models + Pydantic DTOs
4. **Core** (`app/core/`) — DB engine, settings, auth, migrations, logging

### Dependency Injection

```python
@router.post("/calculate")
async def calculate(
    payload: BolusRequestV2,
    db: AsyncSession = Depends(get_db_session),
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
```

### Configuration Hierarchy (lowest to highest priority)

1. Pydantic model defaults in `app/core/settings.py`
2. `config/config.json` file values
3. Environment variables (override everything)

### Database

- **NAS:** Local PostgreSQL with `asyncpg` (source of truth)
- **Render:** Neon PostgreSQL with `asyncpg` (cloud backup, synced from NAS every 4h)
- **Tests/local dev:** SQLite with `aiosqlite` (via conftest.py)
- **Migrations:** Alembic (`backend/alembic/`) + idempotent startup schema fixes in `app/core/migration.py`
- All DB access is async via `AsyncSession`

### Startup Sequence (`app/main.py`)

1. Create data directory, validate secrets (JWT_SECRET, APP_SECRET_KEY)
2. Import models, init DB engine, wait for DB readiness with retry
3. Create tables, run schema migration fixes
4. Background tasks: rescue sync from Nightscout, ML model sync, admin seed
5. Setup APScheduler periodic jobs, initialize Telegram bot

### Frontend Serving

In production, `build_render.sh` copies the Vite build output into `backend/app/static/`. FastAPI serves it as a SPA with a catch-all route. `index.html` is served with `no-cache` headers.

## Key Services

| Service | File | Purpose |
|---------|------|---------|
| Bolus calculation | `bolus_calc_service.py` | Core insulin dose calculation |
| IOB engine | `iob.py` (3600+ lines) | Insulin-on-board with multiple curve models |
| Basal engine | `basal_engine.py` | Basal rate analysis and suggestions |
| Forecast engine | `forecast_engine.py` | Blood glucose prediction |
| Nightscout client | `nightscout_client.py` | Bidirectional Nightscout sync |
| Vision service | `vision.py` | Food photo analysis (OpenAI/Gemini) |
| ML pipeline | `ml_training_pipeline.py` | CatBoost model training |
| ML inference | `ml_inference_service.py` | Model loading + prediction |
| Telegram bot | `bot/service.py` (3600+ lines) | Bot handler, message processing |
| Bot tools | `bot/tools.py` (3000+ lines) | LLM function-calling tools |
| Proactive alerts | `bot/proactive.py` (3000+ lines) | Proactive notifications |
| Autosens | `autosens_service.py` | Insulin sensitivity detection |
| Learning | `learning_service.py` | Meal pattern learning |

## Critical Environment Variables

```bash
# Required
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
JWT_SECRET=<min-16-chars>
APP_SECRET_KEY=<base64-encoded-32-byte-key>
NIGHTSCOUT_BASE_URL=https://yourname.nightscout.cloud
NIGHTSCOUT_API_SECRET=<secret>

# Vision AI (at least one)
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
VISION_PROVIDER=openai   # or gemini

# Telegram Bot
TELEGRAM_BOT_TOKEN=<token>
ALLOWED_TELEGRAM_USER_ID=<user-id>
ENABLE_TELEGRAM_BOT=true

# Optional
DEXCOM_USERNAME=...
DEXCOM_PASSWORD=...
DEXCOM_REGION=ous
ML_TRAINING_ENABLED=false
EMERGENCY_MODE=false
```

## Coding Conventions

- **Language:** Backend Python, frontend JavaScript/JSX (no enforced TypeScript)
- **Async:** All backend DB and HTTP operations are async/await
- **Comments/docs:** Some docstrings and comments are in Spanish
- **No linter config:** No ESLint/Prettier/ruff enforced — follow existing style
- **Error handling:** HTTPException with descriptive messages, structured logging
- **Logging:** `logging.getLogger(__name__)` or `logging.getLogger("uvicorn")`
- **Pydantic v2:** Used for all request/response schemas and settings
- **SQLAlchemy 2.0:** Declarative models with `Mapped[]` type annotations

## Dual-Instance Architecture (HA / Failover)

### Instances

| | NAS (primary) | Render (backup) |
|---|---|---|
| **Hosting** | Docker container via Portainer on home NAS | Render.com cloud service |
| **Database** | Local PostgreSQL | Neon (cloud PostgreSQL) |
| **Telegram bot** | Dedicated bot token, always POLLING mode | Separate bot token, DISABLED (send-only) in standby |
| **State** | Always active, runs all background jobs | Standby by default; activates on NAS failure |
| **Disk** | Persistent Docker volumes | 1GB attached disk (`/var/data`) |

### Two Telegram Bots

There are **two separate Telegram bots** (each with its own token):
- **NAS bot:** Always active in POLLING mode (`forced_polling_on_prem`)
- **Render bot:** Disabled (send-only) in normal operation; activates as WEBHOOK or POLLING when `EMERGENCY_MODE=true`

Bot mode selection logic (`bot/service.py`):
- `RENDER` env var detected + `EMERGENCY_MODE=false` → `BotMode.DISABLED` (send-only for alerts)
- `RENDER` env var detected + `EMERGENCY_MODE=true` → `BotMode.WEBHOOK` or `BotMode.POLLING`
- NAS (no `RENDER` env var) → `BotMode.POLLING` always

### Database Sync (NAS → Neon)

- A `bolus_backup_cron` container in the NAS Docker stack runs `scripts/migration/backup_to_neon.sh` every 4 hours
- Syncs the NAS database to Neon (unidirectional: NAS → Neon)
- **Safety valve:** Before syncing, checks if Neon has `treatment_audit_log` records created during Emergency Mode in the last 24h. If detected, the backup **aborts** and sends a critical Telegram alert to prevent overwriting emergency data

### Failover Flow

1. Render app periodically checks NAS health via the Stability Monitor (`app/services/stability_monitor.py`)
2. If NAS is detected as down, the Render bot sends a Telegram alert
3. **Manual activation:** Set `EMERGENCY_MODE=true` in Render environment variables (auto-restarts the service)
4. Render bot activates fully, processes Telegram commands, runs only the Stability Monitor job (all other periodic jobs disabled)
5. On NAS recovery: set `EMERGENCY_MODE=false` on Render, NAS resumes via rescue sync from Nightscout (`rescue_sync.py` fetches last 6h of treatments to restore IOB/COB)

### Leader Lock (BotLeaderLock)

Database-backed distributed lock (`app/bot/leader_lock.py`, model in `app/models/bot_leader_lock.py`) prevents both bots from processing messages simultaneously:
- Lock has a TTL with heartbeat renewal (every half-TTL)
- If the leader dies, the lock expires and the other instance can acquire it ("stolen")
- On shutdown, the lock is released immediately
- A **webhook guardian** task runs every 15s to detect and delete rogue webhooks from a competing instance

## Safety Design

- Anti-panic logic prevents hypo alerts when pending meals haven't been absorbed
- IOB/COB calculations validated before dosing recommendations
- ML model training gated on data quality (>1000 samples, >3 days, <40 RMSE)
- Emergency mode restricts to monitoring-only
- Nightscout API secrets encrypted at rest (AES-256)
