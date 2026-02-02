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
- **Compensation Tracking**: Store Base Salary, Bonus, Equity, Sign-On, Benefits, and PTO Days
- **Auto-Creation**: When an application's status becomes "OFFER", a placeholder offer is automatically created
- **Is Current Flag**: Mark one offer as your baseline "Current Role" for comparisons

### 📅 Availability & Events
- **Event Scheduling**: Create interview events with start/end times, company linkage, and timezone support
- **Holiday Detection**: Automatically populate U.S. federal holidays for the current year
- **Day Availability**: Mark specific dates as available/unavailable for interviews
- **Weekly View**: API endpoint to fetch a week's worth of availability data

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
   cd backend
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

4. **Load Sample Data (Optional)**
   ```bash
   python manage.py loaddata fixtures/sample_data.json
   ```

5. **Start the Development Server**
   ```bash
   python manage.py runserver
   ```

The API will be available at `http://localhost:8000/api`.

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
├── fixtures/                 # Sample data for quick setup
│   └── sample_data.json      # Django fixture with demo data
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

#### Applications
- `GET /api/applications/` - List all applications
- `POST /api/applications/` - Create a new application
- `GET /api/applications/{id}/` - Retrieve application details
- `PUT /api/applications/{id}/` - Update application (auto-creates offer if status → OFFER)
- `DELETE /api/applications/{id}/` - Delete application
- `POST /api/applications/import/` - Bulk import from CSV/XLSX
- `GET /api/applications/export/?fmt=csv` - Export applications (csv/json/xlsx)
- `DELETE /api/applications/delete_all/` - Delete all applications

#### Offers
- `GET /api/offers/` - List all offers
- `POST /api/offers/` - Create a new offer
- `GET /api/offers/{id}/` - Retrieve offer details
- `PUT /api/offers/{id}/` - Update offer
- `DELETE /api/offers/{id}/` - Delete offer

#### Companies
- `GET /api/companies/` - List all companies
- `POST /api/companies/` - Create a new company

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

#### Day Availability
- `GET /api/availability/` - List day availability records
- `POST /api/availability/` - Mark a day as available/unavailable
- `GET /api/availability/week/?start=YYYY-MM-DD` - Get week view

#### Settings
- `GET /api/settings/1/` - Retrieve user settings
- `PUT /api/settings/1/` - Update settings (ghosting threshold, timezone)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.txt) file for details.

## 👤 Author

**Richie Zhou**

- GitHub: [@arunike](https://github.com/arunike)

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- pip

## 📊 Database Models

### Availability Module

#### `Event`
- **Fields**: `title`, `company`, `start_datetime`, `end_datetime`, `timezone`, `description`, `event_type`
- **Purpose**: Store interview events and meetings

#### `Holiday`
- **Fields**: `date`, `name`, `is_federal`
- **Purpose**: Track federal and custom holidays

#### `DayAvailability`
- **Fields**: `date`, `is_available`, `reason`
- **Purpose**: Mark specific days as available/unavailable

#### `Settings`
- **Fields**: `ghosting_threshold_days`, `my_timezone`
- **Purpose**: User preferences (singleton model)

### Career Module

#### `Company`
- **Fields**: `name`, `website`, `industry`
- **Purpose**: Store company information (auto-deduplicated)

#### `Application`
- **Fields**: `company` (FK), `role_title`, `status`, `rto_policy`, `location`, `salary_range`, `notes`, `date_applied`
- **Choices**: 
  - Status: `APPLIED`, `OA`, `SCREEN`, `ONSITE`, `OFFER`, `REJECTED`, `ACCEPTED`, `GHOSTED`
  - RTO: `REMOTE`, `HYBRID`, `ONSITE`, `UNKNOWN`

#### `Offer`
- **Fields**: `application` (FK), `base_salary`, `bonus`, `equity`, `sign_on`, `benefits_value`, `pto_days`, `is_current`
- **Purpose**: Store compensation details

## 🔗 API Endpoints

### Availability Endpoints
- `GET/POST /api/events/` - List/Create events
- `GET/PUT/DELETE /api/events/{id}/` - Retrieve/Update/Delete event
- `GET /api/events/export/?fmt=csv` - Export events
- `DELETE /api/events/delete_all/` - Delete all events

- `GET/POST /api/holidays/` - List/Create holidays
- `GET /api/holidays/export/?fmt=json` - Export holidays

- `GET/POST /api/availability/` - Manage day availability
- `GET /api/availability/week/?start=YYYY-MM-DD` - Get week view

- `GET/PUT /api/settings/1/` - User settings (singleton)

### Career Endpoints
- `GET/POST /api/companies/` - List/Create companies
- `GET/POST /api/applications/` - List/Create applications
- `POST /api/applications/import/` - Bulk import from CSV/XLSX
- `GET /api/applications/export/?fmt=xlsx` - Export applications
- `DELETE /api/applications/delete_all/` - Delete all applications

- `GET/POST /api/offers/` - List/Create offers
- `GET/PUT/DELETE /api/offers/{id}/` - Manage offer details

## ✨ Special Features

### Auto-Offer Creation
When an `Application`'s status is updated to `OFFER`, the backend automatically creates a placeholder `Offer` object with default values (via `perform_update` in `ApplicationViewSet`).

### Company Auto-Creation
The `ApplicationSerializer` handles `company_name` (write-only) and automatically creates or retrieves the `Company` object using `get_or_create`.

### Import/Export Utilities
- **Import**: Accepts CSV/XLSX with columns: `company`, `role`, `status`, `location`, `salary`, `date_applied`
- **Export**: Supports CSV, JSON, XLSX formats via the `export_data` utility function

### Federal Holidays
The `get_federal_holidays()` utility function uses the `holidays` library to automatically populate U.S. federal holidays.

## 🛠 Tech Stack

- **Django 5.x** - Web framework
- **Django REST Framework** - RESTful API toolkit
- **django-cors-headers** - CORS support for React frontend
- **Pandas** - CSV/XLSX processing
- **openpyxl** - Excel file handling
- **holidays** - Federal holiday detection

### Installation

1. **Navigate to backend directory**
   ```bash
   cd backend
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run migrations**
   ```bash
   python manage.py migrate
   ```

4. **Load sample data (optional)**
   ```bash
   python manage.py loaddata fixtures/sample_data.json
   ```

5. **Start the development server**
   ```bash
   python manage.py runserver
   ```

The API will be available at `http://localhost:8000`.

## 🧪 Development

### Create a superuser (optional)
```bash
python manage.py createsuperuser
```

### Access Django Admin
Navigate to `http://localhost:8000/admin` to manage data via the Django Admin interface.

### Export current data as fixtures
```bash
python manage.py dumpdata career availability --indent 2 -o fixtures/sample_data.json
```

## 📁 Project Structure

```
backend/
├── availability/              # Availability calendar & events module
│   ├── models.py             # Event, Holiday, DayAvailability models
│   ├── serializers.py        # DRF serializers
│   ├── views.py              # API ViewSets (CRUD + export)
│   ├── urls.py               # URL routing
│   └── utils.py              # Utility functions (holidays, exports)
│
├── career/                   # Job applications & offers module
│   ├── models.py             # Company, Application, Offer models
│   ├── serializers.py        # DRF serializers with auto company creation
│   ├── views.py              # API ViewSets + auto-offer creation logic
│   └── urls.py               # URL routing
│
├── fixtures/                 # Sample data for quick setup
│   └── sample_data.json      # Loadable fixture with demo data
│
├── availability_manager/     # Django project settings
│   ├── settings.py           # Main configuration
│   └── urls.py               # Root URL configuration
│
├── db.sqlite3                # SQLite database (not committed)
├── manage.py                 # Django management script
└── requirements.txt          # Python dependencies
```

## 🔗 Frontend

- **Frontend**: [CareerHub Frontend](https://github.com/arunike/CareerHub-Frontend)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.txt) file for details.

## 👤 Author

**Richie Zhou**

- GitHub: [@arunike](https://github.com/arunike)