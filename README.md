# EventHub - Event Ticketing Platform API

EventHub is a backend REST API for a simplified event ticketing platform built with **Django** and **Django REST Framework (DRF)**.

Users can:
- Browse and filter events
- Reserve seats with automatic availability deduction and validation
- Cancel reservations with automatic seat restoration
- View request duration and status logs generated in real time by custom middleware

---

## Table of Contents
1. [Tech Stack](#tech-stack)
2. [Project Structure](#project-structure)
3. [Setup and How to Run the Project](#setup-and-how-to-run-the-project)
4. [API Endpoints](#api-endpoints)
5. [Design Decisions](#design-decisions)
6. [Testing Checklist & Automated Tests](#testing-checklist--automated-tests)
7. [Postman Guide (Screenshots Checklist)](#postman-guide-screenshots-checklist)

---

## Tech Stack
- **Python** (3.13+)
- **Django** (6.1+)
- **Django REST Framework** (3.18+)
- **SQLite3** (Default database)

---

## Project Structure

```text
Event-hub/
├── manage.py
├── requirements.txt
├── postman_collection.json
├── db.sqlite3
├── README.md
├── eventhub/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── events/
    ├── __init__.py
    ├── admin.py
    ├── apps.py
    ├── middleware.py
    ├── models.py
    ├── serializers.py
    ├── tests.py
    ├── urls.py
    ├── views.py
    └── migrations/
        ├── __init__.py
        └── 0001_initial.py
```

---

## Setup and How to Run the Project

### 1. Clone the Repository
```bash
git clone <your-repository-url>
cd Event-hub
```

### 2. Set Up Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Start the Development Server
```bash
python manage.py runserver
```
The server will start at `http://127.0.0.1:8000/`.

---

## API Endpoints

All API routes are served under the `/api/` prefix.

### Event Endpoints (`/api/events/`)

| Method | Endpoint | Description | Query Parameters |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/events/` | List all events (ordered by date) | `status` (exact), `venue` (case-insensitive substring) |
| `POST` | `/api/events/` | Create a new event | None |
| `GET` | `/api/events/{id}/` | Retrieve an event by ID | None |
| `PUT` | `/api/events/{id}/` | Update all fields of an event | None |
| `PATCH` | `/api/events/{id}/` | Partially update an event | None |
| `DELETE` | `/api/events/{id}/` | Delete an event | None |

#### Event Filtering Examples:
- Filter by status: `GET /api/events/?status=upcoming`
- Filter by venue: `GET /api/events/?venue=Bangalore`
- Combined filter: `GET /api/events/?status=upcoming&venue=NIMHANS`

#### Event Fields:
- `id` (integer, read-only)
- `title` (string, max 200 chars)
- `venue` (string, max 200 chars)
- `date` (date string `YYYY-MM-DD`)
- `total_seats` (positive integer)
- `available_seats` (positive integer, cannot exceed `total_seats`)
- `status` (`upcoming`, `ongoing`, `completed`, `cancelled`)
- `created_at` (datetime ISO 8601, read-only)
- `reservations_count` (computed integer: count of confirmed reservations)

---

### Reservation Endpoints (`/api/reservations/`)

| Method | Endpoint | Description | Query Parameters |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/reservations/` | List reservations (ordered by newest first) | `event_id` (filter by specific event ID) |
| `POST` | `/api/reservations/` | Reserve seats for an event | None |
| `GET` | `/api/reservations/{id}/` | Retrieve a reservation by ID | None |
| `POST` | `/api/reservations/{id}/cancel/` | Custom detail action: cancels reservation and restores seats | None |

#### Reservation Filtering Example:
- Filter by event: `GET /api/reservations/?event_id=1`

#### Reservation Fields:
- `id` (integer, read-only)
- `event` (integer, foreign key ID referencing Event)
- `attendee_name` (string, max 200 chars)
- `attendee_email` (email string)
- `seats_reserved` (positive integer, minimum 1)
- `status` (`confirmed`, `cancelled`, read-only)
- `created_at` (datetime ISO 8601, read-only)

---

## Design Decisions

### 1. Atomic Seat Deduction Inside Serializer `create()`
When a user books a reservation, `available_seats` must be reduced from the associated `Event`. Instead of performing this update separately across distinct view layers or controllers:
- We deduct `seats_reserved` from `event.available_seats` and save the event record directly inside `ReservationSerializer.create()`.
- **Why**: This couples the validation and database updates into a single logical execution path. If validation fails in `validate()`, no seats are modified. In high-concurrency production deployments, wrapping this inside `transaction.atomic()` or using `select_for_update()` ensures strict ACID transactional isolation and prevents race conditions.

### 2. Custom Action `@action(detail=True, methods=['post'])` for Cancellation
- Instead of using a standard `DELETE` or generic `PATCH` request to cancel a reservation, we implemented a dedicated `@action(detail=True, methods=['post'])` endpoint at `/api/reservations/{id}/cancel/`.
- **Why**: Cancellation is a state transition that triggers domain side effects (restoring the reserved seats back to `event.available_seats`). Idempotency and error handling are strictly enforced: if a user attempts to cancel a reservation that is already cancelled, the API immediately returns `400 Bad Request` (`{"error": "Already cancelled."}`) without double-restoring seats.

### 3. Computed `reservations_count` with `SerializerMethodField`
- The `EventSerializer` calculates `reservations_count` by filtering related reservations where `status='confirmed'`.
- **Why**: Only active, confirmed reservations count toward event attendance. Cancelled reservations are cleanly excluded from the count.

### 4. Custom Middleware for Real-Time Request Logging
- Located in `events/middleware.py`, `RequestLoggingMiddleware` records the HTTP method, request path, response status code, and latency in seconds (`logger.info(f"{request.method} {request.path} - {response.status_code} - {duration:.2f}s")`).
- **Why**: Provides transparent observability into API response times and request routing without external dependencies.

---

## Testing Checklist & Automated Tests

A comprehensive test suite of 13 tests is implemented in `events/tests.py` verifying all requirements:
1. Event creation with initial seats
2. Event validation preventing `available_seats` > `total_seats`
3. Event listing
4. Event filtering by `status`
5. Event filtering by `venue` (case-insensitive substring)
6. Reservation creation with automatic deduction of `available_seats`
7. Validation requiring at least 1 seat (`seats_reserved >= 1`)
8. Validation preventing reservation on `completed` or `cancelled` events
9. Overbooking prevention returning HTTP 400 (`{"non_field_errors": ["Only X seat(s) available."]}`)
10. Reservation cancellation restoring seats back to the event
11. Preventing double cancellation returning HTTP 400 (`{"error": "Already cancelled."}`)
12. Reservation filtering by `event_id`
13. Middleware logging verification for every incoming request

### Running the Test Suite
```bash
python manage.py test
```
Sample test run output:
```text
Found 13 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
POST /api/reservations/1/cancel/ - 400 - 0.00s
.POST /api/reservations/ - 201 - 0.01s
POST /api/reservations/1/cancel/ - 200 - 0.00s
GET /api/events/1/ - 200 - 0.00s
.POST /api/events/ - 201 - 0.00s
.POST /api/events/ - 400 - 0.00s
.POST /api/reservations/ - 201 - 0.00s
GET /api/events/1/ - 200 - 0.00s
.GET /api/events/ - 200 - 0.00s
.GET /api/events/ - 200 - 0.00s
.GET /api/reservations/ - 200 - 0.00s
.GET /api/events/ - 200 - 0.00s
..POST /api/reservations/ - 400 - 0.00s
.POST /api/reservations/ - 400 - 0.00s
.POST /api/reservations/ - 400 - 0.00s
.
----------------------------------------------------------------------
Ran 13 tests in 0.035s

OK
Destroying test database for alias 'default'...
```

---

## Postman Guide (Screenshots Checklist)

You can import the included [`postman_collection.json`](./postman_collection.json) file directly into Postman.

### Prerequisites: Start Server & Create Initial Event
1. Start server:
   ```bash
   python manage.py runserver
   ```
2. Create Event (POST `http://127.0.0.1:8000/api/events/`):
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
- **URL**: `http://127.0.0.1:8000/api/reservations/`
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
- **Expected Status**: `201 Created`
- **Expected Response**:
  ```json
  {
    "id": 1,
    "event": 1,
    "attendee_name": "Priya Sharma",
    "attendee_email": "priya@example.com",
    "seats_reserved": 2,
    "status": "confirmed",
    "created_at": "2026-10-20T03:37:15.188298Z"
  }
  ```

---

### Screenshot 2: Overbooking Failure (400 Bad Request)
- **Method**: `POST`
- **URL**: `http://127.0.0.1:8000/api/reservations/`
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
- **Expected Status**: `400 Bad Request`
- **Expected Response**:
  ```json
  {
    "non_field_errors": [
      "Only 498 seat(s) available."
    ]
  }
  ```

---

### Screenshot 3: Successful Cancellation (200 OK)
- **Method**: `POST`
- **URL**: `http://127.0.0.1:8000/api/reservations/1/cancel/`
- **Headers**: (None required)
- **Body**: (None required)
- **Expected Status**: `200 OK`
- **Expected Response**:
  ```json
  {
    "id": 1,
    "event": 1,
    "attendee_name": "Priya Sharma",
    "attendee_email": "priya@example.com",
    "seats_reserved": 2,
    "status": "cancelled",
    "created_at": "2026-10-20T03:37:15.188298Z"
  }
  ```
- *Note: If called again, returns `400 Bad Request` with `{"error": "Already cancelled."}`.*
