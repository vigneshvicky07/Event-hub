import hashlib
import json
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL_EVENTS_LIST = 300   # 5 minutes default
CACHE_TTL_EVENT_DETAIL = 300  # 5 minutes default


def get_events_list_cache_key(query_params):
    """
    Generate a deterministic cache key from query parameters (status, venue, etc.).
    """
    sorted_params = sorted((k, v) for k, v in query_params.items())
    param_str = json.dumps(sorted_params)
    param_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest()
    return f"eventhub:events:list:{param_hash}"


def get_event_detail_cache_key(event_id):
    """
    Generate a cache key for individual event detail.
    """
    return f"eventhub:event:{event_id}"


def invalidate_events_cache(event_id=None):
    """
    Invalidates cached event details and all cached event listings.
    Called whenever an event is created/updated/deleted or a reservation is booked/cancelled.
    """
    try:
        if event_id:
            cache.delete(get_event_detail_cache_key(event_id))

        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern("eventhub:events:list:*")
        else:
            cache.clear()
        logger.debug(f"Invalidated events cache for event_id={event_id}")
    except Exception as exc:
        logger.warning(f"Error invalidating events cache: {exc}")
