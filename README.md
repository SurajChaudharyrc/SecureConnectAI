# SecureConnect-AI

> Hyperlocal, trust-aware social network with face-based identity verification and
> organization-validated access control. Decentralized — no admins required.

[![python](https://img.shields.io/badge/python-3.12-3776AB.svg)](https://www.python.org/)
[![fastapi](https://img.shields.io/badge/api-fastapi-009688.svg)](https://fastapi.tiangolo.com/)
[![sqlite](https://img.shields.io/badge/db-sqlite-003B57.svg)](https://www.sqlite.org/)
[![tests](https://img.shields.io/badge/tests-31%20passing-5dd29c.svg)](#testing)
[![license](https://img.shields.io/badge/license-MIT-444.svg)](#license)

---

## What's inside

- **Backend** — FastAPI + SQLAlchemy 2 + SQLite. Session auth with bcrypt-hashed passwords, double-submit CSRF, strict security headers, SlowAPI rate limiting, and sanitized error handlers.
- **Identity** — DeepFace Siamese matching with anti-spoofing enabled by default. Uploads are magic-byte validated, size-capped, and discard client filenames.
- **Geo** — custom Haversine implementation (no map library). Trust-gated discovery + organization domain bypass for global trust networks.
- **Frontend** — vanilla HTML/CSS/JS, no bundler, no framework. Dark glass UI with smooth animations, webcam selfie capture, and full keyboard accessibility.
- **Tests** — 31 pytest cases covering auth, uploads (incl. path traversal), geo, group rules, OTP lifecycle, CSRF, and security headers.

## Quick start

```powershell
# Windows
.\start.ps1
```

```bash
# macOS / Linux
./start.sh
```

The script creates a venv, installs deps, seeds demo data, and serves the app at **http://localhost:8000**. First run installs TensorFlow/DeepFace which takes a few minutes; subsequent runs are near-instant.

### Demo credentials

| Username    | Password        | State                                       |
|-------------|-----------------|---------------------------------------------|
| `aryan_dev` | `DemoPass1234`  | Face-verified, MUJ alumni domain verified.  |
| `new_user`  | `DemoPass1234`  | Fresh account, no verifications yet.        |

### Demo walkthrough (≈ 2 minutes)

1. Open `http://localhost:8000/` and click **Sign in as demo**.
2. Log in as `aryan_dev` / `DemoPass1234`.
3. Visit **Discover** and click **Use my location** — or enter `26.8467, 80.9462` (Lucknow) manually.
4. You'll see proximity-based groups plus the **MUJ Alumni Network**, which shows up regardless of distance because Aryan's organization domain is verified.
5. Visit **Profile** to see the trust gauge, edit interests, or run an org verification flow (the OTP prints to the terminal running the server).
6. Visit **Verify** with `new_user` to walk through the ID + webcam selfie flow.

## Repository layout

```
suraj/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, middleware, static mount
│   │   ├── config.py         # pydantic-settings (.env loaded)
│   │   ├── db.py             # SQLAlchemy 2 engine + WAL mode
│   │   ├── models.py         # Typed mappings: User, Session, Group, …
│   │   ├── schemas.py        # Pydantic request/response models
│   │   ├── security.py       # bcrypt, session tokens, CSRF, OTP
│   │   ├── deps.py           # get_current_user, require_csrf
│   │   ├── errors.py         # Sanitized exception handlers
│   │   ├── middleware.py     # Security-headers middleware
│   │   ├── rate_limit.py     # Single shared SlowAPI Limiter
│   │   ├── routers/          # auth, verify, org, groups, profile
│   │   └── services/         # face, geo, otp, uploads
│   ├── tests/                # 31 pytest cases
│   ├── seed.py               # Idempotent demo seed
│   └── requirements.txt
├── frontend/
│   ├── index.html            # Landing
│   ├── login.html, register.html
│   ├── verify.html           # 3-step wizard (ID + webcam + result)
│   ├── discover.html         # Geo + niche cards
│   ├── profile.html          # Trust gauge + org verify + interests
│   ├── css/{tokens,base,components,pages}.css
│   ├── js/{api,auth,verify,discover,profile,ui}.js
│   └── assets/favicon.svg
├── docs/superpowers/specs/   # Design spec
├── start.ps1 / start.sh      # One-command setup
└── README.md
```

## Architecture

```
Browser ──┬── /        ──► static (index.html)
          ├── /login   ──► static (login.html)
          ├── /verify  ──► static (verify.html)
          ├── /discover/profile/...
          └── /api/*   ──► FastAPI routers
                            ├── auth.py    (register/login/logout/me/csrf)
                            ├── verify.py  (face matching, anti-spoofing)
                            ├── org.py     (org OTP request/confirm)
                            ├── groups.py  (discover/join/leave)
                            └── profile.py (read/update profile)
                                  │
                                  ▼
                            services/ (geo, face, otp, uploads)
                                  │
                                  ▼
                            SQLAlchemy 2.x ──► SQLite (WAL)
```

Static assets are served at `/css/*`, `/js/*`, `/assets/*`. API at `/api/*`. The auto-generated OpenAPI explorer lives at `/api/docs`.

## Security posture

| Concern | What we do |
|---|---|
| Password storage | Bcrypt via passlib (cost 12 default). |
| Session tokens | Random 32-byte token, stored as SHA-256 in DB. Cookie is httpOnly + SameSite=Lax (+ Secure in prod). |
| CSRF | Double-submit cookie pattern. `X-CSRF-Token` header required on all non-GET requests; verified with `itsdangerous` signing. |
| Rate limiting | SlowAPI per-IP: `/auth/login` 10/min, `/auth/register` 5/hr, `/verify/face` 3/min, OTP request 5/hr. |
| File uploads | Magic-byte allowlist (JPG/PNG/WEBP), 8 MB cap, OS temp file via `tempfile.mkstemp` — **client filenames are discarded** (no path-traversal surface). |
| OTPs | `secrets.randbelow(10**6)`, hashed at rest, 10-minute TTL, single-use, 5-attempt cap. |
| Input bounds | Pydantic constraints: usernames `^[a-zA-Z0-9_]{3,32}$`, password ≥ 10 chars with letters + digits, lat/lon ranges enforced. |
| Error responses | Custom handlers return generic messages; full detail logs to the server only. |
| Headers | CSP (no inline JS), X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy strict-origin-when-cross-origin, Permissions-Policy locked down, HSTS in prod, COOP/CORP same-origin. |
| CORS | Exact allowlist (no `*`); credentials require an explicit origin. |
| Face matching | DeepFace `anti_spoofing=True`; on failure the trust score decrements. |
| Trust score | Server-controlled only; never accepted from clients. |

## API

```
POST /api/auth/register   { username, email, password, full_name } → sets cookies
POST /api/auth/login      { username, password }                   → sets cookies
POST /api/auth/logout                                              → 204
GET  /api/auth/me                                                  → current user
GET  /api/auth/csrf                                                → refresh CSRF cookie

POST /api/verify/face          multipart: id_image, selfie         (auth)
POST /api/verify/org/request   { email, domain }                   (auth)
POST /api/verify/org/confirm   { email, code }                     (auth)

GET  /api/groups/discover      ?lat=&lon=                          (auth, trust ≥ 0.5)
POST /api/groups/{id}/join                                         (auth)
POST /api/groups/{id}/leave                                        (auth)

GET  /api/profile                                                  (auth)
PATCH /api/profile             { full_name?, interests?, lat?, lon? } (auth)

GET  /api/health                                                   liveness probe
```

Full schema explorer: `http://localhost:8000/api/docs` once the server is running.

## Testing

```bash
.venv/bin/pytest backend/tests
```

```
31 passed in ~9s
```

Coverage spans:

- Auth — registration, login, logout, /me, duplicate detection, weak password rejection.
- Uploads — JPG/PNG accepted, oversized rejected, non-image rejected, tiny files rejected, **path-traversal filenames stripped**.
- Geo — known distances (Paris↔Delhi ≈ 6595 km), short distances, NaN rejected.
- Groups — proximity discovery, domain bypass, trust-gate enforcement, join authorization.
- OTP — happy path, wrong code, single-use, expiry, attempt cap.
- Security — bcrypt round-trip, session tokens hashed, CSRF signed roundtrip, headers present on every response, CSRF rejection on missing header, double-submit succeeds.

## Configuration

`backend/.env` (created from `.env.example` on first run):

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `prod` enables HSTS and `Secure` cookies. |
| `APP_SECRET` | (set by user) | Used to sign CSRF tokens. Must be ≥ 32 chars. |
| `DATABASE_URL` | `sqlite:///./secureconnect.db` | Swap for Postgres in prod. |
| `ALLOWED_ORIGIN` | `http://localhost:8000` | Exact origin for CORS. |
| `SESSION_TTL_HOURS` | `24` | |
| `OTP_TTL_MINUTES` | `10` | |
| `MAX_UPLOAD_BYTES` | `8388608` | 8 MB per file. |
| `DEEPFACE_ENABLED` | `true` | Set `false` to skip TensorFlow init. |
| `LOG_LEVEL` | `INFO` | |

## Not covered (deliberately)

These are documented out of scope for the demo:

- HTTPS termination — use a reverse proxy (Caddy / nginx) in production.
- Real SMTP/SMS — OTP currently prints to the server console. Wire up your provider in `routers/org.py`.
- Maps — discovery is a sorted list with distance pills; add Leaflet/Mapbox if needed.
- Background workers — face embeddings are computed inline; consider Celery / RQ for scale.

## License

MIT — see [LICENSE](LICENSE) (drop one in to your liking).
