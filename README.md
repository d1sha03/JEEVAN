# JEEVAN — Emergency Response Platform

Dark, cinematic emergency-response system: an accident is detected, verified, and
ambulance + hospital + police are dispatched — in seconds.

This repository contains **three things**:

| Part | What it is | Where |
|---|---|---|
| **Landing experience** | Cinematic scroll-story (JEEVAN intro → crash → silence → response → "No calls. No waiting.") that ends in a login card | `landing.html` |
| **Web platform** | Full login/signup/forgot-password + 5 role dashboards (Citizen, Ambulance, Hospital, Police, Admin) + CCTV/AI upload | `platform.html` |
| **API backend** | FastAPI + SQLAlchemy: JWT auth, RBAC (5 roles), emergency engine with dedup & verification gate, CCTV upload pipeline, pluggable AI inference service, WebSocket live events, Alembic migrations, pytest suite | `backend/` |

The web client talks to the backend over a documented REST + WebSocket API, so a
Flutter/mobile client can consume the exact same endpoints (see
`flutter_integration/README.md`).

---

## Quickstart

**Prerequisites:** Node 18+ and **Python 3.11+** ([python.org](https://www.python.org/downloads/) — on Windows tick *“Add python.exe to PATH”*). No database server needed.

```bash
npm install          # also bootstraps everything on first run (venv + deps + DB + demo data)
npm run dev          # → http://localhost:8000
```

That's it. The npm scripts create an **isolated Python environment** at `backend/.venv`
automatically — they never touch your system Python or other projects' venvs.
If something is missing, `npm run dev` self-heals by re-running the bootstrap
before starting.

Plain Python (no Node) equivalent:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows      (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m alembic upgrade head
python -m app.seed
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**

- `http://localhost:8000/` → the landing experience (scroll it, then hit **Login**)
- `http://localhost:8000/login` → straight to the platform sign-in
- `http://localhost:8000/docs` → interactive API documentation (Swagger)

## Demo accounts

Password for all: **`Jeevan@123`**

| Role | Email (or phone) |
|---|---|
| Citizen | `citizen@jeevan.app` (+91 90000 00001) |
| Ambulance driver | `driver@jeevan.app` (+91 90000 00002) |
| Hospital staff | `hospital@jeevan.app` (+91 90000 00003) |
| Police officer | `police@jeevan.app` (+91 90000 00004) |
| Administrator | `admin@jeevan.app` (+91 90000 00005) |

Login accepts **email or phone** + password. Roles redirect to their own dashboards,
and every API is role-gated server-side (a citizen token cannot touch admin/police/
hospital/ambulance-management or CCTV APIs — that returns `403`).

## Try the full loop (5 minutes)

1. **Landing → Login** as `admin@jeevan.app`.
2. Go to **CCTV / AI** → drag any `.mp4` (≤ 100 MB) into the uploader.
3. Watch the pipeline: `UPLOADING → UPLOADED → PROCESSING → AI ANALYSIS → RESULT`.
4. The AI returns detection + confidence + severity. Detections ≥ 90 % confidence are
   **auto-verified**: an emergency is created and dispatched. Lower-confidence ones wait
   in the admin **verification queue** (Approve / Reject). Duplicates within ~500 m /
   10 min are suppressed.
5. Sign out → login as `driver@jeevan.app` → the request is in the **queue** →
   **Accept** → **Advance** through `EN ROUTE → ARRIVED → PATIENT PICKED UP →
   HOSPITAL ARRIVAL → MISSION COMPLETED`.
6. Sign in as `hospital@jeevan.app` — incoming patient, ETA, preparation state, ICU/beds.
7. Sign in as `police@jeevan.app` — incident feed, evidence viewer (the CCTV analyses),
   traffic panel, close cases.
8. Back as `admin` — stats, live map blips, users (try disabling `citizen@`, then check
   their login is blocked), analytics, reports.
9. Or press the big **SOS** button as the citizen — same engine, instant dispatch.

Everything updates live over the WebSocket (`/ws`) — toasts appear on whichever
dashboard is open when events fire.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `JEEVAN_DB` | `sqlite:///backend/data/jeevan.db` | Any SQLAlchemy URL — use PostgreSQL in production |
| `JEEVAN_JWT_SECRET` | generated & persisted to `backend/data/.jwt_secret` | **Set this in production** |
| `JEEVAN_ACCESS_TTL` | `1800` | Access-token lifetime (seconds) |
| `JEEVAN_REFRESH_TTL` | `2592000` | Refresh-token lifetime (seconds) |
| `JEEVAN_MAX_UPLOAD_MB` | `100` | CCTV upload size limit |
| `JEEVAN_AI_URL` | *(empty → local stub)* | URL of a real AI inference service (receives multipart `file`, returns the standardized detection JSON) |
| `JEEVAN_AI_DELAY` | `0.5` | Demo pacing between pipeline stages |
| `JEEVAN_DEBUG` | `1` | Dev mode (shows password-reset codes in API responses). **Set `0` in production.** |

## Tests & lint

```bash
npm run test        # 22 tests: auth, RBAC, CCTV→dispatch flow, dashboards
npm run lint        # critical lint pass (ruff)
```

(Or from `backend/`: `python -m pytest tests -q` · `python -m ruff check app tests --select E9,F`.)

## All npm scripts

| Script | What it does |
|---|---|
| `npm run setup` | Bootstrap: isolated venv at `backend/.venv` + Python deps + migrations + demo seed (idempotent; also runs on `npm install` and before `dev`) |
| `npm run dev` | Hot-reload server on port 8000 (auto-bootstraps if needed; `PORT` env to change port) |
| `npm start` | Same, production mode (no reload) |
| `npm run seed` | Re-seed demo data |
| `npm run migrate` | Apply Alembic migrations |
| `npm test` / `npm run lint` | Test suite / lint |

## Migrations

```bash
cd backend
python -m alembic upgrade head                        # create/upgrade schema
alembic revision --autogenerate -m "change something" # after model changes
```

(For a quick dev start you can skip this — the app also auto-creates tables on boot.)

## Production notes

- **Database:** set `JEEVAN_DB=postgresql+psycopg://user:pass@host/jeevan` (models are portable).
- **Secrets:** set `JEEVAN_JWT_SECRET` (e.g. `python -c "import secrets;print(secrets.token_hex(32))"`)
  and `JEEVAN_DEBUG=0`.
- **Server:** run behind a reverse proxy, e.g.
  `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`
  (with multiple workers, wire the Redis adapter noted in
  `backend/app/services/ws_manager.py` so WebSocket events fan out across processes).
- **AI service:** point `JEEVAN_AI_URL` at your model server. Contract — it receives the
  footage as multipart `file` plus `camera_id/latitude/longitude` form fields and must
  return:

  ```json
  {
    "detected": true,
    "confidence": 0.94,
    "severity": "critical",
    "timestamp": "2026-01-01T00:00:00Z",
    "location": {"latitude": 31.326, "longitude": 75.576}
  }
  ```

  The AI service **only detects** — the backend's emergency engine handles dedup,
  the verification gate, and dispatch.
- **CORS:** currently open for development; lock `allow_origins` in `backend/app/main.py`.

## Project layout

```
├── landing.html              # cinematic one-page experience (self-contained)
├── platform.html             # SPA: auth pages + 5 dashboards + CCTV uploader
├── index.html                # convenience redirect to landing.html
├── flutter_integration/      # GoRouter guards, Dio interceptor, Riverpod auth
└── backend/
    ├── requirements.txt
    ├── alembic.ini + migrations/
    ├── app/
    │   ├── main.py           # FastAPI app (REST + /ws + page routes)
    │   ├── config.py  database.py  security.py  rbac.py  schemas.py  models.py  seed.py
    │   ├── routers/          # auth.py · cctv.py · core.py (dashboards, SOS, admin)
    │   └── services/         # ai_inference.py · emergency_engine.py · ws_manager.py
    ├── tests/                # pytest suite (22)
    └── data/                 # SQLite DB + uploaded footage (created at runtime)
```

## Troubleshooting

- **`ModuleNotFoundError: No module named 'sqlalchemy'`** — dependencies aren't installed.
  Run `npm run setup` (or `npm install`), then `npm run dev`. The scripts use their own
  `backend/.venv`, so this cannot come from a missing global install.
- **`python` resolves to the wrong environment** (e.g. another project's venv on PATH) —
  solved by design: all scripts execute via `backend\.venv\Scripts\python.exe`
  (Windows) or `backend/.venv/bin/python` (macOS/Linux).
- **`Python 3.11+ not found`** — install from python.org, tick *Add to PATH* (Windows),
  open a **new** terminal, run `npm run setup`.
- **Port 8000 busy** — `PORT=3000 npm run dev` (macOS/Linux) or
  `set PORT=3000 && npm run dev` (Windows).
- **Login says "account disabled"** — that user was disabled in Admin → Users; re-enable
  there, or delete `backend/data/jeevan.db` and run `npm run seed` for a fresh dataset.
- **CCTV upload rejected** — only MP4/AVI/MOV, ≤ 100 MB.
- **WebSocket shows "Reconnecting"** — it retries automatically every 4 s; make sure the
  page is opened through the same host serving the API.
