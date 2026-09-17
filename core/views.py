# core/views.py
from django.http import JsonResponse
from .mongo import get_db, init_indexes


def health(request):
    try:
        get_db().command('ping')
        return JsonResponse({'status': 'ok', 'db': 'connected'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=500)


def bootstrap_indexes(request):
    """Hit once after DB is up. Remove or protect in production."""
    init_indexes()
    return JsonResponse({'status': 'indexes_created'})