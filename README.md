# 🔧 Backend - Django REST API

A robust Django REST Framework API powering the CareerHub job search platform.

![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![DRF](https://img.shields.io/badge/DRF-red?style=for-the-badge&logo=django&logoColor=white) ![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white) ![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

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
The **Backend** is a Django REST Framework-powered API that provides all the data management, business logic, and endpoints for the CareerHub platform. It handles job application tracking, offer management, availability calendars, interview event scheduling, and the secure data APIs consumed by the frontend's browser-side AI tools.

**Key Capabilities:**
- 🔗 **RESTful API**: Full CRUD operations for Applications, Offers, Events, Holidays, Documents, Tasks, Experience, and Settings
- 🤖 **Browser-Side AI Support**: Frontend BYOK flows pull context from standard APIs and call the user's configured AI provider directly
- 📥 **Import/Export**: Bulk CSV/XLSX import plus multi-format export (CSV, JSON, XLSX), including full-fidelity Experience import/export with linked offer/application snapshots
- 🏢 **Company Deduplication**: Intelligent `get_or_create` logic to prevent duplicate companies
- 📅 **Federal Holidays**: Automatic U.S. holiday detection using the `holidays` library
- 🌐 **CORS Enabled**: Ready for frontend integration
- ⚡ **Redis-Powered**: Caching, rate limiting, real-time WebSocket alerts, and async task queue
- 🐳 **Docker Ready**: One-command startup with Docker Compose

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
- **Negotiation Context API**: Offer and Application data power the frontend's browser-side negotiation advisor

### 🤖 Frontend BYOK AI

> AI provider configuration now lives in the frontend Settings page and is stored locally in the browser.

- **JD Matcher**: the frontend fetches Experience data from the API, builds the prompt in the browser, and calls the user's configured OpenAI-compatible provider directly
- **Cover Letter Generator**: the frontend combines Application + Experience context in the browser and sends it straight to the user's configured provider
- **Offer Negotiation Advisor**: the frontend uses Offer/Application/Experience APIs as context for browser-side negotiation generation
- **Analytics Custom Widgets**: deterministic queries run in the frontend; free-form queries fall back to the user's configured provider using a frontend-built summary snapshot

#### Skill Extraction (NLP, background)
- Extracts skills from Experience descriptions using NLTK + spaCy
- Runs automatically on `Experience` create/update
- Implemented in `career/skills_extractor.py`

### 📄 Document Management
- **Upload & CRUD**: Store resumes, cover letters, portfolios, and other docs
- **Versioning**: `version_number` + `is_current`; upload new versions while keeping version history
- **Linking**: Documents can optionally link to an application
- **Locking Rules**: Locked documents cannot be deleted
- **Export**: Export documents in csv/json/xlsx formats

### 👤 Experience
- Full CRUD for work experience entries (title, company, location, start/end dates, description, skills, employment type)
- Skills are auto-extracted from description on save (NLP pipeline)
- Experience data is the shared context for all AI features
- **Company logo upload**: `POST /api/career/experiences/{id}/upload-logo/` (multipart) and `DELETE /api/career/experiences/{id}/remove-logo/`; files stored in `media/experience_logos/`
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
- **Real-Time Conflict Alerts**: WebSocket (`ws://host/ws/conflicts/`) broadcasts conflicts instantly via Django Channels + Redis

### ⚙️ Settings
- **User Preferences**: Singleton settings model (`id=1`) for ghosting threshold, timezone, work hours, work days, buffer time, default event duration, default event category, and notification preferences
- **Multiple Availability Time Ranges** (`work_time_ranges` JSONField): Define multiple non-contiguous availability windows per day (e.g., 11am–12pm and 2pm–5pm); overrides the legacy single `work_start_time`/`work_end_time` fields when non-empty; availability generation merges all ranges after subtracting event conflicts
- **Employment Types** (`employment_types` JSONField): User-configurable list of `{value, label, color}` employment type definitions — consumed by the Experience page; supports add/edit/delete with 10 color options
- **Holiday Tabs** (`holiday_tabs` JSONField): User-defined tab definitions `{id, name}` for organizing holidays in the Holiday Manager beyond the default Custom/Federal split
- **Ignored Federal Holidays** (`ignored_federal_holidays`): List of federal holiday names to suppress from the calendar
- **Event Categories** (`EventCategory` model): Named + colored + icon-tagged categories; supports `is_locked` to prevent accidental deletion via the UI; PATCH endpoint for partial updates
- **Auto-Ghosted Logic**: Configurable threshold; Celery task runs daily to mark stale applications as GHOSTED

### ⚡ Distributed Systems

- **Redis Cache** (`django-redis`)
  - Analytics widget query results cached with MD5 keys (5 min TTL)
  - `UserSettings` primary timezone cached per booking session (10 min TTL)
  - Cache auto-invalidated via `post_save`/`post_delete` signals on `Event` and `Application`
  - Graceful fallback to DB when Redis is unavailable

- **Celery + Redis Beat** (`celery`, `django-celery-beat`)
  - `auto_ghost_stale_applications` — daily task; marks applications as GHOSTED past the configured threshold
  - `expire_stale_share_links` — hourly task; deactivates expired `ShareLink` objects
  - `clear_widget_cache` — every 10 min fallback cache wipe
  - Scheduled via `DatabaseScheduler` (configurable from Django admin)

- **Redis Rate Limiting** (DRF `SimpleRateThrottle`)
  - `PublicBookingSlotsThrottle`: 20 GET requests/minute per IP
  - `PublicBookingCreateThrottle`: 5 POST requests/minute per IP

- **Django Channels WebSocket** (`channels[daphne]`, `channels-redis`)
  - `ConflictAlertConsumer` at `ws://host/ws/conflicts/`
  - Broadcasts real-time conflict alerts to all connected clients when event conflicts are detected
  - Served by Daphne ASGI server (handles both HTTP + WebSocket)

## 🛠 Tech Stack

### Core Framework
- **Django 5.x** - Python web framework
- **Django REST Framework** - Toolkit for building RESTful APIs
- **PostgreSQL** - Primary production database via `DATABASE_URL`
- **SQLite** - Local fallback when `DATABASE_URL` is unset

### AI / NLP
- **User-provided OpenAI-compatible provider** - Browser-side BYOK for JD matching, cover letters, negotiation advice, and analytics widget fallback
- **NLTK + spaCy** - Skill extraction from free-text experience descriptions

### Distributed Systems
- **Redis** - Cache backend, Celery broker/backend, and Channel Layer
- **Celery** - Distributed task queue for background and scheduled jobs
- **django-celery-beat** - Database-backed periodic task scheduler
- **Django Channels + Daphne** - ASGI server with WebSocket support
- **channels-redis** - Redis channel layer for Channels
- **django-redis** - Redis cache backend for Django

### Data Processing
- **Pandas** - CSV/XLSX parsing and data manipulation
- **openpyxl** - Excel file handling

### Utilities
- **django-cors-headers** - CORS middleware for frontend integration
- **holidays** - Federal holiday detection library

### Infrastructure
- **Docker + Docker Compose** - Containerised local development and deployment

## 🚀 Getting Started

### Option A — Docker (recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cd api

# First time — build images and start all services
docker compose up --build

# Subsequent runs
docker compose up -d

# Stop everything
docker compose down

# Stream logs
docker compose logs -f api
```

Services started:
| Service | Port | Description |
|---|---|---|
| Postgres | 5432 | Primary application database |
| Redis | 6379 | Cache, broker, channel layer |
| api (Daphne) | 8000 | Django HTTP + WebSocket |
| worker | — | Celery task worker |
| beat | — | Celery periodic scheduler |

API: `http://localhost:8000/api`
WebSocket: `ws://localhost:8000/ws/conflicts/`

---

### Option B — Local (venv)

#### Prerequisites
- Python 3.8+
- Redis running on `localhost:6379`
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

3. **Choose a database**
   ```bash
   # PostgreSQL example
   export DATABASE_URL=postgresql://careerhub:careerhub@localhost:5432/careerhub

   # Or leave DATABASE_URL unset to keep using api/db.sqlite3 locally
   ```

4. **Run Migrations**
   ```bash
   python manage.py migrate
   ```

5. **Start Daphne (ASGI — HTTP + WebSocket)**
   ```bash
   daphne -b 0.0.0.0 -p 8000 config.asgi:application
   ```

6. **Start Celery Worker** (new terminal)
   ```bash
   celery -A config worker --loglevel=info
   ```

7. **Start Celery Beat** (new terminal)
   ```bash
   celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
   ```


## 🐳 Docker

All Docker files live in `api/`:

```
api/
├── Dockerfile            # Multi-stage build (builder + final)
├── docker-compose.yml    # 5 services: postgres, redis, api, worker, beat
├── media/                # Uploaded files (bind-mounted into container at /app/media — persists on host)
├── .env                  # Local secrets (git-ignored)
├── .env.example          # Template — commit this, not .env
├── .dockerignore         # Excludes venv, db, media, etc.
└── requirements.docker.txt  # Clean minimal dependency list
```

> **Media persistence**: uploaded files (e.g. experience logos) are stored in `api/media/` on the host via a bind mount (`./media:/app/media`). Files survive container restarts and rebuilds — no data is stored in Docker named volumes.

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | dev key | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `DATABASE_URL` | unset | PostgreSQL connection string; when unset Django falls back to `db.sqlite3` |
| `DB_CONN_MAX_AGE` | `60` | Django persistent DB connection lifetime in seconds |
| `REDIS_HOST` | `localhost` | Overridden to `redis` by Compose |
| `REDIS_PORT` | `6379` | Redis port |

### 🤖 Configuring AI for the Current App
Current AI features are configured in the frontend, not in `api/.env`:
1. Open the app and go to `Settings` → `AI Provider`.
2. Enter an OpenAI-compatible endpoint, model, and your own API key.
3. Save the provider locally in the browser.
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
│   ├── consumers.py          # WebSocket ConflictAlertConsumer
│   ├── throttling.py         # Redis rate-limit throttle classes
│   ├── tasks.py              # Celery tasks (expire links, clear cache)
│   ├── signals.py            # Cache invalidation signals
│   ├── routing.py            # WebSocket URL routing
│   ├── migrations/           # Database migrations (0001–0023)
│   └── utils.py              # Utilities (holiday fetching, export helpers)
│
├── career/                   # Job applications, offers & AI tools module
│   ├── models.py             # Company, Application, Offer, Document, Task, Experience models
│   ├── serializers.py        # DRF serializers with auto company creation, skill extraction, and Experience export payloads
│   ├── views/                # API ViewSets (package)
│   │   ├── applications.py   # ApplicationViewSet + import/export helpers
│   │   ├── offers.py         # OfferViewSet
│   │   ├── documents.py      # DocumentViewSet with versioning
│   │   ├── experiences.py    # ExperienceViewSet + Experience import/export helpers
│   │   ├── tasks.py          # TaskViewSet with reorder action
│   │   ├── companies.py      # CompanyViewSet
│   │   └── reference.py      # ReferenceDataView, RentEstimateView, WeeklyReviewView
│   ├── skills_extractor.py   # NLTK + spaCy skill extraction
│   ├── services/             # Business logic (reference data, rent, weekly review)
│   ├── tasks.py              # Celery task: auto_ghost_stale_applications
│   └── urls.py               # URL routing
│
├── analytics/                # Analytics app support
│   └── signals.py            # Cache bust on Event/Application change
│
├── config/                   # Django project settings
│   ├── settings.py           # Configuration (security, PostgreSQL/SQLite, Redis, Celery, Channels, CORS)
│   ├── asgi.py               # ASGI app (HTTP + WebSocket via Daphne)
│   └── urls.py               # Root URL configuration
│
├── celery_app.py             # Celery app definition
├── db.sqlite3                # Local SQLite fallback database (optional, not committed)
├── manage.py                 # Django management script
├── requirements.docker.txt   # Minimal Docker dependencies
└── docker-compose.yml        # Multi-service Docker Compose config
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
- `POST /api/career/experiences/{id}/upload-logo/` — Upload company logo (multipart `logo` field)
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
- `GET /api/career/documents/export/?fmt=csv` — Export documents
- `DELETE /api/career/documents/delete_all/` — Delete all unlocked documents

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
- `POST /api/events/` — Create a new event (triggers conflict detection + WebSocket broadcast)
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
- `GET /api/settings/current/` — Retrieve user settings (singleton)
- `PUT /api/settings/current/` — Update all settings fields including `employment_types`, `holiday_tabs`, and `work_time_ranges`

#### WebSocket
- `ws://host/ws/conflicts/` — Real-time conflict alert stream

## 🔗 Frontend

- **Frontend**: [CareerHub Frontend](https://github.com/arunike/CareerHub-Frontend)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.txt) file for details.

## 👤 Author

**Richie Zhou**

- GitHub: [@arunike](https://github.com/arunike)
