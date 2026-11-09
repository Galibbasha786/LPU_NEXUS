# core/views.py
import logging

from django.http import JsonResponse
from pymongo.errors import PyMongoError

from .mongo import get_db, init_indexes

logger = logging.getLogger(__name__)


def health(request):
    try:
        get_db().command('ping')
        return JsonResponse({'status': 'ok', 'db': 'connected'})
    except PyMongoError:
        logger.exception('MongoDB health check failed')
        return JsonResponse({'status': 'error', 'db': 'unavailable'}, status=503)