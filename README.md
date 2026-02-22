# 🔧 Backend - Django REST API

A robust Django REST Framework API powering the CareerHub job search platform.

![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![DRF](https://img.shields.io/badge/DRF-red?style=for-the-badge&logo=django&logoColor=white)

## 📋 Table of Contents
- [Overview](#-overview)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
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
- **Holiday Detection**: Automatically populate U.S. federal holidays for the current year
- **Availability Generation**: Generate availability text from work settings, holidays, and event conflicts
- **Public Booking Links**:
  - generate/deactivate share links
  - public slots endpoint returns only available slots (no private event/holiday details)
  - public booking endpoint creates a locked internal event to block the booked slot

### ⚙️ Settings
- **User Preferences**: Singleton settings model for ghosting threshold and timezone
- **Auto-Ghosted Logic**: Configurable threshold to auto-update stale applications

## 🛠 Tech Stack

### Core Framework
- **Django 5.x** - Python web framework
- **Django REST Framework** - Toolkit for building RESTful APIs
- **SQLite** - Default database (easily swappable to PostgreSQL/MySQL)

### Data Processing
- **Pandas** - CSV/XLSX parsing and data manipulation
- **openpyxl** - Excel file handling

### Utilities
- **django-cors-headers** - CORS middleware for frontend integration
- **holidays** - Federal holiday detection library

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- pip

### Installation

1. **Navigate to backend directory**
   ```bash
   cd api
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Migrations**
   ```bash
   python manage.py migrate
   ```
   
   This will automatically create the `db.sqlite3` database file with all necessary tables.

4. **Start the Development Server**
   ```bash
   python manage.py runserver
   ```

The API will be available at `http://localhost:8000/api`.

### Migration Workflow (Important)

When you change Django models, always generate and commit migrations.

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
```

Commit both:
- model changes (for example `career/models.py`)
- generated migration files (for example `career/migrations/0017_*.py`)

If migrations are not committed, other environments will fail with DB schema errors (for example `no such column ...`).

### Optional: Create a Superuser
```bash
python manage.py createsuperuser
```

Access the Django Admin at `http://localhost:8000/admin` to manage data via a GUI.

## 📁 Project Structure

```
backend/
├── availability/              # Availability calendar & events module
│   ├── models.py             # Event, Holiday, DayAvailability, Settings models
│   ├── serializers.py        # DRF serializers
│   ├── views.py              # API ViewSets (CRUD + export endpoints)
│   ├── urls.py               # URL routing
│   └── utils.py              # Utilities (holiday fetching, export helpers)
│
├── career/                   # Job applications & offers module
│   ├── models.py             # Company, Application, Offer models
│   ├── serializers.py        # DRF serializers with auto company creation
│   ├── views.py              # API ViewSets + auto-offer creation logic
│   └── urls.py               # URL routing
│
├── availability_manager/     # Django project settings
│   ├── settings.py           # Configuration (CORS, DRF, database)
│   └── urls.py               # Root URL configuration
│
├── db.sqlite3                # SQLite database (auto-created, not committed)
├── manage.py                 # Django management script
└── requirements.txt          # Python dependencies
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
- `GET /api/holidays/` - List all holidays
- `POST /api/holidays/` - Create a custom holiday
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
