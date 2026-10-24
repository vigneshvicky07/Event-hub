import datetime
import logging
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from django.core.cache import cache
from .models import Event, Reservation


class EventHubAPITests(APITestCase):
    def setUp(self):
        cache.clear()
        self.event1 = Event.objects.create(
            title="PyCon India 2025",
            venue="NIMHANS Convention Centre, Bangalore",
            date=datetime.date(2025, 9, 20),
            total_seats=500,
            available_seats=500,
            status="upcoming",
        )
        self.event2 = Event.objects.create(
            title="DjangoCon Europe 2025",
            venue="Dublin Castle, Dublin",
            date=datetime.date(2025, 6, 15),
            total_seats=300,
            available_seats=300,
            status="ongoing",
        )
        self.event_completed = Event.objects.create(
            title="Past Meetup",
            venue="Online",
            date=datetime.date(2024, 1, 1),
            total_seats=50,
            available_seats=50,
            status="completed",
        )
        self.event_cancelled = Event.objects.create(
            title="Cancelled Expo",
            venue="San Francisco",
            date=datetime.date(2025, 8, 1),
            total_seats=100,
            available_seats=100,
            status="cancelled",
        )

    # =========================================================================
    # Event Validations & Exceptions
    # =========================================================================

    def test_create_event_success(self):
        url = reverse("event-list")
        payload = {
            "title": "Tech Summit 2025",
            "venue": "Bangalore International Exhibition Centre",
            "date": "2025-11-10",
            "total_seats": 200,
            "available_seats": 200,
            "status": "upcoming",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Tech Summit 2025")
        self.assertEqual(response.data["reservations_count"], 0)

    def test_create_event_validation_available_exceeds_total(self):
        url = reverse("event-list")
        payload = {
            "title": "Invalid Event",
            "venue": "Some Venue",
            "date": "2025-11-10",
            "total_seats": 100,
            "available_seats": 150,
            "status": "upcoming",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)
        self.assertIn("available_seats cannot exceed total_seats.", response.data["non_field_errors"])

    def test_create_event_validation_blank_title(self):
        url = reverse("event-list")
        payload = {
            "title": "   ",
            "venue": "Convention Hall",
            "date": "2025-11-10",
            "total_seats": 100,
            "available_seats": 100,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response.data)

    def test_create_event_validation_blank_venue(self):
        url = reverse("event-list")
        payload = {
            "title": "DevFest 2025",
            "venue": "   ",
            "date": "2025-11-10",
            "total_seats": 100,
            "available_seats": 100,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("venue", response.data)

    def test_create_event_validation_negative_total_seats(self):
        url = reverse("event-list")
        payload = {
            "title": "DevFest 2025",
            "venue": "Auditorium",
            "date": "2025-11-10",
            "total_seats": -10,
            "available_seats": 0,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_event_cannot_reduce_total_seats_below_booked(self):
        # Book 5 seats
        Reservation.objects.create(
            event=self.event1,
            attendee_name="Alice",
            attendee_email="alice@example.com",
            seats_reserved=5,
            status="confirmed",
        )
        self.event1.available_seats = 495
        self.event1.save()

        # Try updating total_seats to 3 (less than 5 booked)
        url = reverse("event-detail", args=[self.event1.id])
        response = self.client.patch(url, {"total_seats": 3, "available_seats": 0}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)
        self.assertTrue(any("already booked" in err for err in response.data["non_field_errors"]))

    def test_list_all_events(self):
        url = reverse("event-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)

    def test_filter_events_by_status(self):
        url = reverse("event-list")
        response = self.client.get(url, {"status": "upcoming"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "PyCon India 2025")

    def test_filter_events_by_venue(self):
        url = reverse("event-list")
        response = self.client.get(url, {"venue": "Bangalore"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["venue"], "NIMHANS Convention Centre, Bangalore")

    # =========================================================================
    # Reservation Validations & Exceptions
    # =========================================================================

    def test_create_reservation_success_and_seats_deducted(self):
        url = reverse("reservation-list")
        payload = {
            "event": self.event1.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 2,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "confirmed")
        self.assertEqual(response.data["seats_reserved"], 2)

        # Verify seats deducted in database
        self.event1.refresh_from_db()
        self.assertEqual(self.event1.available_seats, 498)

        # Check reservations_count on event
        event_res = self.client.get(reverse("event-detail", args=[self.event1.id]))
        self.assertEqual(event_res.data["reservations_count"], 1)

    def test_reservation_validation_min_seats(self):
        url = reverse("reservation-list")
        payload = {
            "event": self.event1.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 0,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("seats_reserved", response.data)
        self.assertIn("Must reserve at least 1 seat.", response.data["seats_reserved"])

    def test_reservation_validation_blank_name(self):
        url = reverse("reservation-list")
        payload = {
            "event": self.event1.id,
            "attendee_name": "   ",
            "attendee_email": "priya@example.com",
            "seats_reserved": 1,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("attendee_name", response.data)

    def test_reservation_validation_invalid_email(self):
        url = reverse("reservation-list")
        payload = {
            "event": self.event1.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "not-an-email",
            "seats_reserved": 1,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("attendee_email", response.data)

    def test_reservation_validation_completed_event(self):
        url = reverse("reservation-list")
        payload = {
            "event": self.event_completed.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 1,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)
        self.assertIn("Cannot reserve seats for a completed event.", response.data["non_field_errors"])

    def test_reservation_validation_cancelled_event(self):
        url = reverse("reservation-list")
        payload = {
            "event": self.event_cancelled.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 1,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)
        self.assertIn("Cannot reserve seats for a cancelled event.", response.data["non_field_errors"])

    def test_reservation_validation_nonexistent_event(self):
        url = reverse("reservation-list")
        payload = {
            "event": 99999,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 1,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event", response.data)

    def test_overbooking_attempt_returns_400(self):
        self.event1.available_seats = 1
        self.event1.save()

        url = reverse("reservation-list")
        payload = {
            "event": self.event1.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 2,
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"non_field_errors": ["Only 1 seat(s) available."]})

        # Ensure available seats unchanged
        self.event1.refresh_from_db()
        self.assertEqual(self.event1.available_seats, 1)

    # =========================================================================
    # Cancellation Validations & Exceptions
    # =========================================================================

    def test_cancel_reservation_restores_seats(self):
        res_url = reverse("reservation-list")
        payload = {
            "event": self.event1.id,
            "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com",
            "seats_reserved": 5,
        }
        create_res = self.client.post(res_url, payload, format="json")
        reservation_id = create_res.data["id"]
        self.event1.refresh_from_db()
        self.assertEqual(self.event1.available_seats, 495)

        # Cancel reservation
        cancel_url = reverse("reservation-cancel", args=[reservation_id])
        cancel_res = self.client.post(cancel_url)
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_res.data["status"], "cancelled")

        # Verify seats restored
        self.event1.refresh_from_db()
        self.assertEqual(self.event1.available_seats, 500)

        # Verify reservations_count decreased
        event_res = self.client.get(reverse("event-detail", args=[self.event1.id]))
        self.assertEqual(event_res.data["reservations_count"], 0)

    def test_cancel_already_cancelled_reservation_returns_400(self):
        reservation = Reservation.objects.create(
            event=self.event1,
            attendee_name="John Doe",
            attendee_email="john@example.com",
            seats_reserved=2,
            status="cancelled",
        )
        cancel_url = reverse("reservation-cancel", args=[reservation.id])
        response = self.client.post(cancel_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"error": "Already cancelled."})

    def test_cancel_nonexistent_reservation_returns_404(self):
        cancel_url = reverse("reservation-cancel", args=[99999])
        response = self.client.post(cancel_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data, {"error": "Reservation not found."})

    # =========================================================================
    # Filtering & Middleware Logging
    # =========================================================================

    def test_filter_reservations_by_event_id(self):
        res1 = Reservation.objects.create(
            event=self.event1,
            attendee_name="User 1",
            attendee_email="u1@example.com",
            seats_reserved=1,
            status="confirmed",
        )
        res2 = Reservation.objects.create(
            event=self.event2,
            attendee_name="User 2",
            attendee_email="u2@example.com",
            seats_reserved=2,
            status="confirmed",
        )

        url = reverse("reservation-list")
        response = self.client.get(url, {"event_id": self.event1.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], res1.id)

    def test_filter_reservations_invalid_event_id_param(self):
        url = reverse("reservation-list")
        response = self.client.get(url, {"event_id": "invalid_abc"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_middleware_logging(self):
        with self.assertLogs("events.middleware", level="INFO") as cm:
            self.client.get(reverse("event-list"))
        self.assertTrue(any("GET /api/events/ - 200 -" in log_msg for log_msg in cm.output))

    # =========================================================================
    # Redis / Memory Caching & Invalidation Tests
    # =========================================================================

    def test_event_caching_and_invalidation_on_reservation(self):
        event_url = reverse("event-detail", args=[self.event1.id])

        # Initial fetch -> populates cache
        res1 = self.client.get(event_url)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["available_seats"], 500)

        # Create reservation -> invalidates cache
        payload = {
            "event": self.event1.id,
            "attendee_name": "Cache Tester",
            "attendee_email": "cache@example.com",
            "seats_reserved": 10,
        }
        res2 = self.client.post(reverse("reservation-list"), payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

        # Subsequent fetch -> returns freshly invalidated data with 490 available seats
        res3 = self.client.get(event_url)
        self.assertEqual(res3.status_code, status.HTTP_200_OK)
        self.assertEqual(res3.data["available_seats"], 490)
        self.assertEqual(res3.data["reservations_count"], 1)

    def test_event_caching_and_invalidation_on_cancellation(self):
        # Create reservation
        payload = {
            "event": self.event1.id,
            "attendee_name": "Cancel Tester",
            "attendee_email": "canceltester@example.com",
            "seats_reserved": 4,
        }
        create_res = self.client.post(reverse("reservation-list"), payload, format="json")
        reservation_id = create_res.data["id"]

        event_url = reverse("event-detail", args=[self.event1.id])
        res_before = self.client.get(event_url)
        self.assertEqual(res_before.data["available_seats"], 496)

        # Cancel reservation -> invalidates cache
        cancel_url = reverse("reservation-cancel", args=[reservation_id])
        cancel_res = self.client.post(cancel_url)
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)

        # Subsequent fetch -> returns freshly restored 500 seats
        res_after = self.client.get(event_url)
        self.assertEqual(res_after.data["available_seats"], 500)
        self.assertEqual(res_after.data["reservations_count"], 0)
