import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from pymongo.errors import PyMongoError

from core.utils import serialize_list
from accounts.session import get_current_user, login_required_mongo, role_required

from .services import ALLOWED_CATEGORIES, latest_bulletins, publish_bulletin, recent_bulletins

logger = logging.getLogger(__name__)


@login_required_mongo
@role_required('staff', 'admin')
@require_http_methods(['GET', 'POST'])
def bulletin_page(request):
    user = get_current_user(request)
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        body = (request.POST.get('body') or '').strip()
        category = request.POST.get('category', 'news')
        starts_raw = (request.POST.get('starts_at') or '').strip()
        expires_raw = (request.POST.get('expires_at') or '').strip()
        if not title or not body or len(title) > 160 or len(body) > 1200:
            messages.error(request, 'Enter a headline and story within the length limits.')
        elif category not in ALLOWED_CATEGORIES:
            messages.error(request, 'Choose a valid bulletin category.')
        else:
            try:
                if not starts_raw or not expires_raw:
                    raise ValueError('Set both the start and end time.')
                ist = ZoneInfo('Asia/Kolkata')
                starts_at = datetime.fromisoformat(starts_raw).replace(tzinfo=ist).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                expires_at = datetime.fromisoformat(expires_raw).replace(tzinfo=ist).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                if starts_at <= datetime.utcnow():
                    raise ValueError('Choose a start time in the future.')
                if starts_at >= expires_at:
                    raise ValueError('The end time must be after the start time.')
                publish_bulletin(title, body, category, user, starts_at, expires_at)
            except (TypeError, ValueError) as error:
                messages.error(request, str(error) or 'Enter valid start and end times.')
            except PyMongoError:
                logger.exception('Could not publish campus bulletin')
                messages.error(request, 'The campus update could not be published. Please try again.')
            else:
                messages.success(request, 'Campus update published to the headline ticker.')
                return redirect('campus_bulletins:page')
    try:
        bulletins = serialize_list(recent_bulletins())
    except PyMongoError:
        logger.exception('Could not load campus bulletins')
        bulletins = []
        messages.error(request, 'Campus updates could not be loaded.')
    return render(request, 'campus_bulletins/page.html', {
        'user': user,
        'bulletins': bulletins,
        'categories': sorted(ALLOWED_CATEGORIES),
        'now_local': datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%dT%H:%M'),
        'now_utc': datetime.utcnow().isoformat(),
    })


def bulletin_ticker(request):
    try:
        bulletins = serialize_list(latest_bulletins(limit=30))
    except PyMongoError:
        logger.exception('Could not load headline ticker bulletins')
        bulletins = []
    return {'campus_bulletins': bulletins}


@login_required_mongo
@require_http_methods(['GET'])
def bulletin_ticker_json(request):
    try:
        bulletins = serialize_list(latest_bulletins(limit=30))
    except PyMongoError:
        logger.exception('Could not refresh campus headline ticker')
        return JsonResponse({'bulletins': []}, status=503)
    return JsonResponse({'bulletins': bulletins})
