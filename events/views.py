from django.core.cache import cache
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .cache_utils import (
    CACHE_TTL_EVENT_DETAIL,
    CACHE_TTL_EVENTS_LIST,
    get_event_detail_cache_key,
    get_events_list_cache_key,
    invalidate_events_cache,
)
from .models import Event, Reservation
from .serializers import EventSerializer, ReservationSerializer


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        queryset = Event.objects.all()
        status_param = self.request.query_params.get('status')
        venue_param = self.request.query_params.get('venue')

        if status_param:
            queryset = queryset.filter(status=status_param.strip().lower())
        if venue_param:
            queryset = queryset.filter(venue__icontains=venue_param.strip())

        return queryset

    def list(self, request, *args, **kwargs):
        cache_key = get_events_list_cache_key(request.query_params)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL_EVENTS_LIST)
        return response

    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        cache_key = get_event_detail_cache_key(pk)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        response = super().retrieve(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL_EVENT_DETAIL)
        return response

    def perform_create(self, serializer):
        instance = serializer.save()
        invalidate_events_cache(event_id=instance.id)

    def perform_update(self, serializer):
        instance = serializer.save()
        invalidate_events_cache(event_id=instance.id)

    def perform_destroy(self, instance):
        event_id = instance.id
        instance.delete()
        invalidate_events_cache(event_id=event_id)


class ReservationViewSet(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer

    def get_queryset(self):
        queryset = Reservation.objects.all()
        event_id_param = self.request.query_params.get('event_id')

        if event_id_param is not None:
            try:
                event_id = int(event_id_param)
                queryset = queryset.filter(event_id=event_id)
            except (ValueError, TypeError):
                # Return an empty queryset if an invalid event_id format is passed
                return Reservation.objects.none()

        return queryset

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            try:
                reservation = (
                    Reservation.objects.select_for_update()
                    .select_related('event')
                    .get(pk=pk)
                )
            except Reservation.DoesNotExist:
                return Response(
                    {'error': 'Reservation not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if reservation.status == 'cancelled':
                return Response(
                    {'error': 'Already cancelled.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            event = Event.objects.select_for_update().get(pk=reservation.event_id)
            event.available_seats += reservation.seats_reserved
            if event.available_seats > event.total_seats:
                event.available_seats = event.total_seats
            event.save(update_fields=['available_seats'])

            reservation.status = 'cancelled'
            reservation.save(update_fields=['status'])

            # Invalidate Redis cache for this event and all event listings
            invalidate_events_cache(event_id=event.id)

            return Response(self.get_serializer(reservation).data, status=status.HTTP_200_OK)
