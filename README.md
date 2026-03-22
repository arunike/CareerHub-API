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
The **Backend** is a Django REST Framework-powered API that provides all the data management, business logic, and endpoints for the Availability Manager platform. It handles job application tracking, offer management, availability calendars, and interview event scheduling—all exposed through a clean RESTful API.

**Key Capabilities:**
- 🔗 **RESTful API**: Full CRUD operations for Applications, Offers, Events, and Holidays
- 📥 **Import/Export**: Bulk CSV/XLSX import and multi-format export (CSV, JSON, XLSX, ZIP)
- 🤖 **Auto-Offer Creation**: Automatically creates `Offer` objects when application status changes to "OFFER"
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
- **Export Options**: Download data as CSV, JSON, or XLSX with customizable serializers
- **Delete All**: Bulk delete endpoint for clearing test data

### 💎 Offer Management
- **Compensation Tracking**: Store Base Salary, Bonus, Equity (annual + optional total grant/vesting %), Sign-On, Benefits, PTO Days, and Holiday Days
- **Auto-Creation**: When an application's status becomes "OFFER", a placeholder offer is automatically created
- **Is Current Flag**: Mark one offer as your baseline "Current Role" for comparisons
- **Benefit Item Persistence**: Offer-level benefit item breakdown is persisted (JSON) alongside annualized `benefits_value`

### 🤖 AI JD Matcher
- **LLM-Powered Evaluation**: Analyzes resumes against job descriptions to extract matched skills, missing skills, and generate an actionable executive summary.
- **Skill Extraction**: Advanced parsing of candidate experience and job requirements.
- **Scoring Engine**: Calculates an objective overall match score based on extracted alignment criteria.

### 📄 Document Management
- **Upload & CRUD**: Store resumes, cover letters, portfolios, and other docs
- **Versioning**:
  - each document has `version_number` and `is_current`
  - upload new versions while keeping version history
  - query current-only list or full version list
- **Linking**: Documents can optionally link to an application
- **Locking Rules**: Locked documents cannot be deleted
- **Bulk Delete Rules**: `delete_all` deletes only unlocked documents
- **Export**: Export documents in csv/json/xlsx formats

### 📅 Availability & Events
- **Event Scheduling**: Create interview events with start/end times, company linkage, and timezone support
- **Holiday Detection & Management**: 
  - Automatically populate U.S. federal holidays for the current year
  - Add manually-defined "Custom Federal" holidays that integrate directly into the global federal list
  - Ignore specific federal holidays dynamically
  - Create grouped multi-day custom holiday collections
- **Availability Generation**: Generate availability text from work settings, holidays, and event conflicts
- **Public Booking Links**:
  - generate/deactivate share links
  - public slots endpoint returns only available slots (no private event/holiday details)
  - public booking endpoint creates a locked internal event to block the booked slot

### ⚙️ Settings
- **User Preferences**: Singleton settings model for ghosting threshold and timezone
- **Auto-Ghosted Logic**: Configurable threshold to auto-update stale applications

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
  - Throttle state stored in Redis; gracefully falls back to LocMemCache in tests

- **Django Channels WebSocket** (`channels[daphne]`, `channels-redis`)
  - `ConflictAlertConsumer` at `ws://host/ws/conflicts/`
  - Broadcasts real-time conflict alerts to all connected clients when event conflicts are detected
  - Served by Daphne ASGI server (handles both HTTP + WebSocket)

## 🛠 Tech Stack

### Core Framework
- **Django 5.x** - Python web framework
- **Django REST Framework** - Toolkit for building RESTful APIs
- **SQLite** - Default database (easily swappable to PostgreSQL/MySQL)

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

3. **Run Migrations**
   ```bash
   python manage.py migrate
   ```

4. **Start Daphne (ASGI — HTTP + WebSocket)**
   ```bash
   daphne -b 0.0.0.0 -p 8000 config.asgi:application
   ```

5. **Start Celery Worker** (new terminal)
   ```bash
   celery -A config worker --loglevel=info
   ```

6. **Start Celery Beat** (new terminal)
   ```bash
   celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
   ```


## 🐳 Docker

All Docker files live in `api/`:

```
api/
├── Dockerfile            # Multi-stage build (builder + final)
├── docker-compose.yml    # 4 services: redis, api, worker, beat
├── .env                  # Local secrets (git-ignored)
├── .env.example          # Template — commit this, not .env
├── .dockerignore         # Excludes venv, db, media, etc.
└── requirements.docker.txt  # Clean minimal dependency list
```

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | dev key | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `REDIS_HOST` | `localhost` | Overridden to `redis` by Compose |
| `REDIS_PORT` | `6379` | Redis port |
| `LLM_API_KEY` | `your-api-key-here` | Required for AI JD Matcher. Get your free API key from Google AI Studio. |
| `LLM_API_URL` | `https://generat...` | Default points to Gemini's OpenAI-compatible endpoint. |
| `LLM_MODEL` | `gemini-2.0-flash` | The model to use for the JD Matching engine. |

### 🤖 Configuring the AI API Key
The JD Matcher uses Google's Gemini models via their OpenAI-compatible endpoint by default.
1. Create a copy of `.env.example` and name it `.env` in the `api/` directory.
2. Get your free API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
3. Paste the key into your `.env` file: `LLM_API_KEY=your-actual-api-key-here`.
4. Restart docker containers or your local server for the changes to take effect.


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
│   ├── models.py             # Event, Holiday, DayAvailability, Settings models
│   ├── serializers.py        # DRF serializers
│   ├── views/                # API ViewSets (CRUD + export endpoints)
│   ├── consumers.py          # WebSocket ConflictAlertConsumer
│   ├── throttling.py         # Redis rate-limit throttle classes
│   ├── tasks.py              # Celery tasks (expire links, clear cache)
│   ├── signals.py            # Cache invalidation signals
│   ├── routing.py            # WebSocket URL routing
│   └── utils.py              # Utilities (holiday fetching, export helpers)
│
├── career/                   # Job applications & offers module
│   ├── models.py             # Company, Application, Offer models
│   ├── serializers.py        # DRF serializers with auto company creation
│   ├── views.py              # API ViewSets + auto-offer creation logic
│   ├── tasks.py              # Celery task: auto_ghost_stale_applications
│   └── urls.py               # URL routing
│
├── analytics/                # Custom widget query engine
│   ├── custom_widgets.py     # Redis-cached NL query processor
│   ├── signals.py            # Cache bust on Event/Application change
│   └── tests.py              # Widget + cache test suite
│
├── config/                   # Django project settings
│   ├── settings.py           # Configuration (Redis, Celery, Channels, CORS)
│   ├── asgi.py               # ASGI app (HTTP + WebSocket via Daphne)
│   └── urls.py               # Root URL configuration
│
├── celery_app.py             # Celery app definition
├── db.sqlite3                # SQLite database (auto-created, not committed)
├── manage.py                 # Django management script
├── requirements.docker.txt   # Minimal Docker dependencies
└── docker-compose.yml        # Multi-service Docker Compose config
```

## 📡 API Documentation

### Career Endpoints

Base prefix: `/api/career/`

#### Applications
- `GET /api/career/applications/` - List all applications
- `POST /api/career/applications/` - Create a new application
- `GET /api/career/applications/{id}/` - Retrieve application details
- `PUT /api/career/applications/{id}/` - Update application (auto-creates offer if status → OFFER)
- `DELETE /api/career/applications/{id}/` - Delete application
- `POST /api/career/import/` - Bulk import from CSV/XLSX
- `GET /api/career/applications/export/?fmt=csv` - Export applications (csv/json/xlsx)
- `DELETE /api/career/applications/delete_all/` - Delete all applications

#### Offers
- `GET /api/career/offers/` - List all offers
- `POST /api/career/offers/` - Create a new offer
- `GET /api/career/offers/{id}/` - Retrieve offer details
- `PUT /api/career/offers/{id}/` - Update offer
- `DELETE /api/career/offers/{id}/` - Delete offer

#### Companies
- `GET /api/career/companies/` - List all companies
- `POST /api/career/companies/` - Create a new company

#### Documents
- `GET /api/career/documents/` - List current document versions
- `GET /api/career/documents/?include_versions=true` - List all versions
- `POST /api/career/documents/` - Upload a document
- `POST /api/career/documents/{id}/add_version/` - Create new version
- `GET /api/career/documents/{id}/versions/` - List version history
- `GET /api/career/documents/export/?fmt=csv` - Export documents
- `DELETE /api/career/documents/delete_all/` - Delete all unlocked documents

#### Tasks
- `GET /api/career/tasks/` - List tasks
- `POST /api/career/tasks/` - Create task
- `PATCH /api/career/tasks/{id}/` - Update task
- `POST /api/career/tasks/reorder/` - Reorder tasks

#### AI Matcher
- `POST /api/career/match/` - Submit a job description to trigger an LLM-powered evaluation against the current user profile. Returns a detailed match analysis report.

#### Offer Comparison Helpers
- `GET /api/career/reference-data/` - Tax/COL/marital-status reference payload
- `GET /api/career/rent-estimate/?city=San+Jose,+CA,+United+States` - Rent estimate (HUD/fallback)
- `GET /api/career/weekly-review/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` - Weekly summary (applications/interviews/next actions)

### Availability Endpoints

#### Events
- `GET /api/events/` - List all events
- `POST /api/events/` - Create a new event
- `GET /api/events/{id}/` - Retrieve event details
- `PUT /api/events/{id}/` - Update event
- `DELETE /api/events/{id}/` - Delete event
- `GET /api/events/export/?fmt=json` - Export events
- `DELETE /api/events/delete_all/` - Delete all events

#### Holidays
- `GET /api/holidays/` - List all custom holidays
- `POST /api/holidays/` - Create a custom holiday (includes grouped collections)
- `GET /api/holidays/federal/` - List native federal + user-defined federal holidays
- `GET /api/holidays/export/?fmt=csv` - Export holidays

#### Availability / Booking
- `GET /api/availability/generate/?start_date=YYYY-MM-DD&timezone=PT` - Generate availability text rows
- `POST /api/overrides/` - Override a specific date's availability text
- `GET /api/share-links/current/` - Get active booking share link (if any)
- `POST /api/share-links/generate/` - Generate a new booking share link
- `POST /api/share-links/deactivate/` - Deactivate current booking share links
- `GET /api/booking/{uuid}/slots/?date=YYYY-MM-DD&timezone=PT` - Public endpoint to fetch bookable slots
- `POST /api/booking/{uuid}/book/` - Public endpoint to submit a booking

#### Settings
- `GET /api/settings/1/` - Retrieve user settings
- `PUT /api/settings/1/` - Update settings (ghosting threshold, timezone)

## 🔗 Frontend

- **Frontend**: [WorkOps API](https://github.com/arunike/CareerHub-Frontend)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.txt) file for details.

## 👤 Author

**Richie Zhou**

- GitHub: [@arunike](https://github.com/arunike)
