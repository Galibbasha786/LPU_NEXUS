import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


def lab_home(request):
    progress = request.session.get('dsa_progress', [])
    return render(request, 'dsa_lab/index.html', {
        'progress': progress,
        'progress_count': len(progress),
        'topics_total': 12,
    })


@require_POST
def save_progress(request):
    """Store completed lesson IDs in the current browser session."""
    try:
        payload = json.loads(request.body or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    topic = payload.get('topic')
    if not isinstance(topic, str) or len(topic) > 40:
        return JsonResponse({'error': 'Invalid topic.'}, status=400)
    allowed = {'arrays', 'strings', 'linked-lists', 'stacks', 'queues', 'hashmaps',
               'trees', 'graphs', 'recursion', 'backtracking', 'greedy', 'dynamic-programming'}
    if topic not in allowed:
        return JsonResponse({'error': 'Unknown topic.'}, status=400)
    completed = request.session.get('dsa_progress', [])
    if topic not in completed:
        completed.append(topic)
    request.session['dsa_progress'] = completed
    return JsonResponse({'completed': completed, 'count': len(completed)})
