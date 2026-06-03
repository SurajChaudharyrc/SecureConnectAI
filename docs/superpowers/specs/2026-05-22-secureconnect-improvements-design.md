# SecureConnect-AI — Hardening + Frontend Design

**Date:** 2026-05-22
**Status:** Approved (user directed: "yes... implement this")
**Scope:** Polished demo / portfolio. Local, one-command run, SQLite, real flows, dark-mode frontend.

## 1. Problem

The current repo has a broken import layout (`from models.user`, `from services.groups...` against a flat file tree), no auth, in-memory state, path-traversal risk on uploads, leaky exception messages, `CORS *` with credentials, `random.randint` for OTPs, no rate limiting, no input bounds, no security headers, no frontend, and a `/discover` endpoint that ignores the trust/domain rules defined in `group_manager.py`.

## 2. Goals

- Working, hardened FastAPI backend that actually starts.
- Real signup / login / face-verify / org-verify / discover / join / profile flows.
- Polished, accessible dark-mode frontend in vanilla HTML/CSS/JS.
- Seed data + one-command start on Windows and Unix.

## 3. Non-goals

- Real map rendering (list with distance pills is enough for a demo).
- Real email/SMS sending (OTP printed to console).
- HTTPS termination, container orchestration, multi-tenant scale.
- Replacing DeepFace or the Haversine implementation.

## 4. Repository layout

```
suraj/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app, static mount, middleware
│   │   ├── config.py          # pydantic-settings
│   │   ├── db.py              # SQLAlchemy engine/session
│   │   ├── models.py          # SQLAlchemy ORM
│   │   ├── schemas.py         # Pydantic I/O
│   │   ├── security.py        # bcrypt, session tokens, CSRF
│   │   ├── deps.py            # get_db, get_current_user
│   │   ├── errors.py          # Sanitized exception handlers
│   │   ├── middleware.py      # Security headers
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── verify.py
│   │   │   ├── org.py
│   │   │   ├── groups.py
│   │   │   └── profile.py
│   │   └── services/
│   │       ├── face.py        # DeepFace wrapper, sanitized
│   │       ├── geo.py         # haversine
│   │       ├── otp.py         # cryptographic OTP, hashed at rest
│   │       └── uploads.py     # safe file ingest (magic bytes + size)
│   ├── tests/
│   │   ├── test_auth.py
│   │   ├── test_uploads.py
│   │   ├── test_geo.py
│   │   ├── test_groups.py
│   │   └── test_org.py
│   ├── seed.py
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── index.html             # landing
│   ├── login.html
│   ├── register.html
│   ├── verify.html
│   ├── discover.html
│   ├── profile.html
│   ├── css/{tokens,base,components,pages}.css
│   ├── js/{api,auth,verify,discover,profile,ui}.js
│   └── assets/
├── start.ps1
├── start.sh
├── .env.example
└── README.md
```

FastAPI mounts `frontend/` at `/`; API lives at `/api/*`. One process, one port, one command.

## 5. Security fixes (vuln → fix)

| Vulnerability | Fix |
|---|---|
| `CORS allow_origins=["*"]` + credentials | Allowlist from config; default `http://localhost:8000` |
| Path traversal via uploaded `filename` | Discard filename; `tempfile.NamedTemporaryFile(delete=False)` in OS temp dir |
| No file validation | Magic-byte check (JPG/PNG/WEBP), max 8MB, max 4096px |
| No auth on any endpoint | Bcrypt (passlib), opaque session token in httpOnly cookie (SameSite=Lax, Secure when prod), DB-backed sessions |
| CSRF | Double-submit cookie pattern for non-GET; frontend reads `csrf_token` cookie, echoes header |
| Leaky errors | Custom 4xx/5xx handlers return generic messages; full detail logged |
| In-memory `user_db` | SQLite + SQLAlchemy, WAL mode |
| No rate limit | SlowAPI: `/verify/face` 3/min/IP, `/auth/login` 5/min, `/auth/register` 5/hr, `/org/request` 5/hr |
| `random.randint` OTP | `secrets.randbelow(10**6)`, hashed (bcrypt) before persist, 10-min TTL, max 5 attempts, single-use |
| No bounds on lat/lon | Pydantic `Field(ge=-90, le=90)` etc. |
| Username unvalidated | Regex `^[a-zA-Z0-9_]{3,32}$`, password ≥ 10 chars + complexity |
| No security headers | Middleware: HSTS (prod), CSP, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy |
| Trust score client-trustable | Server-controlled only; mutated by `/verify` outcomes |
| Domain bypass not honored on /discover | Use `get_nearby_groups` everywhere; enforce trust ≥ 0.5 |
| Anti-spoof | Keep DeepFace `anti_spoofing=True`; webcam capture sends recent timestamp + nonce to discourage replay |
| No audit log | `verification_attempts` row per attempt; structured stdout logging for security events |

## 6. Data model (SQLite via SQLAlchemy 2.x typed mappings)

- `users(id PK, username UQ, email UQ, password_hash, full_name, trust_score DEFAULT 1.0, is_face_verified BOOL, verified_domain NULL, interests JSON, current_lat NULL, current_lon NULL, created_at, last_login_at NULL)`
- `sessions(token_hash PK, user_id FK, created_at, expires_at, ip, user_agent)`
- `groups(id PK, name UQ, niche_type, latitude, longitude, radius_km, required_domain NULL, created_at)`
- `memberships(user_id, group_id, joined_at)` — composite PK
- `org_otps(id PK, email, code_hash, expires_at, used_at NULL, attempts DEFAULT 0)`
- `verification_attempts(id PK, user_id FK NULL, kind, success, ip, created_at)`

Session tokens: 32 random bytes → urlsafe b64 (~43 chars). Only **SHA-256 of the token** is stored. The plaintext lives only in the cookie.

## 7. API

```
POST /api/auth/register   { username, email, password, full_name } → 201, sets cookies
POST /api/auth/login      { username, password }                  → 200, sets cookies
POST /api/auth/logout                                              → 204
GET  /api/auth/me                                                  → current user (auth)

POST /api/verify/face          multipart: id_image, selfie         (auth, rate-limited)
POST /api/verify/org/request   { email, domain }                   (auth, rate-limited)
POST /api/verify/org/confirm   { email, code }                     (auth)

GET  /api/groups/discover      ?lat=&lon=                          (auth, trust ≥ 0.5)
POST /api/groups/{id}/join                                         (auth)
POST /api/groups/{id}/leave                                        (auth)

GET  /api/profile                                                   (auth)
PATCH /api/profile             { full_name?, interests?, lat?, lon? } (auth)
```

All write endpoints require the CSRF header. Cookies are httpOnly, SameSite=Lax.

## 8. Frontend

- **Tech:** vanilla HTML + CSS + JS. No bundler, no framework, no CDN at runtime.
- **Theme:** dark base `#0a0c14`, glass cards, cyan/violet accents, subtle gradients, soft shadows. Inter (system fallback) for UI, JetBrains Mono for accents.
- **Pages:**
  - `/` landing: hero, "how it works" three-step, feature grid, footer.
  - `/login`, `/register`: forms with inline validation.
  - `/verify`: 3-step wizard — upload ID (drag/drop), capture selfie via `getUserMedia` (or upload fallback), result card with trust score animation.
  - `/discover`: geolocation prompt (manual fallback), card list of nearby groups sorted by distance, niche-type badges, join button.
  - `/profile`: avatar/initials, trust gauge, interests chips with add/remove, org-email verification widget, location updater.
- **Components (pure CSS):** button (primary/ghost), input, card, badge, toast, modal, file-drop, stepper, gauge.
- **A11y:** keyboard navigation, visible focus, ARIA labels, prefers-reduced-motion, contrast ≥ AA.
- **Responsive:** mobile-first; grid for discover, single-column for forms.

## 9. Demo experience

- `start.ps1` / `start.sh` creates venv, installs deps, runs `python -m backend.seed`, launches `uvicorn`.
- Seed inserts: 2 users (verified `aryan_dev` with `muj.manipal.edu` domain + unverified `new_user`), 6 groups across Lucknow/Paris/Delhi/Jaipur including the MUJ alumni network.
- README documents demo creds + a one-paragraph walkthrough.

## 10. Testing

- pytest covers: auth happy + bad password, registration validation, session invalidation, file upload rejecting non-image, file upload rejecting oversized, haversine math, `get_nearby_groups` trust + domain bypass, OTP single-use + TTL, rate-limiter triggers, security headers present, CSRF rejection.
- Frontend: smoke-test by launching the server and clicking through the flow; no formal e2e suite (out of scope for demo).

## 11. Tradeoffs accepted

- SQLite (not Postgres) — single-file, zero setup, plenty for demo.
- Sessions (not JWT) — easier revocation, simpler cookie-first frontend.
- No map library — list + distance pills, keeps the bundle zero.
- Webcam selfie preferred, file upload fallback.
- DeepFace stays as the matcher; we wrap it for safety, not replace it.

## 12. Out of repo today (documented in README)

- HTTPS termination via reverse proxy.
- Real SMTP/SMS for OTP delivery.
- Background worker for embedding pre-compute.

