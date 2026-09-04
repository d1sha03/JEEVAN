# JEEVAN — Emergency Response Platform
### Authentication · Role Dashboards · CCTV/AI Backend — Implementation Report

> **Environment note (important).** This workspace did **not** contain the pre-existing
> Flutter/PostgreSQL/Redis/Docker repository referenced in the spec. Implemented here is the
> complete feature set on the parts of the stack that run in this environment:
> **real FastAPI + SQLAlchemy + JWT + RBAC + WebSockets backend** (Postgres-ready — single URL swap),
> a **web client in the existing JEEVAN design language** (the API layer is exactly what a
> Flutter/Dio client consumes — see `flutter_integration/README.md` for the GoRouter/Riverpod/Dio
> integration code), and a **pluggable AI inference service** with an HTTP hook
> (`JEEVAN_AI_URL`) plus a clearly-labeled deterministic local stub for offline operation.
> Disclosed substitutions are listed at the bottom.

---

## 1. Files created / changed

```
backend/
├── requirements.txt              # pinned deps
├── alembic.ini                   # migration config
├── migrations/
│   ├── env.py                    # targets app.models.Base.metadata
│   ├── script.py.mako
│   └── versions/0001_bootstrap.py        # initial schema
├── app/
│   ├── main.py                   # FastAPI app: REST + /ws + landing/SPA routes
│   ├── config.py                 # env-driven settings, NO hardcoded secrets
│   ├── database.py               # engine/session/get_db (swap URL → PostgreSQL)
│   ├── security.py               # PBKDF2-SHA256 (240k iters) + JWT create/decode
│   ├── rbac.py                   # ROLE_PERMISSIONS matrix, require_role/require_permission, ws_auth
│   ├── schemas.py                # pydantic request models
│   ├── models.py                 # User, EmergencyContact, Hospital, Ambulance, PoliceUnit,
│   │                             # Emergency, Dispatch, CCTVFootage, AIDetection,
│   │                             # Notification, AuditLog
│   ├── routers/
│   │   ├── auth.py               # /api/v1/auth/*
│   │   ├── cctv.py               # /api/v1/cctv/*  (upload pipeline + tracking)
│   │   └── core.py               # citizen / ambulance / hospital / police / admin APIs
│   ├── services/
│   │   ├── ai_inference.py       # SEPARATE AI service (detects only, never dispatches)
│   │   ├── emergency_engine.py   # dedup → verification gate → create → dispatch
│   │   └── ws_manager.py         # role-aware WebSocket hub (Redis adapter point)
│   └── seed.py                   # demo users/units/emergencies
├── tests/
│   ├── conftest.py               # isolated test DB + 5 role tokens
│   ├── test_auth_rbac.py         # 13 tests
│   └── test_cctv_dashboards.py   # 9 tests incl. full CCTV→dispatch flow
landing.html                      # cinematic landing (login button → /login)
platform.html                     # SPA: /login /signup /forgot-password + 5 role dashboards
flutter_integration/README.md     # GoRouter guards, Dio interceptor, Riverpod auth for the Flutter repo
```

## 2. Database migrations

```bash
cd backend
python -m alembic upgrade head          # apply 0001_bootstrap (full schema)
alembic revision --autogenerate -m "..." # future changes against live DB
```

`app.database.init_db()` (run at startup) also does `create_all` for dev convenience.
Key tables: `users`, `emergency_contacts`, `hospitals`, `ambulances`, `police_units`,
`emergencies`, `dispatches`, **`cctv_footages`** (id, uploaded_by, filename, storage_path,
file_size, mime_type, camera_id, latitude/longitude, uploaded_at, processing_status,
analysis_id, emergency_id, error, created_at, updated_at), **`ai_detections`** (id, footage_id,
detection_type, detected, confidence, severity, timestamp, latitude, longitude, model_name,
model_version, created_at), `notifications`, `audit_logs`.
Indexes on: users.email/phone/role, emergencies.created_at/status, dispatches.state,
cctv_footages.uploaded_by/processing_status, ai_detections.footage_id.

## 3. New API endpoints

| Method | Endpoint | Roles | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/login` | public | JWT login (email **or** phone) → tokens + user + role + permissions |
| POST | `/api/v1/auth/refresh` | bearer(refresh) | rotate access token |
| GET | `/api/v1/auth/me` | any | current user + permissions |
| POST | `/api/v1/auth/register` | public | citizen self-signup |
| POST | `/api/v1/auth/forgot-password` | public | 6-digit recovery code (debug code shown only when `JEEVAN_DEBUG=1`) |
| POST | `/api/v1/auth/reset-password` | public | code + new password |
| POST | `/api/v1/auth/logout` | any | audit-logged sign-out |
| POST | `/api/v1/emergencies/sos` | citizen | create verified emergency → dispatch |
| POST | `/api/v1/cctv/upload` | police, admin | multipart upload → validation → pipeline → AI |
| GET | `/api/v1/cctv` | police, admin | recent analyses |
| GET | `/api/v1/cctv/{id}` | police, admin | processing status + detection result |
| GET | `/api/v1/citizen/overview` | citizen | profile, contacts, active emergency, history, notifications |
| POST/DELETE | `/api/v1/citizen/contacts[/{id}]` | citizen | manage emergency contacts |
| GET | `/api/v1/ambulance/overview` | driver | status, queue, active mission, chain |
| POST | `/api/v1/ambulance/status` | driver | online/offline toggle (blocked mid-mission) |
| POST | `/api/v1/ambulance/missions/{id}/accept·decline` | driver | request handling (decline reassigns nearest unit) |
| POST | `/api/v1/ambulance/mission/advance` | driver | advance mission state machine |
| GET | `/api/v1/hospital/overview` | hospital | incoming patients, beds/ICU, preparedness |
| POST | `/api/v1/hospital/dispatch/{id}/prepare` | hospital | preparing ⇄ ready |
| POST | `/api/v1/hospital/capacity` | hospital, admin | bed/ICU counters |
| GET | `/api/v1/police/overview` | police | incident feed, cases, traffic, footage |
| POST | `/api/v1/police/cases/{id}/close` | police | close case (audit-logged) |
| GET | `/api/v1/admin/overview` | admin | stats, live map payload, recent, verification queue |
| GET/POST | `/api/v1/admin/users[...]` | admin | management (enable/disable, audit-logged) |
| GET | `/api/v1/admin/units` · POST `.../capacity` | admin | hospitals/ambulances/police management |
| GET | `/api/v1/admin/analytics` · `/admin/reports` | admin | trends, response times, 4 report sets |
| POST | `/api/v1/admin/emergencies/{id}/verify` | admin | manual verification gate (approve → dispatch) |
| GET | `/api/v1/notifications` · POST `/read` | any | role-scoped notifications |
| WS | `/ws?token=` | any | realtime: cctv_status, cctv_result, emergency_created, mission_state, hospital_prep, case_closed |

## 4. Frontend routes (web client)

```
/  /login  /signup  /forgot-password
/citizen  /citizen/sos  /citizen/history  /citizen/profile
/ambulance  /ambulance/mission
/hospital  /hospital/capacity
/police  /police/evidence  /police/traffic
/admin  /admin/users  /admin/units  /admin/analytics  /admin/reports  /admin/cctv
```
Frontend guard: session fetch on every navigation; role mismatch on a role URL → hard redirect
to the user's own dashboard. **Backend RBAC is the real enforcement** — every dashboard API is
role-gated independently of the frontend.

## 5. RBAC rules

| Permission | Citizen | Driver | Hospital | Police | Admin |
|---|---|---|---|---|---|
| SOS create / own history / contacts | ✔ | | | | ✔* |
| Ambulance queue/mission/online | | ✔ | | | |
| Hospital intake / capacity | | | ✔ | | ✔(capacity) |
| Incident feed / close case / traffic | | | | ✔ | |
| CCTV upload | ✗ | ✗ | ✗ | ✔ | ✔ |
| CCTV read | ✗ | ✗ | ✗ | ✔ | ✔ |
| Admin APIs (users/units/analytics/reports/verify) | ✗ | ✗ | ✗ | ✗ | ✔ |

\* admin passes `*` wildcard. Enforcement: `require_role(...)` / `require_permission(...)`
dependencies on every route + `ws_auth` on WebSocket. Verified by tests:
citizen→admin = 403, citizen→cctv = 403, citizen→police = 403, driver→hospital = 403,
hospital→admin = 403. A citizen **cannot** upload privileged CCTV footage.

## 6. Run backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m alembic upgrade head        # or skip: startup auto-creates tables
python -m app.seed                    # demo data
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# → http://localhost:8000            (landing → LOGIN → dashboards)
```

## 7. Run frontend

Already served by the same server (`/` landing, `/login`+dashboards SPA).
Environment variables: `JEEVAN_DB` (default sqlite backend/data/jeevan.db; set to PostgreSQL URL in prod),
`JEEVAN_JWT_SECRET`, `JEEVAN_ACCESS_TTL`, `JEEVAN_MAX_UPLOAD_MB`, `JEEVAN_AI_URL`, `JEEVAN_DEBUG`.

## 8. Test login

UI: open `/login` → sign in with any demo account (email or phone + password).
Demo accounts (password `Jeevan@123`): `citizen@jeevan.app`, `driver@jeevan.app`,
`hospital@jeevan.app`, `police@jeevan.app`, `admin@jeevan.app`.
API: `POST /api/v1/auth/login {"identifier":"admin@jeevan.app","password":"Jeevan@123"}`.
Error paths verified: wrong password → 401 `invalid_credentials`; deactivated account → 403
`account_disabled` (disable via Admin→Users, try logging in); network/server errors surface in the UI;
expired session → auto-refresh, then redirect to `/login?expired=1`.

## 9. Test each dashboard

Sign in with each role (URL access to other roles' dashboards redirects to your own):
- **Citizen** — big SOS → pipeline (detected → location → created → notified); check History; add a contact in Profile.
- **Ambulance** — go Online, accept the queued request, then Advance through EN ROUTE → ARRIVED → PICKED UP → HOSPITAL ARRIVAL → COMPLETED.
- **Hospital** — incoming patient card (details/ETA/required resources) → Prepare → Ready; adjust beds/ICU.
- **Police** — live feed, close a case, Evidence viewer (CCTV results), traffic panel.
- **Admin** — stats, live map blips, Users (disable `citizen@jeevan.app` → verify login is blocked), Units, Analytics, Reports, **CCTV/AI**.

## 10. Upload CCTV footage

Admin → **CCTV / AI** (or Police → **Evidence viewer**) → drag & drop / choose an MP4/AVI/MOV ≤ 100 MB →
watch UPLOADING (progress %) → UPLOADED → PROCESSING → AI ANALYSIS → RESULT.
API equivalent:
```bash
curl -H "Authorization: Bearer $POLICE_TOKEN" -F "file=@camera_01.mp4" \
     -F "camera_id=CAM-07" -F "latitude=30.9089" -F "longitude=75.8538" \
     http://localhost:8000/api/v1/cctv/upload
```
Invalid type → 415; oversized → 413; citizen attempt → 403.

## 11. Test AI processing

Pipeline runs as a background task: status broadcasts hit the admin/police dashboards live over
WebSocket; result shows detection, confidence, severity, timestamp, location, incident ID, and the
verification decision. Detections ≥ 0.90 confidence are **auto-verified and dispatched** (you should
see the ambulance queue, hospital intake and police feed update); lower-confidence detections land in
the admin **verification queue** for manual Approve/Reject; duplicates within ~500 m / 10 min are
suppressed. The AI service is separate from the engine (`app/services/ai_inference.py`) and returns
the exact standardized payload from the spec; point `JEEVAN_AI_URL` at a real model server to swap
the stub — no other code changes.

## 12. Remaining limitations

1. **Flutter client** — this environment cannot run the Flutter toolchain; the web client consumes
   the identical API. `flutter_integration/README.md` contains the GoRouter guards, Dio interceptor
   (refresh/401 handling), and Riverpod auth controller to drop into the real app.
2. **SQLite (dev)** — swap `JEEVAN_DB` to a PostgreSQL URL for production; models are portable.
3. **AI stub** — deterministic hash-based analyzer labeled `jeevan-vision-stub`; not a real model.
4. **Google Maps** — dashboards render a dark SVG operations map with live blips; the Maps SDK slot
   is marked in the UI (needs an API key).
5. **Redis** — replaced by an in-process WS hub with a documented adapter point; multi-worker
   deployments need the Redis adapter.
6. **Recovery codes** — surfaced in API responses only while `JEEVAN_DEBUG=1` (no SMS/email provider here).
7. **mypy** — sandbox lacks the full typing stub chain; `ruff` (E9,F) and `pytest` (22/22) pass clean.

**STOP — awaiting your confirmation.**
