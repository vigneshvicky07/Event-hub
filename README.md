# EventHub - Event Ticketing Platform API

EventHub is a production-grade backend REST API for an event ticketing platform built with **Django**, **Django REST Framework (DRF)**, **PostgreSQL 16**, and **Docker**.

Users can:
- Browse and filter events by status and venue
- Reserve seats with concurrency-safe availability deduction and validations
- Cancel reservations with automatic seat restoration and idempotent error handling
- View real-time latency and status logging for every HTTP request via custom middleware

---

## Table of Contents
1. [Tech Stack](#tech-stack)
2. [Project Structure](#project-structure)
3. [Setup & Running Instructions](#setup--running-instructions)
   - [Option A: Running with Docker & PostgreSQL (Recommended)](#option-a-running-with-docker--postgresql-recommended)
   - [Option B: Running Locally with Python Virtualenv (SQLite Fallback)](#option-b-running-locally-with-python-virtualenv-sqlite-fallback)
4. [Validation & Exception Handling System](#validation--exception-handling-system)
5. [API Endpoints Reference](#api-endpoints-reference)
6. [Design Decisions](#design-decisions)
7. [Running Automated Tests](#running-automated-tests)
8. [Postman Guide (Screenshots Checklist)](#postman-guide-screenshots-checklist)

---

## Tech Stack
- **Python** 3.13
- **Django** 6.1
- **Django REST Framework** 3.18
- **PostgreSQL** 16 (Alpine) via `psycopg2-binary`
- **Docker & Docker Compose** for container orchestration
- **SQLite3** available as automated local fallback

---

## Project Structure

```text
Event-hub/
├── Dockerfile                  # Container definition (Python 3.13-slim)
├── docker-compose.yml          # PostgreSQL 16 & Django web service definition
├── entrypoint.sh               # DB readiness probe, automated migrations & startup
├── .env.example                # Environment variables template
├── requirements.txt            # Python dependencies (Django, DRF, psycopg2-binary, etc.)
├── postman_collection.json     # Importable Postman test collection
├── test_eventhub.py            # Standalone API & validation verification suite
├── manage.py
├── README.md
├── eventhub/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py             # Configured for PostgreSQL with SQLite fallback & custom exception handler
│   ├── urls.py                 # Root router with /api/ prefix
│   └── wsgi.py
└── events/
    ├── __init__.py
    ├── admin.py                # Admin registrations for Event & Reservation
    ├── apps.py
    ├── exceptions.py           # Custom DRF exception handler for standardized JSON errors
    ├── middleware.py           # RequestLoggingMiddleware for latency & status logging
    ├── models.py               # Event and Reservation ORM models
    ├── serializers.py          # Field & cross-field validations + atomic create() logic
    ├── tests.py                # Comprehensive test runner (23 unit & integration tests)
    ├── urls.py                 # DefaultRouter configuration
    ├── views.py                # EventViewSet & ReservationViewSet with atomic cancel action
    └── migrations/
        ├── __init__.py
        └── 0001_initial.py
```

---

## Setup & Running Instructions

### Option A: Running with Docker & PostgreSQL (Recommended)

EventHub is fully Dockerized with a dedicated PostgreSQL database container (`eventhub_db`) and application web container (`eventhub_api`).

On container startup, `entrypoint.sh` automatically probes PostgreSQL for readiness, applies all pending migrations, and launches the WSGI development server on port `8000`.

```bash
# 1. Build and start containers in detached mode
docker compose up --build -d

# 2. View live container logs (includes DB wait probe and middleware logs)
docker compose logs -f web

# 3. Run automated test suite inside Docker
docker compose exec web python manage.py test

# 4. Run standalone verification suite inside Docker
docker compose exec web python test_eventhub.py

# 5. Stop containers
docker compose down
```

- **API Base URL**: `http://127.0.0.1:8000/`
- **PostgreSQL Port**: Mapped to host at `localhost:5434` (Internal Docker network connects at `db:5432`)
- **Database Credentials**:
  - DB Name: `eventhub`
  - User: `eventhub_user`
  - Password: `eventhub_password`

---

### Option B: Running Locally with Python Virtualenv (SQLite Fallback)

If Docker is not running, EventHub automatically falls back to SQLite for local development.

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations
python manage.py makemigrations
python manage.py migrate

# 4. Start local development server
python manage.py runserver 0.0.0.0:8000

# 5. Run tests locally
python manage.py test
python test_eventhub.py
```

*Note: You can explicitly force SQLite by setting `USE_SQLITE=true` in your environment.*

---

## Validation & Exception Handling System

Modeled after industry best practices (and the `@devtrack` architecture), EventHub enforces defensive input validation, database integrity protection, concurrency isolation, and consistent JSON error formats.

### 1. Event Validations ([`events/serializers.py`](events/serializers.py))
- **Title Validation (`validate_title`)**: Rejects null, empty, or whitespace-only titles. Automatically trims leading/trailing whitespace.
- **Venue Validation (`validate_venue`)**: Rejects null, empty, or whitespace-only venues. Trims whitespace.
- **Total Seats Validation (`validate_total_seats`)**: Rejects values less than 1 (`Total seats must be at least 1.`).
- **Available Seats Validation (`validate_available_seats`)**: Rejects negative values (`Available seats cannot be negative.`).
- **Cross-Field Availability Validation (`validate`)**: Rejects any state where `available_seats > total_seats` with HTTP 400 (`available_seats cannot exceed total_seats.`).
- **Booking Protection on Update (`validate`)**: When updating `total_seats` on an existing event, checks sum of confirmed reservations and rejects any reduction below currently reserved seats.

### 2. Reservation Validations ([`events/serializers.py`](events/serializers.py))
- **Attendee Name Validation (`validate_attendee_name`)**: Rejects empty or blank strings. Trims whitespace.
- **Attendee Email Validation (`validate_attendee_email`)**: Validates against RFC email format specifications. Trims and converts to lowercase.
- **Minimum Seat Validation (`validate_seats_reserved`)**: Rejects values < 1 with HTTP 400 (`Must reserve at least 1 seat.`).
- **Event Lifecycle Validation (`validate`)**: Validates that target event status is either `upcoming` or `ongoing`. Rejects reservations on `completed` or `cancelled` events (`Cannot reserve seats for a {status} event.`).
- **Overbooking Prevention (`validate` & `create`)**: Checks remaining `available_seats`. Rejects requests exceeding capacity with exact message: `Only {available_seats} seat(s) available.`.

### 3. Concurrency & Race Condition Protection
Ticketing systems experience high concurrency when multiple users attempt to reserve the final seats simultaneously:
- **`select_for_update()` inside `transaction.atomic()`**:
  Inside `ReservationSerializer.create()`, an explicit row-level lock is acquired on the `Event` record:
  ```python
  with transaction.atomic():
      event = Event.objects.select_for_update().get(pk=validated_data['event'].pk)
      if seats_requested > event.available_seats:
          raise serializers.ValidationError(f'Only {event.available_seats} seat(s) available.')
      event.available_seats -= seats_requested
      event.save(update_fields=['available_seats'])
      ...
  ```
  If two requests arrive concurrently, the second transaction is blocked until the first completes. It then evaluates the updated seat count and safely raises a 400 error rather than overselling.

### 4. Cancellation Handling ([`events/views.py`](events/views.py))
- Custom detail action at `POST /api/reservations/{id}/cancel/`.
- Uses `select_for_update()` inside `transaction.atomic()` across both the reservation and its related event.
- If reservation ID does not exist: returns HTTP 404 (`{"error": "Reservation not found."}`).
- If reservation is already cancelled: returns HTTP 400 (`{"error": "Already cancelled."}`).
- Atomically adds back seats to `event.available_seats` and transitions reservation status to `cancelled`.

### 5. Standardized Exception Handler ([`events/exceptions.py`](events/exceptions.py))
Configured in `settings.py` via `REST_FRAMEWORK['EXCEPTION_HANDLER']`:
- **Django Core `ValidationError`**: Formats into standardized `{ "error": "Validation error", "detail": ... }`.
- **Database `IntegrityError`**: Catches constraint violations (foreign keys, duplicates) and returns HTTP 400 `{ "error": "Database integrity error", "detail": ... }`.
- **Unhandled 500 Exceptions**: Catches unexpected crashes, logs full trace with `logger.exception()`, and returns clean JSON `{ "error": "Internal server error" }` instead of leaking HTML stack traces.

---

## API Endpoints Reference

All routes are served under the `/api/` prefix.

### Events (`/api/events/`)

| Method | Endpoint | Description | Query Parameters |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/events/` | List all events (ordered by date) | `status` (exact), `venue` (case-insensitive substring) |
| `POST` | `/api/events/` | Create a new event | None |
| `GET` | `/api/events/{id}/` | Retrieve an event by ID | None |
| `PUT` | `/api/events/{id}/` | Replace event details | None |
| `PATCH` | `/api/events/{id}/` | Partially update event | None |
| `DELETE` | `/api/events/{id}/` | Delete an event | None |

### Reservations (`/api/reservations/`)

| Method | Endpoint | Description | Query Parameters |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/reservations/` | List all reservations | `event_id` (filter by event ID) |
| `POST` | `/api/reservations/` | Reserve seats for an event | None |
| `GET` | `/api/reservations/{id}/` | Retrieve reservation details | None |
| `POST` | `/api/reservations/{id}/cancel/` | Cancel reservation & restore seats | None |

---

## Design Decisions

1. **Transactional Integrity & Row-Level Locking**:
   Instead of updating seat counts in independent queries, `select_for_update()` and `transaction.atomic()` ensure absolute ACID compliance and protect against simultaneous overbooking attempts.
2. **Dynamic Computed Field (`reservations_count`)**:
   `SerializerMethodField` dynamically computes only `status='confirmed'` reservations so cancelled reservations never skew active attendee numbers.
3. **Dedicated POST Action for State Mutation**:
   Cancellation is executed via `POST /api/reservations/{id}/cancel/` rather than generic `PATCH` or `DELETE`, ensuring business side effects (seat restoration) are applied reliably and idempotently.
4. **Environment-Aware Database Switching**:
   Supports PostgreSQL via Docker or external configuration, with zero-setup SQLite fallback for local development or fast CI testing.

---

## Running Automated Tests

### 1. Django Test Runner (23 Unit & Integration Tests)
```bash
# In Docker
docker compose exec web python manage.py test

# Locally
python manage.py test
```

### 2. Standalone Verification Suite
```bash
# In Docker
docker compose exec web python test_eventhub.py

# Locally
python test_eventhub.py
```

---

## Postman Guide (Screenshots Checklist)

Import the included [`postman_collection.json`](postman_collection.json) into Postman.

### Prerequisite: Seed / Verify Initial Event
Ensure `PyCon India 2025` is present (`POST http://localhost:8000/api/events/`):
```json
{
  "title": "PyCon India 2025",
  "venue": "NIMHANS Convention Centre, Bangalore",
  "date": "2025-09-20",
  "total_seats": 500,
  "available_seats": 500,
  "status": "upcoming"
}
```

---

### Screenshot 1: Successful Reservation (201 Created)
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/reservations/`
- **Headers**: `Content-Type: application/json`
- **Body (raw JSON)**:
  ```json
  {
    "event": 1,
    "attendee_name": "Priya Sharma",
    "attendee_email": "priya@example.com",
    "seats_reserved": 2
  }
  ```
- **Response**: `201 Created` with status `"confirmed"`.

---

### Screenshot 2: Overbooking Failure (400 Bad Request)
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/reservations/`
- **Headers**: `Content-Type: application/json`
- **Body (raw JSON)**:
  ```json
  {
    "event": 1,
    "attendee_name": "Rahul Verma",
    "attendee_email": "rahul@example.com",
    "seats_reserved": 1000
  }
  ```
- **Response**: `400 Bad Request` with `{"non_field_errors": ["Only 498 seat(s) available."]}`.

---

### Screenshot 3: Successful Cancellation (200 OK)
- **Method**: `POST`
- **URL**: `http://localhost:8000/api/reservations/1/cancel/`
- **Headers**: None
- **Body**: None
- **Response**: `200 OK` with status `"cancelled"`.
- *Note: Subsequent calls return `400 Bad Request` with `{"error": "Already cancelled."}`.*
