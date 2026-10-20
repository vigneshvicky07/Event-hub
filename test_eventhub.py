import json
import os
import sys
import django
from django.test import Client

# Configure Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'eventhub.settings')
django.setup()

from events.models import Event, Reservation

TEST_STATE = {}


def test_event_validations_and_api():
    print("\n--- 1. Testing Event Creation, Validations & Filtering ---")
    client = Client()

    # Clear previous test data
    Reservation.objects.all().delete()
    Event.objects.all().delete()

    # 1. Valid Event Creation
    resp = client.post(
        '/api/events/',
        data=json.dumps({
            "title": "PyCon India 2025",
            "venue": "NIMHANS Convention Centre, Bangalore",
            "date": "2025-09-20",
            "total_seats": 500,
            "available_seats": 500,
            "status": "upcoming"
        }),
        content_type='application/json'
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.content}"
    event1 = resp.json()
    assert event1["title"] == "PyCon India 2025"
    assert event1["reservations_count"] == 0
    TEST_STATE["event1_id"] = event1["id"]
    print(f"✓ POST /api/events/ (201 Created, ID={event1['id']}) passed")

    # 2. Validation: Available seats exceeds total seats
    resp = client.post(
        '/api/events/',
        data=json.dumps({
            "title": "Invalid Event",
            "venue": "Some Venue",
            "date": "2025-10-10",
            "total_seats": 100,
            "available_seats": 200,
            "status": "upcoming"
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert "available_seats cannot exceed total_seats." in str(resp.json())
    print("✓ Validation check: available_seats > total_seats rejected (400) passed")

    # 3. Validation: Blank title
    resp = client.post(
        '/api/events/',
        data=json.dumps({
            "title": "   ",
            "venue": "Some Venue",
            "date": "2025-10-10",
            "total_seats": 100,
            "available_seats": 100,
            "status": "upcoming"
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert "title" in resp.json()
    print("✓ Validation check: blank title rejected (400) passed")

    # 4. Validation: Negative total seats
    resp = client.post(
        '/api/events/',
        data=json.dumps({
            "title": "Valid Title",
            "venue": "Some Venue",
            "date": "2025-10-10",
            "total_seats": -5,
            "available_seats": 0,
            "status": "upcoming"
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print("✓ Validation check: negative total_seats rejected (400) passed")

    # Create ongoing and completed events for filtering & status checks
    resp_ongoing = client.post(
        '/api/events/',
        data=json.dumps({
            "title": "DjangoCon Europe 2025",
            "venue": "Dublin Castle, Dublin",
            "date": "2025-06-15",
            "total_seats": 300,
            "available_seats": 300,
            "status": "ongoing"
        }),
        content_type='application/json'
    )
    TEST_STATE["event2_id"] = resp_ongoing.json()["id"]

    resp_completed = client.post(
        '/api/events/',
        data=json.dumps({
            "title": "Past Meetup",
            "venue": "Online",
            "date": "2024-01-01",
            "total_seats": 50,
            "available_seats": 50,
            "status": "completed"
        }),
        content_type='application/json'
    )
    TEST_STATE["event_completed_id"] = resp_completed.json()["id"]

    # 5. Filter events by status
    resp = client.get('/api/events/?status=upcoming')
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["title"] == "PyCon India 2025"
    print("✓ GET /api/events/?status=upcoming passed")

    # 6. Filter events by venue
    resp = client.get('/api/events/?venue=Bangalore')
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert "Bangalore" in resp.json()[0]["venue"]
    print("✓ GET /api/events/?venue=Bangalore passed")


def test_reservation_validations_and_api():
    print("\n--- 2. Testing Reservation Creation, Validations & Overbooking ---")
    client = Client()
    event1_id = TEST_STATE["event1_id"]
    event_completed_id = TEST_STATE["event_completed_id"]

    # 1. Successful Reservation (201 Created)
    resp = client.post(
        '/api/reservations/',
        data=json.dumps({
            "event": event1_id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 2
        }),
        content_type='application/json'
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.content}"
    res_data = resp.json()
    assert res_data["status"] == "confirmed"
    assert res_data["seats_reserved"] == 2
    TEST_STATE["reservation1_id"] = res_data["id"]

    # Verify event seats deducted
    event_resp = client.get(f'/api/events/{event1_id}/')
    assert event_resp.json()["available_seats"] == 498
    assert event_resp.json()["reservations_count"] == 1
    print("✓ POST /api/reservations/ (201 Created & seats deducted) passed")

    # 2. Validation: Reserve 0 seats (minimum 1 required)
    resp = client.post(
        '/api/reservations/',
        data=json.dumps({
            "event": event1_id,
            "attendee_name": "Test User",
            "attendee_email": "test@example.com",
            "seats_reserved": 0
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400
    assert "Must reserve at least 1 seat." in str(resp.json())
    print("✓ Validation check: 0 seats rejected (400) passed")

    # 3. Validation: Invalid email format
    resp = client.post(
        '/api/reservations/',
        data=json.dumps({
            "event": event1_id,
            "attendee_name": "Test User",
            "attendee_email": "invalid_email_format",
            "seats_reserved": 1
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400
    assert "attendee_email" in resp.json()
    print("✓ Validation check: invalid email rejected (400) passed")

    # 4. Validation: Cannot reserve completed event
    resp = client.post(
        '/api/reservations/',
        data=json.dumps({
            "event": event_completed_id,
            "attendee_name": "Test User",
            "attendee_email": "test@example.com",
            "seats_reserved": 1
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400
    assert "Cannot reserve seats for a completed event." in str(resp.json())
    print("✓ Validation check: completed event rejected (400) passed")

    # 5. Overbooking Attempt (400 Bad Request)
    resp = client.post(
        '/api/reservations/',
        data=json.dumps({
            "event": event1_id,
            "attendee_name": "Rahul Verma",
            "attendee_email": "rahul@example.com",
            "seats_reserved": 1000
        }),
        content_type='application/json'
    )
    assert resp.status_code == 400
    assert resp.json() == {"non_field_errors": ["Only 498 seat(s) available."]}
    print("✓ Overbooking attempt rejected (400 with exact message) passed")


def test_cancellation_and_filters():
    print("\n--- 3. Testing Cancellation & Filtering ---")
    client = Client()
    event1_id = TEST_STATE["event1_id"]
    res1_id = TEST_STATE["reservation1_id"]

    # 1. Successful Cancellation (200 OK)
    resp = client.post(f'/api/reservations/{res1_id}/cancel/')
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.content}"
    assert resp.json()["status"] == "cancelled"

    # Verify event seats restored
    event_resp = client.get(f'/api/events/{event1_id}/')
    assert event_resp.json()["available_seats"] == 500
    assert event_resp.json()["reservations_count"] == 0
    print(f"✓ POST /api/reservations/{res1_id}/cancel/ (200 OK & seats restored) passed")

    # 2. Re-cancelling already cancelled reservation (400 Bad Request)
    resp = client.post(f'/api/reservations/{res1_id}/cancel/')
    assert resp.status_code == 400
    assert resp.json() == {"error": "Already cancelled."}
    print("✓ Already cancelled reservation rejected (400) passed")

    # 3. Cancelling non-existent reservation (404 Not Found)
    resp = client.post('/api/reservations/9999/cancel/')
    assert resp.status_code == 404
    assert resp.json() == {"error": "Reservation not found."}
    print("✓ Non-existent reservation cancellation rejected (404) passed")

    # 4. Filter reservations by event_id
    resp = client.get(f'/api/reservations/?event_id={event1_id}')
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    print(f"✓ GET /api/reservations/?event_id={event1_id} passed")

    # 5. Filter reservations by invalid non-integer event_id (graceful empty result)
    resp = client.get('/api/reservations/?event_id=abc')
    assert resp.status_code == 200
    assert len(resp.json()) == 0
    print("✓ GET /api/reservations/?event_id=abc (handled gracefully) passed")


if __name__ == '__main__':
    print("==================================================")
    print("🚀 Running EventHub Comprehensive Test Suite")
    print("==================================================")
    try:
        test_event_validations_and_api()
        test_reservation_validations_and_api()
        test_cancellation_and_filters()
        print("\n==================================================")
        print("🎉 ALL TESTS PASSED SUCCESSFULLY! (100% Verified)")
        print("==================================================")
    except AssertionError as err:
        print(f"\n❌ Test Failed: {err}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n💥 Unexpected Error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
