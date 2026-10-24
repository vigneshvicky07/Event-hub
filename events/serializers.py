import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from .models import Event, Reservation
from .cache_utils import invalidate_events_cache


class EventSerializer(serializers.ModelSerializer):
    reservations_count = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id',
            'title',
            'venue',
            'date',
            'total_seats',
            'available_seats',
            'status',
            'created_at',
            'reservations_count',
        ]

    def get_reservations_count(self, obj):
        return obj.reservations.filter(status='confirmed').count()

    def validate_title(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError('Title cannot be empty or blank.')
        return str(value).strip()

    def validate_venue(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError('Venue cannot be empty or blank.')
        return str(value).strip()

    def validate_total_seats(self, value):
        if value < 1:
            raise serializers.ValidationError('Total seats must be at least 1.')
        return value

    def validate_available_seats(self, value):
        if value < 0:
            raise serializers.ValidationError('Available seats cannot be negative.')
        return value

    def validate(self, data):
        total_seats = data.get('total_seats', self.instance.total_seats if self.instance else 0)
        available_seats = data.get('available_seats', self.instance.available_seats if self.instance else 0)

        if available_seats > total_seats:
            raise serializers.ValidationError('available_seats cannot exceed total_seats.')

        # If updating an existing event, ensure total_seats is not reduced below confirmed bookings
        if self.instance and 'total_seats' in data:
            confirmed_seats = sum(
                r.seats_reserved for r in self.instance.reservations.filter(status='confirmed')
            )
            if data['total_seats'] < confirmed_seats:
                raise serializers.ValidationError(
                    f'Cannot reduce total_seats to {data["total_seats"]}; {confirmed_seats} seat(s) are already booked.'
                )

        return data


class ReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            'id',
            'event',
            'attendee_name',
            'attendee_email',
            'seats_reserved',
            'status',
            'created_at',
        ]
        read_only_fields = ['status', 'created_at']

    def validate_attendee_name(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError('Attendee name cannot be empty or blank.')
        return str(value).strip()

    def validate_attendee_email(self, value):
        email = str(value).strip()
        if not email:
            raise serializers.ValidationError('Attendee email cannot be empty.')
        try:
            validate_email(email)
        except DjangoValidationError:
            raise serializers.ValidationError('Enter a valid email address.')
        return email.lower()

    def validate_seats_reserved(self, value):
        if value < 1:
            raise serializers.ValidationError('Must reserve at least 1 seat.')
        return value

    def validate(self, data):
        event = data.get('event')
        if not event:
            raise serializers.ValidationError({'event': 'Event is required.'})

        if event.status not in ('upcoming', 'ongoing'):
            raise serializers.ValidationError(
                f'Cannot reserve seats for a {event.status} event.'
            )

        if data.get('seats_reserved', 0) > event.available_seats:
            raise serializers.ValidationError(
                f'Only {event.available_seats} seat(s) available.'
            )

        return data

    def create(self, validated_data):
        with transaction.atomic():
            # Concurrency protection: lock event row to prevent race conditions during booking
            event = Event.objects.select_for_update().get(pk=validated_data['event'].pk)
            seats_requested = validated_data['seats_reserved']

            if event.status not in ('upcoming', 'ongoing'):
                raise serializers.ValidationError(
                    f'Cannot reserve seats for a {event.status} event.'
                )

            if seats_requested > event.available_seats:
                raise serializers.ValidationError(
                    f'Only {event.available_seats} seat(s) available.'
                )

            event.available_seats -= seats_requested
            event.save(update_fields=['available_seats'])

            validated_data['event'] = event
            reservation = Reservation.objects.create(**validated_data)

            # Invalidate Redis cache for this event and all event listings
            invalidate_events_cache(event_id=event.id)

            return reservation
