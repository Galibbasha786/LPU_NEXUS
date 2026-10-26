from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.session import get_current_user, login_required_mongo, role_required
from core.mongo import problems

from .services import (
    GeminiServiceError,
    MAX_QUESTION_LENGTH,
    MAX_TRIAGE_LENGTH,
    answer_campus_question,
    contains_emergency_signal,
    triage_problem as create_triage_suggestion,
)
from problems.constants import PROBLEM_CATEGORIES, PROBLEM_PRIORITIES


@login_required_mongo
def assistant_page(request):
    return render(request, "campus_ai/assistant.html", {
        "user": get_current_user(request),
        "ai_configured": bool(settings.GEMINI_API_KEY),
    })


@login_required_mongo
@require_POST
def ask_campus_question(request):
    question = (request.POST.get("question") or "").strip()
    if request.POST.get("consent") != "on":
        return JsonResponse({
            "error": "Confirm that the question may be sent to Google Gemini after identifier redaction.",
        }, status=400)
    if not question:
        return JsonResponse({"error": "Enter a question before submitting."}, status=400)
    if len(question) > MAX_QUESTION_LENGTH:
        return JsonResponse({
            "error": f"Questions can be up to {MAX_QUESTION_LENGTH:,} characters.",
        }, status=400)
    try:
        answer = answer_campus_question(question)
    except GeminiServiceError as error:
        return JsonResponse({"error": str(error)}, status=503)
    return JsonResponse({"answer": answer})


@login_required_mongo
@role_required("student")
@require_POST
def triage_problem(request):
    if request.POST.get("consent") != "on":
        return JsonResponse({
            "error": "Confirm that the report text may be sent to Google Gemini after identifier redaction.",
        }, status=400)
    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    category = request.POST.get("category", "")
    if not title or not description or len(title) > 140 or len(description) > MAX_TRIAGE_LENGTH:
        return JsonResponse({
            "error": "Enter a title and description (up to 1,600 characters) before requesting suggestions.",
        }, status=400)
    if contains_emergency_signal(f"{title}\n{description}"):
        return JsonResponse({
            "error": "AI triage does not handle emergencies. Use Report Emergency or contact official campus emergency services.",
        }, status=400)
    if category not in dict(PROBLEM_CATEGORIES):
        return JsonResponse({"error": "Choose a valid problem category first."}, status=400)
    try:
        suggestion = create_triage_suggestion(title, description, category)
    except GeminiServiceError as error:
        return JsonResponse({"error": str(error)}, status=503)
    similar_open_reports = problems().count_documents({
        "category": suggestion["category"],
        "status": {"$in": ["submitted", "acknowledged", "in_progress", "waiting"]},
    })
    suggestion["similar_open_reports"] = similar_open_reports
    return JsonResponse({"suggestion": suggestion})
