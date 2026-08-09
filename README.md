# 🔧 Backend - Django REST API

A robust Django REST Framework API powering the CareerHub job search platform.

![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![DRF](https://img.shields.io/badge/DRF-red?style=for-the-badge&logo=django&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white) ![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

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
- 👥 **Career Relationship Network**: Canonical contacts connect to Application and Experience contexts, expose company metadata for shared list/network filtering, support direct and person-to-person relationship edges, and preserve one logical career lifecycle from application through employment
- 🏢 **Company Deduplication**: Intelligent `get_or_create` logic to prevent duplicate companies
- 📅 **Federal Holidays**: Automatic U.S. holiday detection using the `holidays` library
- 🌐 **CORS Enabled**: Ready for frontend integration
- ☁️ **Vercel-Compatible HTTP API**: Django runs as a pure HTTP app with a WSGI entrypoint, external PostgreSQL, and a secured cron endpoint for maintenance jobs
- ⚡ **Optional Shared Cache**: Redis can still be attached for shared caching/throttling, but local development and Vercel deployments no longer depend on it
- 🐳 **Docker Ready (Local Dev)**: One-command local startup with Docker Compose bound to localhost

## ✨ Features

### 🏢 Application Management
- **CRUD API**: Full create, read, update, delete operations for job applications
- **Status Tracking**: Default pipeline stages use the shared blue-to-purple palette for Applied, rounds 1–4, Final Round, Onsite, Offer, Rejected, Ghosted, and Removed without overwriting saved per-user stage settings
- **Company Auto-Creation**: Serializer automatically creates `Company` objects from `company_name`
- **Bulk Import**: Upload CSV/XLSX files to import multiple applications at once
- **Google Sheets Sync**: Link a Google Sheet, auto-map columns from headers, optionally adjust fields, and import changed rows into Applications from the Settings integration UI; newly encountered numbered rounds automatically append deterministic, algorithmically generated blue-to-purple stage colors to that user's pipeline
- **Job Board URL Import**: Extract company, role, location, and job description from public HTTPS job pages, using the user's AI provider when configured and falling back to deterministic parsing
- **Export Options**: Download data as CSV, JSON, or XLSX
- **Optional Decision Signals**: Store advanced visa sponsorship, Day 1 GC, growth, work-life, brand, and manager/team scores only when users provide them
- **Detail Aggregation Ready**: Application records expose linked timeline, event, document, AI artifact, and notes data consumed by the frontend detail drawer
- **Application Prep Workspace**: Aggregates one application's JD reports, cover letters, linked documents, notes, timeline, and resume evidence for the frontend prep drawer
- **Company Timeline**: Persist editable per-application stage titles, dates, notes, and attached documents; user overrides and removals are protected from Google Sheets repair, while manually authored later-round history is hidden instead of destroyed when a synced status moves backward
- **Timeline Analytics**: Aggregate timeline and sheet sync history into average time from applied to interview, stage conversion, stale in-stage warnings, and offer rates by source/sheet/company
- **Locking**: Locked applications cannot be deleted
- **Delete All**: Bulk delete endpoint respects lock status

### 💎 Offer Management
- **Compensation Tracking**: Store Base Salary, Bonus, Equity (annual + optional total grant/vesting %), Sign-On, Benefits, PTO Days, and Holiday Days
- **`Application.job_description`**: the full posting text. Postings are routinely taken down while you are still interviewing, so the link alone is not a record. The URL importer already extracted this text but the frontend was folding it into `notes`; it now has its own column and is exposed by `ApplicationSerializer`
- **`Application.has_reached_interview`** (read-only): true once the timeline shows a stage past screening. Annotated with a single `Exists` subquery on the list endpoint rather than a query per row, and falls back to a direct check for single objects. Drives whether the Debriefs tab appears
- **Interview debriefs**: `/api/career/interview-debriefs/` (CRUD, `?application=<id>`) stores one `InterviewDebrief` per application round — questions asked, what went well, weak areas, interviewer notes, confidence (1-5), and next steps. The serializer enforces one debrief per round, the confidence range, and application ownership
- **`Application.submitted_documents`** (M2M to `Document`): the exact document versions sent with an application. Because each version is its own `Document` row, uploading a new version never changes what is pinned
- **Canonical Contacts**: `/api/career/contacts/` stores each person once per user with optional email, job title, company, and notes; obsolete phone and LinkedIn fields are not part of the model or API, Application and Experience associations are retained as contexts, normalized non-empty email matches are reused, and same-name records remain separate for manual review
- **`Offer.linked_experience`** (read-only): the role an offer turned into, taken from the existing `Experience.offer` reverse relation — `id`, `title`, `company`, `start_date`, `end_date`, and `is_current`. Several experiences can point at one offer (an internship and the return offer it became), so the most recent `start_date` wins and rows without one sort last rather than raising. The offers queryset prefetches `experiences`, so the field costs one query for the page instead of one per offer. Lets a client tell a role still held from one already left
- **Sign-On Schedule**: `Offer.sign_on_schedule` holds per-year sign-on amounts (e.g. `[30000, 20000]`); an empty list means the whole sign-on lands in year 1, so projections can model an uneven split rather than assuming it is paid up front
- **Multi-Day Events**: `Event.end_date` is null for a single-day event and otherwise the last day it spans; `EventSerializer.validate` rejects an end date before the start, falling back to the stored value so a PATCH sending only one of the two is still checked
- **Event Link Suggestions**: `GET /api/events/link-suggestions/` pairs unlinked events with a likely application by word-boundary company match (skipping meeting-tool phrases such as "Google Meet"), `GET /api/events/suggest-link/?title=` does the same for one title, and `POST /api/events/apply-links/` attaches them in bulk, silently skipping ids the caller does not own. `GET /api/events/?application=` filters events to one application
- **All-Day Events**: `Event.is_all_day` marks an event as spanning the whole day; times are still stored (`00:00`–`23:59`) so ordering, conflict checks, and ICS export keep working unchanged
- **Relationship Network**: `/api/career/contact-relationships/` stores optional direct-to-user and person-to-person edges with standard or custom labels and optional career-record context; the legacy `/application-contacts/` route remains an API alias during migration
- **`Experience.work_email`**: the work email address you had at that job
- **Application timeline analytics**: `GET /career/application-timeline-analytics/` is the single source for funnel data. Alongside the existing `stage_conversion` (per-stage `reached_count` / `current_count` from the timeline), it now also returns `total_applications`, `outcomes`, `response_rate`, `ghost_rate`, and `biggest_drop`
- **`unlocked_count` on paginated lists**: applications, documents, and events return how many rows across the *whole* filtered set are unlocked, not just the current page. A "Delete All" control needs this — `count` alone cannot tell it whether anything is deletable. Provided by the shared `availability.pagination.ConditionalPageNumberPagination`, which replaced three byte-identical copies
- **Offer export**: `GET /career/offers/export/?fmt=csv|json|xlsx`
- **Document filtering**: `GET /career/documents/?application=<id>` restricts documents to one application, used by the offer modal's attachment list
- **Offer validation**: `refresh_starts_year` must be 1-4 and `annual_refresh_value` cannot be negative, enforced in `OfferSerializer` because the DB column carries no CHECK constraint
- **`UserSettings.offer_adjustment_settings`** (JSONField): stores offer comparison scenarios and adjustment assumptions `{maritalStatus, simulatedOffers, savedAt}` per user, replacing browser-only storage
- **Equity refresh fields**: `annual_refresh_value` and `refresh_starts_year` on Offer, both optional (0 disables refresh modelling)
- **Offer Letter document type**: `OFFER_LETTER` added to `Document.DOCUMENT_TYPES`
- **Migration replay**: `availability/0001_initial` used to create `PublicBooking` with a composite `unique_together` and then drop it later in the same migration. Postgres never exposed that as a droppable named constraint, so the history could not be replayed on a fresh database — meaning tests and CI could not run at all. Both operations cancelled out and have been removed; the end state is unchanged and `manage.py migrate` now succeeds from scratch
- **Migration note**: this Postgres engine rejects `ALTER COLUMN ... DROP DEFAULT`, which Django emits after every `AddField` with a default. Migration `0017` uses `SeparateDatabaseAndState` with raw `ADD COLUMN` SQL to work around it; follow the same pattern for future defaulted fields
- **Offer lifecycle fields**: `deadline` (decision due date), `negotiation_rounds` (JSON log of asked-vs-received per round), `risk_notes` (watch-outs, written by the Negotiation Advisor), and `final_decision_status` / `final_decision_reasoning` are all surfaced in the frontend. `final_decision_status` accepts `PENDING`, `ACCEPTED`, `REJECTED`, `EXPIRED`, and `WITHDRAWN`; the legacy `DECLINED` value is still read and preserved
- **Removed `counteroffer_history`** (migration `0016`): redundant with `negotiation_rounds`, which models the same asked-and-answered cycle. Nothing read or wrote the field
- **Private Equity Liquidity**: Classify annual equity as freely tradable, company-buyback, or currently unsellable; store the annual buyback value separately so downstream comparisons count only realizable equity while preserving the full grant amount
- **Simulator Inputs**: Offer and Application records expose tax overrides, monthly rent, commute cost, food perk, PTO, and equity vesting fields used by the frontend compensation simulator
- **Auto-Creation**: When an application's status becomes "OFFER", a placeholder offer is automatically created
- **Is Current Flag**: Mark one offer as your baseline "Current Role" for comparisons
- **Benefit Item Persistence**: Offer-level benefit item breakdown is persisted (JSON) alongside annualized `benefits_value`
- **Decision Snapshots**: Persist point-in-time offer decisions with scorecard rank, frontend-calculated adjusted value and uncapped logarithmic Financial score, totals above the $300k = 100 benchmark, tax/rent/commute assumptions, separate Remote/RTO category scores, offer snapshot, and notes
- **Negotiation Context API**: Offer and Application data power the frontend negotiation advisor and backend relay flow

### 🤖 Frontend BYOK AI

> AI provider configuration now lives in the frontend Settings page, while the API key is stored encrypted on the backend.

- **JD Matcher**: the frontend fetches Experience data from the API, builds the prompt in the browser, and sends it through the authenticated backend relay for fit scoring, gap analysis, and resume tailoring suggestions
- **Cover Letter Generator**: the frontend combines Application + Experience context in the browser and routes provider requests through the encrypted backend relay
- **Offer Negotiation Advisor**: the frontend uses Offer/Application/Experience APIs as context while the backend relay handles the provider call
- **Career Transition Advisor**: the frontend sends current job pain points, custom sentiments, promotion outlook, and simulated offers to the `/api/career/offers/transition-advisor/` action, which queries active offers and calls the configured AI provider to analyze tradeoffs, decide the optimal move (Stay vs. Hop vs. Job Hunt), suggest company search criteria, and generate side-by-side path comparisons
- **Skill Refinement**: the frontend can refine Experience skills through the backend relay when the user's provider key is configured
- **Promotion Readiness Review**: the frontend evaluates saved Experience evidence plus optional context through the backend relay, then stores the review as a `PROMOTION_REVIEW` artifact linked to the source Experience
- **Analytics Custom Widgets**: deterministic queries run in the frontend; free-form queries use the authenticated backend relay with the user's stored provider config
- **AI Artifact Library**: generated JD reports, cover letters, negotiation results, and promotion reviews are persisted as authenticated `AIArtifact` records so they sync across browsers/devices, keep lock/delete semantics, and participate in account export/restore

#### Skill Extraction (NLP, background)
- Extracts fallback skills from Experience descriptions using a lightweight keyword + acronym matcher
- Runs automatically on `Experience` create/update
- Remains the default when no AI provider key is configured or provider refinement fails
- Implemented in `career/skills_extractor.py`

### 📄 Document Management
- **Upload & CRUD**: Store resumes, cover letters, portfolios, and other docs
- **Versioning**: `version_number` + `is_current`; upload new versions while keeping version history
- **Hosted private storage**: when `DOCUMENT_BLOB_READ_WRITE_TOKEN` is configured, documents are stored as private Vercel Blob assets and opened through an authenticated download endpoint
- **Linking**: Documents can optionally link to an application
- **Locking Rules**: Locked versions preserve the whole document chain from delete-all and single-delete operations
- **Export**: Export documents in csv/json/xlsx formats

### 👤 Experience
- Full CRUD for work experience entries (title, company, location, start/end dates, description, skills, employment type)
- **Application → Experience lifecycle**: every application and experience belongs to a shared `CareerRecord`; linking an offer to Experience reuses the application's record and atomically marks the application `ACCEPTED` while leaving it visible in Applications
- Skills are auto-extracted from descriptions and can be AI-refined after save when a provider key is configured
- Experience data is the shared context for all AI features
- **Company logo upload**: `POST /api/career/experiences/{id}/upload-logo/` (multipart) and `DELETE /api/career/experiences/{id}/remove-logo/`; logos are stored as URL-backed assets and use Vercel Blob automatically when `BLOB_READ_WRITE_TOKEN` is configured
- **Raise History**: each experience can link to an Offer; raise events (date, type, before/after base/bonus/equity, label, notes) are stored as a JSON array on the linked Offer's `raise_history` field
- **Structured team history**: `team_history` JSON stores named team entries and norms metadata for use in the frontend Team History modal
- **Internship compensation model**: hourly roles support `hourly_rate`, `hours_per_day`, `working_days_per_week`, `total_hours_worked`, `overtime_hours`, `overtime_rate`, `overtime_multiplier`, and `total_earnings_override`
- **Multi-phase internship schedules**: `schedule_phases` JSON stores phase-by-phase internship schedule and compensation overrides
- **Experience import/export**: export all experiences in CSV/JSON/XLSX; JSON preserves the richest payload including `schedule_phases`, `team_history`, linked `offer` snapshots, linked `application` snapshots, and logo data
- **Atomic import pipeline**: experience import reconstructs related `Company`, `Application`, and `Offer` records when present, then restores logo files and Experience records inside a DB transaction
- **AI artifact backup**: account exports include backend-saved JD reports, cover letters, and negotiation results, and backup restore can recreate them in merge or replace mode
- **Offer decision history backup**: account exports include offer decision snapshots; restore can recreate snapshots and their linked offers from exported point-in-time offer data when needed

### 📅 Availability & Events
- **Event Scheduling**: Create interview events with start/end times, company linkage, and timezone support
- **Unified Calendar Operations**: Standard Events and Holidays endpoints support create/edit flows from the Availability, Events, and Holiday Manager calendars
- **Holiday Detection & Management**: Auto-populate U.S. federal holidays; add custom and custom-federal holidays; ignore specific holidays dynamically; group multi-day collections; assign holidays to user-defined **custom tabs** (e.g., "Inauspicious Days") via the `tab` field
- **Availability Generation**: Generate user-defined week-long availability text blocks from work settings, holidays, and event conflicts; today's active ranges are clipped to the next 30-minute boundary instead of removed wholesale
- **Public Booking Links**: Generate/deactivate share links with branded page copy, slot duration, buffer rules, max meetings/day, reschedule/cancel cutoff hours, cancel reasons, per-link booking analytics, and locked internal events
- **Conflict Detection APIs**: conflicts are surfaced through the standard REST endpoints and the frontend notification polling flow

### ⚙️ Settings
- **User Preferences**: Singleton settings model (`id=1`) for ghosting threshold, timezone, work hours, work days, buffer time, default event duration, default event category used by new event forms, and notification preferences
- **Mobile Toolbar Preferences** (`mobile_toolbar_items` JSONField): Persist an ordered, validated set of up to four mobile navigation slots per user, including one optional `__smart__` slot; empty values retain the default Home, Applications, Offers, and Insights toolbar
- **Profile Identity**: Stores `display_name` (for public booking links) and `profile_picture` (Vercel Blob backed) as part of the user's core identity.
- **Privacy Export Center APIs**: Account-level export, backup restore, and confirmed account deletion endpoints live under `user-settings`.
- **Multiple Availability Time Ranges** (`work_time_ranges` JSONField): Define multiple non-contiguous availability windows with optional `days` lists for day-specific schedules (e.g., Mon–Thu 10am–3pm, Fri 1pm–4pm); overrides the legacy single `work_start_time`/`work_end_time` fields when non-empty; availability generation merges matching ranges after subtracting event conflicts
- **Employment Types** (`employment_types` JSONField): User-configurable list of `{value, label, color}` employment type definitions — consumed by the Experience page; supports add/edit/delete with 10 color options
- **Holiday Tabs** (`holiday_tabs` JSONField): User-defined tab definitions `{id, name}` for organizing holidays in the Holiday Manager beyond the default Custom/Federal split
- **Ignored Federal Holidays** (`ignored_federal_holidays`): List of federal holiday names to suppress from the calendar
- **Event Categories** (`EventCategory` model): Named + colored + icon-tagged categories; supports `is_locked` to prevent accidental deletion via the UI; PATCH endpoint for partial updates
- **Auto-Ghosted Logic**: Configurable threshold; a secured cron endpoint runs daily maintenance to mark stale applications as GHOSTED and expire stale share links
- **Google Sheets Integrations**: Per-user sync configs store sheet links, target type, worksheet/tab metadata, generated column mappings, preferred daily sync time/timezone, row hashes, last run status, import results, and last-run change history

### 🔐 Authentication & Security
- **JWT login flow**: `/api/auth/login/` issues access + refresh tokens, `/api/auth/refresh/` rotates both tokens, and used refresh tokens are blacklisted
- **Account Management**: Supports updating user `first_name` and `last_name` via `PATCH /api/auth/me/`.
- **Password Security**: `/api/auth/password-change/` handles secure password updates with old-password verification. Passwords are never stored in plain text; they are encrypted using industry-standard hashing algorithms.
- **Bearer-protected API access**: authenticated API routes accept `Authorization: Bearer <access-token>` while session auth remains available for local admin/test workflows

### ⚡ Runtime & Background Work

- **Optional Redis Cache** (`django-redis`)
  - Analytics widget query results cached with MD5 keys (5 min TTL)
  - `UserSettings` primary timezone cached per booking session (10 min TTL)
  - Cache auto-invalidated via `post_save`/`post_delete` signals on `Event` and `Application`
  - Graceful fallback to in-memory cache when Redis is unavailable or intentionally omitted

- **Secured Cron Endpoint**
  - `GET /api/internal/cron/daily-maintenance/`
  - `GET /api/internal/cron/google-sheet-syncs/`
  - guarded by `CRON_SECRET` via the `Authorization: Bearer ...` header that Vercel automatically sends for cron invocations
  - Hobby-safe Vercel deploys run one daily cron at `0 8 * * *`; daily maintenance handles stale applications, share links, account deletion purges, and enabled Google Sheets syncs

- **Rate Limiting**
  - `PublicBookingSlotsThrottle`: 20 GET requests/minute per IP
  - `PublicBookingCreateThrottle`: 5 POST requests/minute per IP
  - Vercel edge mitigation denies common scanner paths such as `.env`, `.git`, WordPress probes, and phpMyAdmin probes before they reach Django
  - `vercel-firewall-actions.json` contains the Hobby-compatible Vercel Firewall actions for bot logging, AI bot blocking, and one sensitive API flood-limit rule

## 🛠 Tech Stack

### Core Framework
- **Django 5.x** - Python web framework
- **Django REST Framework** - Toolkit for building RESTful APIs
- **PostgreSQL** - Primary production database via `DATABASE_URL`
- **SQLite** - Local fallback when `DATABASE_URL` is unset

### AI / NLP
- **User-provided AI provider** - Encrypted backend relay with Claude, Gemini, OpenAI, OpenRouter, and custom adapters for JD matching, cover letters, job URL import, negotiation advice, and analytics widget fallback
- **Lightweight keyword/acronym extractor** - Skill extraction from free-text experience descriptions without heavyweight runtime NLP dependencies

### Distributed Systems
- **django-redis** - Optional Redis cache backend for shared caching/throttling

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
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.docker.txt
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

| Variable | Production Value |
|---|---|
| `SESSION_COOKIE_SECURE` | `True` |
| `CSRF_COOKIE_SECURE` | `True` |
| `SECURE_SSL_REDIRECT` | `True` |
| `SECURE_HSTS_SECONDS` | `31536000` |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` |
| `AI_PROVIDER_ALLOWED_HOSTS` | `api.anthropic.com,generativelanguage.googleapis.com,api.openai.com,openrouter.ai` if you enforce an AI relay allowlist |
| `GOOGLE_OAUTH_CLIENT_ID` | Google Cloud OAuth web client ID for private Google Sheets access |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google Cloud OAuth web client secret |
| `GOOGLE_OAUTH_SUCCESS_REDIRECT_URL` | Frontend Settings URL to use if OAuth callback cannot use stored state redirect |

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


### Migration Workflow

When you change Django models, always generate and commit migrations.

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
```

### Optional: Django Admin
```bash
python manage.py createsuperuser
```
Access at `http://localhost:8000/admin`.

## 📁 Project Structure

```
api/
├── src/                      # Importable Django source packages
│   ├── availability/         # Availability calendar & events module
│   │   ├── models.py         # Event, CustomHoliday, UserSettings, ShareLink, PublicBooking
│   │   ├── serializers.py    # DRF serializers
│   │   ├── views/            # API ViewSets (CRUD + export endpoints)
│   │   ├── throttling.py     # Redis rate-limit throttle classes
│   │   ├── tasks.py          # HTTP-triggered maintenance helpers
│   │   ├── ai_provider.py    # Encryption helpers and authenticated provider relay
│   │   ├── signals.py        # Cache invalidation signals
│   │   ├── migrations/       # Database migrations
│   │   └── utils.py          # Utilities (holiday fetching, export helpers)
│   │
│   ├── career/               # Job applications, offers & AI tools module
│   │   ├── models.py         # Applications, offers, experiences, canonical contacts, career records, and relationship models
│   │   ├── serializers.py    # DRF serializers with auto company creation and export payloads
│   │   ├── views/            # API ViewSets (package)
│   │   ├── skills_extractor.py
│   │   ├── services/         # Business logic (career records, reference data, rent, weekly review, Google Sheets, storage)
│   │   ├── tasks.py          # Maintenance helper: auto_ghost_stale_applications
│   │   ├── migrations/       # Database migrations
│   │   └── urls.py           # URL routing
│   │
│   ├── analytics/            # Analytics app support
│   │   └── signals.py        # Cache bust on Event/Application change
│   │
│   └── config/               # Django project settings
│       ├── settings.py       # Configuration (security, environment modes, PostgreSQL/SQLite, cache, CORS)
│       ├── asgi.py           # HTTP-only ASGI entrypoint
│       ├── cron_views.py     # Secured cron endpoint for background maintenance
│       └── urls.py           # Root URL configuration
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
- `GET /api/career/application-timeline-analytics/` — Return timeline-driven application analytics, including time-to-interview, stage conversion, stale in-stage warnings, and offer rates by source/sheet/company

#### Offers
- `GET /api/career/offers/` — List all offers
- `POST /api/career/offers/` — Create a new offer
- `GET /api/career/offers/{id}/` — Retrieve offer details
- `PUT /api/career/offers/{id}/` — Update offer
- `DELETE /api/career/offers/{id}/` — Delete offer

Offer payloads expose `equity_liquidity` (`LIQUID`, `BUYBACK`, or `ILLIQUID`) and `equity_buyback_value`. Existing offers default to `LIQUID` for backward-compatible calculations.

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
