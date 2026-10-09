# 🔧 Backend - Django REST API

A robust Django REST Framework API powering the CareerHub job search platform.

![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![DRF](https://img.shields.io/badge/DRF-red?style=for-the-badge&logo=django&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white) ![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

## Security headers

`config/security/security_headers.py` sends `Content-Security-Policy: default-src 'none'` — the API
only returns JSON — plus `Permissions-Policy` and the Cross-Origin Opener/Resource policies.
Django's own settings cover HSTS, SSL redirect, `X-Frame-Options: DENY`, nosniff, referrer policy
and secure cookies.


## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
- [Docker](#-docker)
- [Project Structure](#-project-structure)
- [API Documentation](#-api-documentation)
- [Frontend](#-frontend)
- [License](#-license)
- [Author](#-author)

## 🌟 Overview

The **Backend** is a Django REST Framework-powered API that provides all the data management, business logic, and endpoints for the CareerHub platform. It handles job application tracking, offer management, availability calendars, interview event scheduling, and the secure data APIs consumed by the frontend's AI tools.

**Key Capabilities:**

- 🔗 **RESTful API**: Full CRUD operations for Applications, Offers, Events, Holidays, Documents, Tasks, Experience, and Settings
- 🔐 **JWT Auth for Split Deployments**: Login, refresh, logout, and `me` flows now use Bearer tokens so separate `*.vercel.app` frontend/backend projects work without a shared cookie domain
- 🤖 **Encrypted AI Provider Relay**: Frontend BYOK flows pull context from standard APIs while provider keys stay encrypted on the backend and provider adapters relay requests server-side
- 📥 **Import/Export**: Bulk CSV/XLSX import plus multi-format export (CSV, JSON, XLSX), including full-fidelity Experience import/export with linked offer/application snapshots
- 🔄 **Google Sheets Sync**: Authenticated users can link Google Sheets to one-way sync Applications or Events, review detected application imports, resolve possible duplicates, approve selected changes, inspect last-run change history, run manual syncs, and configure daily cron refreshes
- 📊 **Timeline Analytics**: Application timeline entries and Google Sheet row provenance power time-to-interview, stage conversion, stale-stage warnings, and offer-rate breakdowns
- 📄 **Resume Version Analytics**: `Application.submitted_documents` already pins the exact document version sent, so response, interview and offer rates per resume version are derived from records already kept — no new input asked for
- 👥 **Career Relationship Network**: Canonical contacts connect to Application and Experience contexts, expose company metadata for shared list/network filtering, support direct and person-to-person relationship edges, and preserve one logical career lifecycle from application through employment
- 🏢 **Company Deduplication**: Intelligent `get_or_create` logic to prevent duplicate companies
- 📅 **Federal Holidays**: Automatic U.S. holiday detection using the `holidays` library
- 🌐 **CORS Enabled**: Ready for frontend integration
- ☁️ **Vercel-Compatible HTTP API**: Django runs as a pure HTTP app with a WSGI entrypoint, external PostgreSQL, and a secured cron endpoint for maintenance jobs
- ⚡ **In-process cache**: `LocMemCache` only, used where no other instance needs to invalidate it. List responses are deliberately uncached, since a serverless instance cannot invalidate another's cache.
- 🐳 **Docker Ready (Local Dev)**: One-command local startup with Docker Compose bound to localhost

## ✨ Features

### 🏢 Applications

- **CRUD, locking and delete-all** over `/api/career/applications/`, with a lock that protects a row from bulk actions.
- **Status tracking** across the default pipeline — Applied, rounds 1–4, Final Round, Onsite, Offer, Rejected, Ghosted, Removed — without overwriting per-user stage settings.
- **Company auto-creation** when an application names a company that does not exist yet.
- **Bulk import** from CSV or XLSX, **job-board URL import** over public HTTPS with AI-assisted extraction when configured, and **Google Sheets sync** from a linked sheet.
- **Export** to CSV, JSON or XLSX.
- **Prep workspace** (`/prep_workspace/`) aggregating JD fit, resume evidence, linked documents, cover letters and notes for one application.
- **Company timeline** and **timeline analytics** for the stages an application passed through.
- **`job_description`** stores the full posting, so it survives the listing being taken down; **`has_reached_interview`** records that a round actually happened; **interview debriefs** attach per round.
- **`submitted_documents`** pins the exact document versions that were sent.
- **`free_food_meals`** itemises office meals as `[{meal, value, provided}]` rather than one averaged figure.
- **`unlocked_count`** ships on paginated application, document and offer lists so a caller knows how many rows a bulk action would touch.

### 🤝 Contacts

- **Canonical contacts** shared by Applications, Experience and Offers, with duplicate detection and merge.
- **Relationship network**: directed contact-to-contact edges with standard or custom labels, several edges per pair, and people not connected to the account holder.

### 💎 Offers

- **Compensation tracking**: base, bonus, equity, sign-on and benefits, with a per-year **sign-on schedule** and **equity refresh** fields.
- **Offer lifecycle**: `is_current` marks the baseline every comparison measures against; accepted, declined, expired and withdrawn are recorded.
- **`linked_experience`** ties an accepted offer to the role it became; **expected start date** and **Offer Letter** document type sit alongside it.
- **Private equity liquidity**: freely tradable, company buyback, or currently unsellable.
- **Simulator inputs** and **`UserSettings.offer_adjustment_settings`** hold the rent, commute and tax assumptions a comparison is priced under.
- **Decision snapshots** store a point-in-time comparison; the **decision journal** stores the judgement behind it.
- **Negotiation context API** returns the figures an advisor needs for one offer.
- **Benefit items** persist per offer, and **offer validation** rejects a payload outside the whitelisted fields.
- **Export** to CSV, JSON or XLSX.

### 📊 Analytics

- **Application stats** (`/api/career/application-stats/`) and the **funnel** are computed server-side across every page, not from the rows a client happens to hold.
- **Response trend**, **reply timing** and **response rate by source, location and level** — each row carrying `total` beside the rate so a caller can refuse to render a small sample.
- **Stage durations** and **days-to-offer** report how long your rounds actually take, with the provenance of each figure.
- **Field completeness** reports what is missing from your records.
- **Interview links** pairs events with applications.

### 🤖 Frontend BYOK AI

Bring your own provider key; every call is relayed through the API and the key is stored encrypted.

- **JD matcher**, **cover letter generator**, **offer negotiation advisor**, **career transition advisor**, **skill refinement**, **promotion readiness review** and **custom analytics widgets**.
- **AI artifact library** (`AIArtifact`) keeps every generated output, so a result survives the session that produced it.

### 📄 Documents

- **Upload, CRUD and versioning**, each version its own row, in hosted private storage.
- **Linking** to applications and experiences, **locking rules** that protect a version, **filtering** by type, and **export**.

### 👤 Experience

- **Application → Experience lifecycle**: an accepted offer becomes a role.
- **Raise history** drives pay over time; **structured team history** records who you worked with.
- **Internship compensation model** with **multi-phase schedules** for a role whose hours change partway.
- **Company logo upload** and **`work_email`**.
- **Import and export** in CSV, JSON or XLSX through an **atomic pipeline** that reconstructs the related company, application and offer rows inside one transaction, including **AI artifacts** and **offer decision history**.

### 📅 Availability & Events

- **Event scheduling** with **multi-day** (`end_date`) and **all-day** events, validated so an end date cannot precede a start even on a partial `PATCH`.
- **Unified calendar operations** over events, time off and federal holidays.
- **Holiday detection and management**, including ignoring a specific federal holiday.
- **Availability generation** for a chosen range and timezone.
- **Public booking links**, several per account, throttled per IP.
- **Conflict detection** APIs behind the notification bell.
- **Event link suggestions** (`/api/events/link-suggestions/`) pair unlinked events with a likely application by word-boundary company match, skipping meeting-tool phrases such as "Google Meet"; `/suggest-link/` does one title and `/apply-links/` attaches in bulk.

### ⚙️ Settings

- **User preferences**: working hours, timezone, event reminders, job-hunt thresholds and driving defaults.
- **Multiple availability time ranges** per day pattern, with **event date range validation**.
- **Organisation**: employment types, event categories, holiday tabs and pipeline stages.
- **Auto-ghosted logic** moves an application on once it has been silent past your threshold.
- **Navigation**: sidebar order, hidden entries and **mobile toolbar** preferences.
- **Profile identity** and the **privacy export centre** APIs for exporting or deleting an account.
- **Google Sheets integrations**: link a sheet, schedule a sync, and review each run.

### 💵 Income & Recorded Paychecks

- **`IncomeYear`** holds one year's elections — pay cadence, allowances, deductions, 401(k) rates and `deferral_base` — as JSON columns, so its shape changes without a migration.
- **`PaycheckActual`** keeps only the figures a person records, and round-trips through `IncomeYear` rather than a separate write path.
- **`allowances`** accepts a `ONCE` unit for a one-off payment on a nominated pay period.
- **`hidden_income_roles`** and **`hidden_income_years`** on `UserSettings` drive which sources the Income pickers offer.

### 📊 Account-Backed Layout

`UserSettings` stores what used to live only in the browser, so a second device sees it: the custom widget definitions and both analytics dashboard layouts, saved as `JSONField`s through `PUT /api/user-settings/current/`.

### 🔐 Authentication & Security

- **JWT login flow**: `/api/auth/login/` issues access and refresh tokens, `/api/auth/refresh/` rotates them.
- **Bearer-protected API access**, so the frontend can sit on another origin.
- **Account management** via `PATCH /api/auth/me/`, and **password change** with old-password verification. Passwords are hashed, never stored in plain text.
- **Every user-supplied URL the server fetches** goes through `config/security/outbound.py`, which refuses non-HTTP(S) schemes, odd ports and hosts resolving to private addresses, re-validating each redirect hop.

### ⚡ Runtime & Background Work

- **In-process cache** (`LocMemCache`), used for booking flows, the timezone lookup and AI artifact jobs. Response caching for list endpoints is deliberately not used: a serverless instance cannot invalidate another instance's cache.
- **Secured cron endpoints**: `/api/internal/cron/daily-maintenance/` and `/api/internal/cron/google-sheet-syncs/`, guarded by `CRON_SECRET` through the `Authorization: Bearer` header Vercel sends. Hobby-safe deploys run one daily cron at `0 8 * * *`.
- **Rate limiting**: 20 GET/min per IP on public booking slots, 5 POST/min on booking creation. Vercel edge mitigation denies common scanner paths, and `vercel-firewall-actions.json` holds the Hobby-compatible firewall actions.

## 🛠 Tech Stack

### Core Framework

- **Django 5.x** - Python web framework
- **Django REST Framework** - Toolkit for building RESTful APIs
- **PostgreSQL** - Primary production database via `DATABASE_URL`
- **SQLite** - Local fallback when `DATABASE_URL` is unset

### AI / NLP

- **User-provided AI provider** - Encrypted backend relay with Claude, Gemini, OpenAI, OpenRouter, and custom adapters for JD matching, cover letters, job URL import, negotiation advice, and analytics widget fallback
- **Lightweight keyword/acronym extractor** - Skill extraction from free-text experience descriptions without heavyweight runtime NLP dependencies

### Data Processing

- **Pandas** - CSV/XLSX parsing and data manipulation
- **openpyxl** - Excel file handling
- **Google API Client** - Optional private Google Sheets reads through service account credentials

### Utilities

- **django-cors-headers** - CORS middleware for frontend integration
- **holidays** - Federal holiday detection library

### Infrastructure

- **Docker + Docker Compose** - Containerised local development only

## 🚀 Getting Started

### Option A — Docker (recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cd api
cp .env.development.example .env.development

# First time — build images and start all services
docker compose up --build

# Subsequent runs
docker compose up -d

# Stop everything
docker compose down

# Stream logs
docker compose logs -f api
```

> `docker-compose.yml` is for local development only. It binds Postgres and the API to `127.0.0.1`, reads container env from `.env.development`, manages its own local Postgres volume, and is not an internet-facing deployment template.

Services started:
| Service | Port | Description |
|---|---|---|
| Postgres | 5432 | Primary application database |
| api | 8000 | Django HTTP API |

API: `http://localhost:8000/api`

---

### Option B — Local (venv)

#### Prerequisites

- Python 3.11+
- PostgreSQL running locally if you set `DATABASE_URL` (otherwise the app falls back to SQLite)

#### Installation

1. **Navigate to backend directory**

   ```bash
   cd api
   ```

2. **Activate virtual environment and install dependencies**

   ```bash
   uv sync                     # creates .venv from uv.lock, Python 3.12 per requires-python
   source .venv/bin/activate
   ```

3. **Create your local env file**

   ```bash
   cp .env.development.example .env.development
   ```

4. **Choose a database**

   ```bash
   # Edit .env.development for local PostgreSQL
   DATABASE_URL=postgresql://careerhub:careerhub@localhost:5432/careerhub

   # Or remove DATABASE_URL from .env.development to keep using api/db.sqlite3 locally
   ```

5. **Run Migrations**

   ```bash
   python manage.py migrate
   ```

6. **Start Django**
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

## 🐳 Docker

All Docker files live in `api/`:

```
api/
├── Dockerfile            # Multi-stage build (builder + final)
├── docker-compose.yml    # Local-development-only services: postgres + api
├── media/                # Local fallback uploads when Blob storage is not configured
├── .env                  # Pointer file explaining the split env setup
├── .env.development      # Local development secrets (git-ignored)
├── .env.development.example
├── .env.production.example
├── .env.example          # Quick start note for the split env workflow
├── .dockerignore         # Excludes venv, db, media, etc.
├── requirements.docker.txt  # Docker install shim
└── requirements.runtime.txt # Runtime dependency list for Docker + Vercel
```

> **Media persistence**: when `BLOB_READ_WRITE_TOKEN` and `DOCUMENT_BLOB_READ_WRITE_TOKEN` are unset, logo uploads and document uploads fall back to Django storage in `api/media/` on the host via a bind mount (`./media:/app/media`). Files survive container restarts and rebuilds — no data is stored in Docker named volumes.

### Environment Modes

CareerHub now uses explicit environment files instead of a single mixed `.env`:

- `.env.development` — local development settings; secure cookies, SSL redirect, and HSTS stay off
- `.env.production` — production-only settings if you use a file-based deploy target; secure cookies, SSL redirect, and HSTS should be on
- platform-managed environment variables — preferred for hosted production deployments

Key production flags:

| Variable                            | Production Value                                                                                                        |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `SESSION_COOKIE_SECURE`             | `True`                                                                                                                  |
| `CSRF_COOKIE_SECURE`                | `True`                                                                                                                  |
| `SECURE_SSL_REDIRECT`               | `True`                                                                                                                  |
| `SECURE_HSTS_SECONDS`               | `31536000`                                                                                                              |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS`    | `True`                                                                                                                  |
| `AI_PROVIDER_ALLOWED_HOSTS`         | `api.anthropic.com,generativelanguage.googleapis.com,api.openai.com,openrouter.ai` if you enforce an AI relay allowlist |
| `GOOGLE_OAUTH_CLIENT_ID`            | Google Cloud OAuth web client ID for private Google Sheets access                                                       |
| `GOOGLE_OAUTH_CLIENT_SECRET`        | Google Cloud OAuth web client secret                                                                                    |
| `GOOGLE_OAUTH_SUCCESS_REDIRECT_URL` | Frontend Settings URL to use if OAuth callback cannot use stored state redirect                                         |

### Vercel Deployment Shape

CareerHub now deploys cleanly to Vercel as two separate projects:

1. `api/` — Django backend on the Python runtime
2. `frontend/` — Vite SPA on Vercel static hosting

Backend notes:

- `api/vercel.json` routes all requests to the Django WSGI entrypoint at `api/wsgi.py`
- set `DATABASE_URL` to an external PostgreSQL database
- set `BLOB_READ_WRITE_TOKEN` if you want Experience logos to use public Vercel Blob storage
- set `DOCUMENT_BLOB_READ_WRITE_TOKEN` if you want documents to use private Vercel Blob storage
- set `CRON_SECRET` so Vercel can securely invoke `/api/internal/cron/daily-maintenance/`
- enable both Google Sheets API and Google Drive API in Google Cloud for private sheet sync and spreadsheet selection
- set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` for user-owned private Google Sheets sync; add `https://your-api-project.vercel.app/api/career/google-oauth/callback/` as an authorized redirect URI in Google Cloud
- set `GOOGLE_OAUTH_SUCCESS_REDIRECT_URL` to your frontend Settings integrations URL, for example `https://your-frontend.vercel.app/settings?tab=integrations`
- optional fallback: set `GOOGLE_SERVICE_ACCOUNT_JSON` or `GOOGLE_SERVICE_ACCOUNT_INFO` if you want private Google Sheets sync by service account sharing; public sheet CSV export still works without either credential path
- optional WAF setup: run `VERCEL_TOKEN=... python scripts/apply_vercel_firewall.py` from `api/` to apply the supported firewall actions in `vercel-firewall-actions.json`; Vercel Firewall rate limiting is omitted from the dashboard when the active plan does not support it.
- hosted document uploads are capped at 4 MB so they stay within Vercel request limits; local fallback storage can still use your configured `MAX_DOCUMENT_UPLOAD_BYTES`
- for the zero-domain-cost setup in this repo, set `ALLOWED_HOSTS` to your actual backend `*.vercel.app` alias and `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` to your actual frontend alias
- JWT Bearer auth does not require cross-origin cookies, so `CORS_ALLOW_CREDENTIALS` can stay off
- if you later move to a shared custom parent domain and want cookie-based flows for other surfaces, also set:
  - `SESSION_COOKIE_DOMAIN=.example.com`
  - `CSRF_COOKIE_DOMAIN=.example.com`

Frontend notes:

- set `VITE_API_BASE_URL` to your own backend origin plus `/api`, for example `https://your-api-project.vercel.app/api`
- optionally set `VITE_MEDIA_BASE_URL` if uploaded files are served from a different origin

### 🤖 Configuring AI for the Current App

Current AI features are configured in the frontend, with the provider key stored encrypted on the backend:

1. Open the app and go to `Settings` → `AI Provider`.
2. Choose Claude, Gemini, OpenAI, OpenRouter, or Custom providers, then enter the endpoint, model, and your own API key.
3. Save the provider to your authenticated account.
4. Run JD Matcher, Cover Letter generation, Negotiation Advisor, or Analytics custom widgets from the UI.

### Share prices

`Offer.equity_current_price` holds a price per share for a company with no ticker, which is how a
private buyback is valued. `StockPrice` covers listed symbols, holding the latest price per ticker
per user rather than per offer, so two offers at the same company share one number; `source` marks
whether it was typed or fetched, and `POST` upserts on `(user, symbol)`.

`POST /career/stock-prices/refresh/` fetches the latest traded price for a ticker and records it;
with no `symbol` it sweeps every tracked ticker and reports a bad one in `failed`. History is kept
so a grant can be repriced over time. The source is Yahoo's chart endpoint — free, no key, and
undocumented, so it refuses a request without a browser-shaped user agent.


### Google Sheets sync behaviour

A tracked row is matched by `identity:sha256(company, role, salary_range, location,
office_location, job_link)`, with the sheet row number as a fallback when a field is edited, so
renaming a role updates the application in place rather than creating a second one. A row that
leaves the sheet is archived; the permanent delete that follows is refused when the application
carries a recorded offer, a decision journal or attached documents. Mapping an `external_id`
column makes the key a stable id and avoids the hash entirely.

### Analytics endpoints

- **Resume version analytics** report which document version went out with each application and how
  each performed, counting replies rather than offers.
- **Decision journal** records the concerns and assumptions behind an offer decision, each later
  marked became real, never happened or still unclear.
- **Decision outcome insights** read the journal back across decisions: which concerns became real,
  which assumptions were wrong, and which criteria have historically mattered.

### Squashed migrations

Each app has exactly one migration, `0001_initial`, generated from the current models: a fresh
database is built from plain `CreateModel` statements rather than replaying 52 files of raw
`ADD COLUMN` workarounds. Production already had a `0001_initial` row per app, so it still reads
as applied and no `django_migrations` surgery was needed. This also unblocked local sqlite: the old
`0034` used `DROP COLUMN IF EXISTS`, which sqlite rejects, so a from-scratch local migrate was
impossible and the backend tests could not run at all.

Rows for the 52 replaced migrations remain in `django_migrations` as orphans, alongside 98 that
were already there from an earlier squash. Django ignores rows with no matching file.

One known drift, unchanged by the squash: ten `availability_usersettings` columns are nullable in
production but `NOT NULL` in a fresh build, because the raw `ADD COLUMN` statements omitted the
constraint. No row holds a NULL, so it is cosmetic.

### Migration Workflow

When you change Django models, always generate and commit migrations.

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
```

### Optional: Local Privacy Gate

This is a single-maintainer deployment, so the repo must never carry the maintainer's own
employers, contacts, pay figures or dates — fixtures and docs use the substitutes published in
`AGENTS.md`. Two gates enforce that:

- `career/tests/test_fixture_vocabulary.py` runs with the suite and fails when a fixture names an
  employer or person outside the published substitutes. It needs no database access.
- An optional `.git/hooks/pre-commit` greps staged lines against a locally generated list:

  ```bash
  DJANGO_ENV=production python manage.py export_leakcheck_values --email <your-account>
  ```

  The command prints only a count, writes to a directory outside every git repo, and is checked in
  two tiers: unambiguous values (emails, multi-word names, amounts with non-zero cents) against
  every file, and premium-sized amounts against fixtures and docs only. `LEAKCHECK=off git commit`
  bypasses it for a genuine coincidence.

### Optional: Django Admin

```bash
python manage.py createsuperuser
```

Access at `http://localhost:8000/admin`.

## 📁 Project Structure

```
api/
├── src/                      # Importable Django source packages
│   │                         # Every app keeps Django's own modules at its root (models, serializers,
│   │                         # admin, apps, urls, signals, tasks) and everything else in a package
│   │                         # named for what it is: services/, views/, tests/.
│   ├── availability/         # Availability calendar & events module
│   │   ├── models.py         # Event, CustomHoliday, UserSettings, ShareLink, PublicBooking
│   │   ├── serializers.py    # DRF serializers
│   │   ├── pagination.py     # DRF page-size classes
│   │   ├── throttling.py     # DRF rate-limit throttle classes
│   │   ├── signals.py        # Cache invalidation signals
│   │   ├── tasks.py          # HTTP-triggered maintenance helpers
│   │   ├── services/         # Domain logic: ai_provider (relay), provider_secrets (key encryption),
│   │   │                     # json_healing (JSON repair), ai_provider_errors, conflict_detector,
│   │   │                     # recurrence, holiday_recurrence, timezones, utils
│   │   ├── views/            # API ViewSets, one module per surface (share links, imports, categories,
│   │   │                     # conflicts, user settings); booking.py keeps the endpoints plus the slot
│   │   │                     # validation the tests patch, the rest in booking_{slots,intake,ics,…}.py
│   │   ├── tests/            # Per-domain test modules (availability, events, booking, settings,
│   │   │                     # AI provider, auth, holidays, hidden income, nav labels)
│   │   └── migrations/
│   │
│   ├── career/               # Job applications, offers & AI tools module
│   │   ├── models/           # Models by domain; `__init__.py` imports all of them, so `from .models
│   │   │                     # import X` and app_label resolution are unchanged
│   │   ├── serializers/      # DRF serializers by domain; `__init__.py` re-exports every name
│   │   ├── services/         # Business logic: career records, reference data, rent, weekly review,
│   │   │                     # storage, stock quotes, cache, skills_extractor, upload_validation;
│   │   │                     # google_sheets.py keeps the sync orchestration and the names the tests
│   │   │                     # patch, the rest in google_sheet_{constants,stages,rows,…}.py
│   │   ├── views/            # API ViewSets (package)
│   │   ├── tests/            # Per-domain test modules; sheet sync split again by concern
│   │   ├── management/       # Django management commands
│   │   ├── data/             # Bundled reference data
│   │   └── migrations/
│   │
│   ├── analytics/            # Analytics app support
│   │   └── signals.py        # Cache bust on Event/Application change
│   │
│   └── config/               # Django project settings
│       ├── settings.py       # Configuration (security, environment modes, PostgreSQL/SQLite, cache, CORS)
│       ├── urls.py           # Root URL configuration
│       ├── asgi.py           # HTTP-only ASGI entrypoint
│       ├── wsgi.py
│       ├── auth/             # authentication.py (JWT/session account-status rules), auth_urls, auth_views
│       ├── security/         # security_headers (CSP), security_views, outbound (SSRF guard), user_ownership
│       └── views/            # cron_views (secured cron endpoint), public_redirect_views
│
├── api/                      # Vercel Python runtime package
│   └── wsgi.py               # Public `app` entrypoint for Vercel
├── db.sqlite3                # Local SQLite fallback database (optional, not committed)
├── manage.py                 # Django management script
├── requirements.docker.txt   # Docker dependency shim
├── requirements.runtime.txt  # Shared runtime dependencies
├── vercel.json               # Vercel routing + cron config
└── docker-compose.yml        # Local-development-only Docker Compose config
```

## 📡 API Documentation

### Career Endpoints

Base prefix: `/api/career/`

#### Applications

- `GET /api/career/applications/` — List all applications
- `GET /api/career/applications/company-list/` — List distinct companies used by the authenticated user's applications for shared selectors
- `POST /api/career/applications/` — Create a new application
- `GET /api/career/applications/{id}/` — Retrieve application details
- `GET /api/career/applications/{id}/prep_workspace/` — Retrieve the application's prep workspace with JD reports, cover letters, linked documents, notes, timeline, and resume evidence
- `PUT /api/career/applications/{id}/` — Update application (auto-creates offer if status → OFFER)
- `DELETE /api/career/applications/{id}/` — Delete application (blocked if locked)
- `DELETE /api/career/applications/delete_all/` — Delete all unlocked applications
- `POST /api/career/import/` — Bulk import from CSV/XLSX
- `POST /api/career/job-import/` — Extract application fields from a public HTTPS job board URL with optional AI-assisted parsing
- `GET /api/career/applications/export/?fmt=csv` — Export applications (csv/json/xlsx)
- `GET /api/career/application-timeline/?application={id}` — List timeline entries for one application
- `POST /api/career/application-timeline/` — Create or restore a stage timeline entry with a per-application title, date, notes, and documents
- `PATCH /api/career/application-timeline/{id}/` — Update a timeline title, date, notes, or documents without changing its canonical synced stage key
- `DELETE /api/career/application-timeline/{id}/` — Remove a timeline entry while suppressing automatic Google Sheets recreation
- `GET /api/career/application-stats/` — Return dashboard aggregates (totals, rates, locations, age buckets, daily applied histogram, available years) without the application rows; accepts `?year=`
- `GET /api/career/application-timeline-analytics/` — Return timeline-driven application analytics, including time-to-interview, stage conversion, stale in-stage warnings, and offer rates by source/sheet/company
- `GET /api/career/resume-version-analytics/` — Return per-resume-version application counts, response/interview/offer rates, breakdowns by role type and source, and a small-sample flag
- `GET /api/career/decision-outcome-insights/` — Return which recorded concerns became real, how each decision criterion actually turned out, and how many decisions have been looked back on

#### Interviews

- `GET /api/career/interview-debriefs/` — List debriefs for the authenticated user's applications
- `POST /api/career/interview-debriefs/` — Record a debrief against one interview round

#### Offers

- `GET /api/career/offers/` — List all offers
- `POST /api/career/offers/` — Create a new offer
- `GET /api/career/offers/{id}/` — Retrieve offer details
- `PUT /api/career/offers/{id}/` — Update offer
- `DELETE /api/career/offers/{id}/` — Delete offer
- `POST /api/career/offers/transition-advisor/` — Career transition advice for a role you want to leave

Offer payloads expose `equity_liquidity` (`LIQUID`, `BUYBACK`, or `ILLIQUID`) and `equity_buyback_value`. Existing offers default to `LIQUID` for backward-compatible calculations.

#### Income

- `GET /api/career/paycheck-actuals/` — List recorded paychecks
- `POST /api/career/paycheck-actuals/` — Record what a paycheck actually paid

#### Experience

- `GET /api/career/experiences/` — List all experience entries
- `POST /api/career/experiences/` — Create experience (auto-extracts skills)
- `PUT /api/career/experiences/{id}/` — Update experience
- `PATCH /api/career/experiences/{id}/` — Partial update experience fields (used heavily by the frontend)
- `DELETE /api/career/experiences/{id}/` — Delete experience
- `DELETE /api/career/experiences/delete_all/` — Delete all unlocked experiences
- `GET /api/career/experiences/export/?fmt=json` — Export experiences (csv/json/xlsx). JSON is best for full round-trip fidelity
- `POST /api/career/experiences/import/` — Import experiences from JSON/CSV/XLSX, including linked offer/application snapshots when present
- `POST /api/career/experiences/{id}/upload-logo/` — Upload company logo (multipart `logo` field, stores a public logo URL)
- `DELETE /api/career/experiences/{id}/remove-logo/` — Remove company logo

#### Contacts and Relationships

- `GET /api/career/applications/options/` — Lightweight application options for pickers; supports `search`, `page`, `page_size` (default 50, max 200), and `ids` for resolving specific applications regardless of paging
- `GET /api/career/contacts/` — List canonical contacts; filter by `application`, `experience`, `context`, `relationship`, `direct`, or `search`
- `POST /api/career/contacts/` — Create or reuse a contact and optionally attach Application/Experience context plus a direct relationship
- `PATCH /api/career/contacts/{id}/` — Update canonical contact details
- `DELETE /api/career/contacts/{id}/?application={id}` — Detach a contact from one Application or Experience context without deleting the person globally
- `POST /api/career/contacts/{id}/merge/` — Merge a confirmed duplicate while preserving contexts, notes, locks, and relationships
- `GET|POST /api/career/contact-relationships/` — List or create direct and person-to-person relationship edges
- `PATCH|DELETE /api/career/contact-relationships/{id}/` — Update or delete one relationship edge

#### Documents

- `GET /api/career/documents/` — List current document versions
- `GET /api/career/documents/?include_versions=true` — List all versions
- `POST /api/career/documents/` — Upload a document
- `POST /api/career/documents/{id}/add_version/` — Create new version
- `GET /api/career/documents/{id}/versions/` — List version history
- `GET /api/career/documents/{id}/download/` — Stream a document through an authenticated download endpoint
- `GET /api/career/documents/export/?fmt=csv` — Export documents
- `DELETE /api/career/documents/delete_all/` — Delete all unlocked document chains

#### Tasks

- `GET /api/career/tasks/` — List tasks
- `POST /api/career/tasks/` — Create task, including smart reminders parsed by the frontend into normal task due dates
- `PATCH /api/career/tasks/{id}/` — Update task
- `POST /api/career/tasks/reorder/` — Reorder tasks

#### Helpers

- `GET /api/career/reference-data/` — Tax/COL/marital-status reference payload
- `GET /api/career/rent-estimate/?city=San+Jose,+CA,+United+States` — Rent estimate (HUD/fallback)
- `GET /api/career/weekly-review/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` — Weekly summary

#### Google Sheets Sync

- `GET /api/career/google-oauth/status/` — Check whether Google OAuth is configured and connected
- `POST /api/career/google-oauth/connect/` — Create a Google OAuth consent URL for read-only Sheets access and Drive metadata access for spreadsheet selection
- `GET /api/career/google-oauth/callback/` — OAuth callback registered with Google Cloud
- `POST /api/career/google-oauth/disconnect/` — Remove the authenticated user's Google OAuth refresh token
- `GET /api/career/google-oauth/spreadsheets/` — List the connected Google account's spreadsheet files for the Settings picker
- `GET /api/career/google-oauth/spreadsheet-tabs/` — List worksheet tabs for the selected spreadsheet
- `GET /api/career/google-sheet-syncs/` — List saved Google Sheet sync configs
- `POST /api/career/google-sheet-syncs/` — Create a sheet sync config for Applications or Events
- `PATCH /api/career/google-sheet-syncs/{id}/` — Update mapping, worksheet, enabled state, or target settings
- `POST /api/career/google-sheet-syncs/{id}/test/` — Read headers and preview rows from the linked sheet
- `POST /api/career/google-sheet-syncs/{id}/import-review/` — Scan an application sync and summarize new applications, status changes, possible duplicates, and other updates without writing records
- `POST /api/career/google-sheet-syncs/{id}/apply-import-review/` — Apply only approved review item IDs, with optional duplicate resolutions for merge, keep separate, or intentional duplicate
- `POST /api/career/google-sheet-syncs/{id}/sync-now/` — Run the sync immediately

### Availability Endpoints

#### Events

- `GET /api/events/` — List all events
- `POST /api/events/` — Create a new event (triggers conflict detection)
- `GET /api/events/{id}/` — Retrieve event details
- `PUT /api/events/{id}/` — Update event
- `DELETE /api/events/{id}/` — Delete event
- `GET /api/events/export/?fmt=json` — Export events
- `DELETE /api/events/delete_all/` — Delete all events

#### Holidays

- `GET /api/holidays/` — List all custom holidays (includes `tab` field)
- `POST /api/holidays/` — Create a custom holiday (supports `tab` assignment + grouped multi-day collections)
- `PUT /api/holidays/{id}/` — Update holiday (full replace)
- `PATCH /api/holidays/{id}/` — Partial update (e.g., tab or description only)
- `GET /api/holidays/federal/` — List native federal + user-defined federal holidays
- `GET /api/holidays/export/?fmt=csv` — Export holidays

#### Event Categories

- `GET /api/categories/` — List all event categories
- `POST /api/categories/` — Create a category
- `PUT /api/categories/{id}/` — Update category (name, color, icon, is_locked)
- `PATCH /api/categories/{id}/` — Partial update (e.g., toggle `is_locked` only)
- `DELETE /api/categories/{id}/` — Delete category

#### Availability / Booking

- `GET /api/availability/generate/?start_date=YYYY-MM-DD&timezone=Asia/Tokyo&weeks=2` — Generate availability text rows for a user-defined week range; accepts IANA timezone names
- `POST /api/overrides/` — Override a specific date's availability text
- `GET /api/share-links/current/` — Get active booking share link
- `POST /api/share-links/generate/` — Generate a new booking share link, including optional reschedule/cancel cutoff hours
- `POST /api/share-links/deactivate/` — Deactivate current booking share links
- `POST /api/public-bookings/{id}/cancel/` — Authenticated host cancel action that bypasses guest cutoff rules and removes the locked event
- `GET /api/booking/{uuid}/slots/?date=YYYY-MM-DD&timezone=Asia/Tokyo` — Public: fetch bookable slots in the visitor's IANA timezone
- `POST /api/booking/{uuid}/book/` — Public: submit a booking (creates locked event)
- `GET /api/booking/{uuid}/manage/{booking_uuid}/details/` — Public: fetch booking details for guest self-management
- `POST /api/booking/{uuid}/manage/{booking_uuid}/reschedule/` — Public: reschedule a booking before the configured cutoff
- `POST /api/booking/{uuid}/manage/{booking_uuid}/cancel/` — Public: cancel a booking before the configured cutoff with an optional reason

#### Settings

- `GET /api/security/dashboard/` — Authenticated security posture summary for Settings, including environment flags, auth throttles, Google sync health, and Vercel WAF setup hints
- `GET /api/user-settings/current/` — Retrieve user settings (singleton)
- `PUT /api/user-settings/current/` — Update all settings fields including `availability_weeks`, `employment_types`, `holiday_tabs`, `work_time_ranges`, `mobile_toolbar_items`, and AI provider fields
- `GET /api/user-settings/account-export/?fmt=json|zip` — Download account-level CareerHub export data
- `POST /api/user-settings/restore-backup/` — Restore a CareerHub account export in merge or replace mode
- `DELETE /api/user-settings/account/` — Schedule authenticated account deletion with a 14-day grace period when the payload includes `confirm=DELETE`
- `POST /api/user-settings/ai-provider/chat-completions/` — Relay an authenticated AI request through the user's selected Claude, Gemini, OpenAI, OpenRouter, or custom adapter using the encrypted provider key

#### Internal Maintenance

- `GET /api/internal/cron/daily-maintenance/` — Secured daily maintenance hook for Vercel Cron Jobs; expires share links, ghosts stale applications, and purges account deletions whose 14-day grace period has elapsed
- `GET /api/internal/cron/google-sheet-syncs/` — Secured Google Sheets cron hook kept for future Pro/custom-worker scheduling; Hobby deploys use the single daily cron in `vercel.json`

#### Authentication

- `POST /api/auth/login/` — Email/password login, returns `user`, `access`, and `refresh`
- `POST /api/auth/refresh/` — Exchange a refresh token for a rotated access/refresh pair; the previous refresh token is invalidated
- `POST /api/auth/logout/` — Logout companion endpoint; if a refresh token is supplied it is blacklisted server-side
- `GET /api/auth/me/` — Fetch the current user with a Bearer access token
- `GET /api/auth/signup-status/` — Public signup capability metadata
- `POST /api/auth/signup/` — Create a new account
- `POST /api/auth/password-change/` — Change user password (requires old password)
- `PATCH /api/auth/me/` — Update user profile details (first/last name)

## 🔗 Frontend

- **Frontend**: [CareerHub Frontend](https://github.com/arunike/CareerHub-Frontend)
- The authenticated Availability workspace presents these generation and booking APIs in phone-, tablet-, and wide-desktop-safe layouts.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.txt) file for details.

## 👤 Author

**Richie Zhou**

- GitHub: [@arunike](https://github.com/arunike)
