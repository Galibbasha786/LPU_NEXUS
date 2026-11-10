import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from pymongo.errors import PyMongoError

from core.utils import serialize_list
from accounts.session import get_current_user, login_required_mongo, role_required

from .services import ALLOWED_CATEGORIES, latest_bulletins, publish_bulletin

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
        if not title or not body or len(title) > 160 or len(body) > 1200:
            messages.error(request, 'Enter a headline and story within the length limits.')
        elif category not in ALLOWED_CATEGORIES:
            messages.error(request, 'Choose a valid bulletin category.')
        else:
            try:
                publish_bulletin(title, body, category, user)
            except PyMongoError:
                logger.exception('Could not publish campus bulletin')
                messages.error(request, 'The campus update could not be published. Please try again.')
            else:
                messages.success(request, 'Campus update published to the headline ticker.')
                return redirect('campus_bulletins:page')
    try:
        bulletins = serialize_list(latest_bulletins())
    except PyMongoError:
        logger.exception('Could not load campus bulletins')
        bulletins = []
        messages.error(request, 'Campus updates could not be loaded.')
    return render(request, 'campus_bulletins/page.html', {
        'user': user,
        'bulletins': bulletins,
        'categories': sorted(ALLOWED_CATEGORIES),
    })


def bulletin_ticker(request):
    try:
        bulletins = serialize_list(latest_bulletins(limit=30))
    except PyMongoError:
        logger.exception('Could not load headline ticker bulletins')
        bulletins = []
    return {'campus_bulletins': bulletins}
