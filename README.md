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
- 🤖 **Encrypted AI Provider Relay**: Frontend BYOK flows pull context from standard APIs while provider keys stay encrypted on the backend and requests are relayed server-side
- 📥 **Import/Export**: Bulk CSV/XLSX import plus multi-format export (CSV, JSON, XLSX), including full-fidelity Experience import/export with linked offer/application snapshots
- 🏢 **Company Deduplication**: Intelligent `get_or_create` logic to prevent duplicate companies
- 📅 **Federal Holidays**: Automatic U.S. holiday detection using the `holidays` library
- 🌐 **CORS Enabled**: Ready for frontend integration
- ☁️ **Vercel-Compatible HTTP API**: Django runs as a pure HTTP app with a WSGI entrypoint, external PostgreSQL, and a secured cron endpoint for maintenance jobs
- ⚡ **Optional Shared Cache**: Redis can still be attached for shared caching/throttling, but local development and Vercel deployments no longer depend on it
- 🐳 **Docker Ready (Local Dev)**: One-command local startup with Docker Compose bound to localhost

## ✨ Features

### 🏢 Application Management
- **CRUD API**: Full create, read, update, delete operations for job applications
- **Status Tracking**: Support for 8 application stages (Applied, OA, Screen, Onsite, Offer, Rejected, Accepted, Ghosted)
- **Company Auto-Creation**: Serializer automatically creates `Company` objects from `company_name`
- **Bulk Import**: Upload CSV/XLSX files to import multiple applications at once
- **Export Options**: Download data as CSV, JSON, or XLSX
- **Locking**: Locked applications cannot be deleted
- **Delete All**: Bulk delete endpoint respects lock status

### 💎 Offer Management
- **Compensation Tracking**: Store Base Salary, Bonus, Equity (annual + optional total grant/vesting %), Sign-On, Benefits, PTO Days, and Holiday Days
- **Auto-Creation**: When an application's status becomes "OFFER", a placeholder offer is automatically created
- **Is Current Flag**: Mark one offer as your baseline "Current Role" for comparisons
- **Benefit Item Persistence**: Offer-level benefit item breakdown is persisted (JSON) alongside annualized `benefits_value`
- **Negotiation Context API**: Offer and Application data power the frontend negotiation advisor and backend relay flow

### 🤖 Frontend BYOK AI

> AI provider configuration now lives in the frontend Settings page, while the API key is stored encrypted on the backend.

- **JD Matcher**: the frontend fetches Experience data from the API, builds the prompt in the browser, and sends it through the authenticated backend relay
- **Cover Letter Generator**: the frontend combines Application + Experience context in the browser and routes provider requests through the encrypted backend relay
- **Offer Negotiation Advisor**: the frontend uses Offer/Application/Experience APIs as context while the backend relay handles the provider call
- **Analytics Custom Widgets**: deterministic queries run in the frontend; free-form queries use the authenticated backend relay with the user's stored provider config

#### Skill Extraction (NLP, background)
- Extracts skills from Experience descriptions using a lightweight keyword + acronym matcher
- Runs automatically on `Experience` create/update
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
- Skills are auto-extracted from description on save (NLP pipeline)
- Experience data is the shared context for all AI features
- **Company logo upload**: `POST /api/career/experiences/{id}/upload-logo/` (multipart) and `DELETE /api/career/experiences/{id}/remove-logo/`; logos are stored as URL-backed assets and use Vercel Blob automatically when `BLOB_READ_WRITE_TOKEN` is configured
- **Raise History**: each experience can link to an Offer; raise events (date, type, before/after base/bonus/equity, label, notes) are stored as a JSON array on the linked Offer's `raise_history` field
- **Structured team history**: `team_history` JSON stores named team entries and norms metadata for use in the frontend Team History modal
- **Internship compensation model**: hourly roles support `hourly_rate`, `hours_per_day`, `working_days_per_week`, `total_hours_worked`, `overtime_hours`, `overtime_rate`, `overtime_multiplier`, and `total_earnings_override`
- **Multi-phase internship schedules**: `schedule_phases` JSON stores phase-by-phase internship schedule and compensation overrides
- **Experience import/export**: export all experiences in CSV/JSON/XLSX; JSON preserves the richest payload including `schedule_phases`, `team_history`, linked `offer` snapshots, linked `application` snapshots, and logo data
- **Atomic import pipeline**: experience import reconstructs related `Company`, `Application`, and `Offer` records when present, then restores logo files and Experience records inside a DB transaction

### 📅 Availability & Events
- **Event Scheduling**: Create interview events with start/end times, company linkage, and timezone support
- **Holiday Detection & Management**: Auto-populate U.S. federal holidays; add custom and custom-federal holidays; ignore specific holidays dynamically; group multi-day collections; assign holidays to user-defined **custom tabs** (e.g., "Inauspicious Days") via the `tab` field
- **Availability Generation**: Generate availability text blocks from work settings, holidays, and event conflicts
- **Public Booking Links**: Generate/deactivate share links; public slots endpoint; booking creates a locked internal event
- **Conflict Detection APIs**: conflicts are surfaced through the standard REST endpoints and the frontend notification polling flow

### ⚙️ Settings
- **User Preferences**: Singleton settings model (`id=1`) for ghosting threshold, timezone, work hours, work days, buffer time, default event duration, default event category, and notification preferences
- **Multiple Availability Time Ranges** (`work_time_ranges` JSONField): Define multiple non-contiguous availability windows per day (e.g., 11am–12pm and 2pm–5pm); overrides the legacy single `work_start_time`/`work_end_time` fields when non-empty; availability generation merges all ranges after subtracting event conflicts
- **Employment Types** (`employment_types` JSONField): User-configurable list of `{value, label, color}` employment type definitions — consumed by the Experience page; supports add/edit/delete with 10 color options
- **Holiday Tabs** (`holiday_tabs` JSONField): User-defined tab definitions `{id, name}` for organizing holidays in the Holiday Manager beyond the default Custom/Federal split
- **Ignored Federal Holidays** (`ignored_federal_holidays`): List of federal holiday names to suppress from the calendar
- **Event Categories** (`EventCategory` model): Named + colored + icon-tagged categories; supports `is_locked` to prevent accidental deletion via the UI; PATCH endpoint for partial updates
- **Auto-Ghosted Logic**: Configurable threshold; a secured cron endpoint runs daily maintenance to mark stale applications as GHOSTED and expire stale share links

### 🔐 Authentication
- **JWT login flow**: `/api/auth/login/` issues access + refresh tokens, `/api/auth/refresh/` rotates both tokens, and used refresh tokens are blacklisted
- **Bearer-protected API access**: authenticated API routes accept `Authorization: Bearer <access-token>` while session auth remains available for local admin/test workflows

### ⚡ Runtime & Background Work

- **Optional Redis Cache** (`django-redis`)
  - Analytics widget query results cached with MD5 keys (5 min TTL)
  - `UserSettings` primary timezone cached per booking session (10 min TTL)
  - Cache auto-invalidated via `post_save`/`post_delete` signals on `Event` and `Application`
  - Graceful fallback to in-memory cache when Redis is unavailable or intentionally omitted

- **Secured Cron Endpoint**
  - `GET /api/internal/cron/daily-maintenance/`
  - guarded by `CRON_SECRET` via the `Authorization: Bearer ...` header that Vercel automatically sends for cron invocations
  - runs `auto_ghost_stale_applications` and `expire_stale_share_links`

- **Rate Limiting**
  - `PublicBookingSlotsThrottle`: 20 GET requests/minute per IP
  - `PublicBookingCreateThrottle`: 5 POST requests/minute per IP

## 🛠 Tech Stack

### Core Framework
- **Django 5.x** - Python web framework
- **Django REST Framework** - Toolkit for building RESTful APIs
- **PostgreSQL** - Primary production database via `DATABASE_URL`
- **SQLite** - Local fallback when `DATABASE_URL` is unset

### AI / NLP
- **User-provided OpenAI-compatible provider** - Encrypted backend relay for JD matching, cover letters, negotiation advice, and analytics widget fallback
- **Lightweight keyword/acronym extractor** - Skill extraction from free-text experience descriptions without heavyweight runtime NLP dependencies

### Distributed Systems
- **django-redis** - Optional Redis cache backend for shared caching/throttling

### Data Processing
- **Pandas** - CSV/XLSX parsing and data manipulation
- **openpyxl** - Excel file handling

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
2. Enter an OpenAI-compatible endpoint, model, and your own API key.
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
├── availability/              # Availability calendar & events module
│   ├── models.py             # Event, CustomHoliday (+ tab field), UserSettings
│   │                         #   (+ employment_types, holiday_tabs JSONFields),
│   │                         #   EventCategory (+ is_locked), ShareLink, PublicBooking
│   ├── serializers.py        # DRF serializers (all new fields exposed)
│   ├── views/                # API ViewSets (CRUD + export endpoints)
│   ├── throttling.py         # Redis rate-limit throttle classes
│   ├── tasks.py              # HTTP-triggered maintenance helpers (expire links, clear cache)
│   ├── ai_provider.py        # Encryption helpers and authenticated provider relay
│   ├── signals.py            # Cache invalidation signals
│   ├── migrations/           # Database migrations (0001–0025)
│   └── utils.py              # Utilities (holiday fetching, export helpers)
│
├── career/                   # Job applications, offers & AI tools module
│   ├── models.py             # Company, Application, Offer, Document, Task, Experience models
│   ├── serializers.py        # DRF serializers with auto company creation, skill extraction, and Experience export payloads
│   ├── views/                # API ViewSets (package)
│   │   ├── applications.py   # ApplicationViewSet + import/export helpers
│   │   ├── offers.py         # OfferViewSet
│   │   ├── documents.py      # DocumentViewSet with versioning + authenticated downloads
│   │   ├── experiences.py    # ExperienceViewSet + Experience import/export helpers
│   │   ├── tasks.py          # TaskViewSet with reorder action
│   │   ├── companies.py      # CompanyViewSet
│   │   └── reference.py      # ReferenceDataView, RentEstimateView, WeeklyReviewView
│   ├── skills_extractor.py   # Lightweight keyword/acronym skill extraction
│   ├── services/             # Business logic (reference data, rent, weekly review, logo/document storage)
│   ├── tasks.py              # Maintenance helper: auto_ghost_stale_applications
│   ├── migrations/           # Database migrations (0001–0039)
│   └── urls.py               # URL routing
│
├── analytics/                # Analytics app support
│   └── signals.py            # Cache bust on Event/Application change
│
├── config/                   # Django project settings
│   ├── settings.py           # Configuration (security, environment modes, PostgreSQL/SQLite, cache, CORS)
│   ├── asgi.py               # HTTP-only ASGI entrypoint
│   ├── cron_views.py         # Secured cron endpoint for background maintenance
│   └── urls.py               # Root URL configuration
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
- `POST /api/career/applications/` — Create a new application
- `GET /api/career/applications/{id}/` — Retrieve application details
- `PUT /api/career/applications/{id}/` — Update application (auto-creates offer if status → OFFER)
- `DELETE /api/career/applications/{id}/` — Delete application (blocked if locked)
- `DELETE /api/career/applications/delete_all/` — Delete all unlocked applications
- `POST /api/career/import/` — Bulk import from CSV/XLSX
- `GET /api/career/applications/export/?fmt=csv` — Export applications (csv/json/xlsx)

#### Offers
- `GET /api/career/offers/` — List all offers
- `POST /api/career/offers/` — Create a new offer
- `GET /api/career/offers/{id}/` — Retrieve offer details
- `PUT /api/career/offers/{id}/` — Update offer
- `DELETE /api/career/offers/{id}/` — Delete offer

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

#### Companies
- `GET /api/career/companies/` — List all companies
- `POST /api/career/companies/` — Create a new company

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
- `POST /api/career/tasks/` — Create task
- `PATCH /api/career/tasks/{id}/` — Update task
- `POST /api/career/tasks/reorder/` — Reorder tasks

#### Helpers
- `GET /api/career/reference-data/` — Tax/COL/marital-status reference payload
- `GET /api/career/rent-estimate/?city=San+Jose,+CA,+United+States` — Rent estimate (HUD/fallback)
- `GET /api/career/weekly-review/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` — Weekly summary

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
- `GET /api/availability/generate/?start_date=YYYY-MM-DD&timezone=PT` — Generate availability text rows
- `POST /api/overrides/` — Override a specific date's availability text
- `GET /api/share-links/current/` — Get active booking share link
- `POST /api/share-links/generate/` — Generate a new booking share link
- `POST /api/share-links/deactivate/` — Deactivate current booking share links
- `GET /api/booking/{uuid}/slots/?date=YYYY-MM-DD&timezone=PT` — Public: fetch bookable slots
- `POST /api/booking/{uuid}/book/` — Public: submit a booking (creates locked event)

#### Settings
- `GET /api/user-settings/current/` — Retrieve user settings (singleton)
- `PUT /api/user-settings/current/` — Update all settings fields including `employment_types`, `holiday_tabs`, `work_time_ranges`, and AI provider fields
- `POST /api/user-settings/ai-provider/chat-completions/` — Relay an authenticated OpenAI-compatible chat completion request using the user's encrypted provider key

#### Internal Maintenance
- `GET /api/internal/cron/daily-maintenance/` — Secured daily maintenance hook for Vercel Cron Jobs

#### Authentication
- `POST /api/auth/login/` — Email/password login, returns `user`, `access`, and `refresh`
- `POST /api/auth/refresh/` — Exchange a refresh token for a rotated access/refresh pair; the previous refresh token is invalidated
- `POST /api/auth/logout/` — Logout companion endpoint; if a refresh token is supplied it is blacklisted server-side
- `GET /api/auth/me/` — Fetch the current user with a Bearer access token
- `GET /api/auth/signup-status/` — Public signup capability metadata
- `POST /api/auth/signup/` — Create a new account

## 🔗 Frontend

- **Frontend**: [CareerHub Frontend](https://github.com/arunike/CareerHub-Frontend)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.txt) file for details.

## 👤 Author

**Richie Zhou**

- GitHub: [@arunike](https://github.com/arunike)
