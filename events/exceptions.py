import logging
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler to ensure all validation, database, and unexpected
    exceptions are returned in a clean, consistent JSON response format.
    """
    # Call REST framework's default exception handler first to get the standard error response
    response = exception_handler(exc, context)

    if response is not None:
        return response

    # Handle Django's core model/field validation errors if raised directly
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, 'message_dict') else exc.messages
        return Response(
            {
                'error': 'Validation error',
                'detail': detail,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Handle database integrity errors (unique constraints, foreign key violations)
    if isinstance(exc, IntegrityError):
        logger.error(f"Database IntegrityError: {exc}", exc_info=True)
        return Response(
            {
                'error': 'Database integrity error',
                'detail': str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Catch-all for unhandled exceptions to prevent raw 500 HTML traces
    view_name = context.get('view').__class__.__name__ if context and context.get('view') else 'UnknownView'
    logger.exception(f"Unhandled exception in {view_name}: {exc}")
    return Response(
        {
            'error': 'Internal server error',
            'detail': str(exc),
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
