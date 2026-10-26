from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.session import get_current_user, login_required_mongo, role_required
from core.mongo import student_profiles
from core.utils import serialize_doc, serialize_list, to_object_id

from . import services

IDEA_CATEGORIES = [
    ("campus", "Campus life"),
    ("facilities", "Facilities"),
    ("technology", "Technology"),
    ("sustainability", "Sustainability"),
    ("learning", "Learning"),
    ("other", "Other"),
]


@login_required_mongo
@role_required("student")
@require_http_methods(["GET", "POST"])
def idea_list(request):
    user = get_current_user(request)
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()
        category = request.POST.get("category", "")
        if (not title or not description or category not in dict(IDEA_CATEGORIES)
                or len(title) > 140 or len(description) > 5000):
            messages.error(request, "Enter a valid title, category, and description.")
        else:
            services.create_idea(user, title, description, category)
            messages.success(
                request,
                "Your idea is live. Students can vote and comment for seven days.",
            )
            return redirect("ideas:list")
    idea_list = serialize_list(services.list_ideas())
    for idea in idea_list:
        idea["vote_totals"] = services.vote_totals(idea["id"])
    return render(request, "ideas/list.html", {
        "user": user,
        "ideas": idea_list,
        "categories": IDEA_CATEGORIES,
    })


@login_required_mongo
def idea_detail(request, idea_id):
    user = get_current_user(request)
    idea = services.get_idea(idea_id)
    if not idea:
        messages.error(request, "Idea not found.")
        return redirect("accounts:dashboard")
    totals = services.vote_totals(idea_id)
    profile = student_profiles().find_one({"user_id": to_object_id(idea["author_id"])})
    return render(request, "ideas/detail.html", {
        "user": user,
        "idea": serialize_doc(idea),
        "vote_totals": totals,
        "support_percent": round(totals["support"] * 100 / totals["total"]) if totals["total"] else 0,
        "user_vote": services.get_user_vote(idea_id, user["id"]),
        "is_author": str(idea["author_id"]) == user["id"],
        "is_student": user["role"] == "student",
        "can_review": user["role"] == "admin",
        "author_registration_number": profile.get("registration_number", "") if profile else "",
    })


@login_required_mongo
@role_required("student")
@require_http_methods(["POST"])
def cast_vote(request, idea_id):
    support = request.POST.get("vote")
    if support not in ("support", "against"):
        messages.error(request, "Choose support or against to vote.")
    else:
        success, error = services.add_vote(
            idea_id, request.session.get("lpu_user_id"), support == "support",
        )
        if error:
            messages.error(request, error)
        elif success:
            messages.success(request, "Your vote has been recorded.")
    return redirect("ideas:detail", idea_id=idea_id)


@login_required_mongo
@role_required("student")
@require_http_methods(["POST"])
def add_comment(request, idea_id):
    user = get_current_user(request)
    body = (request.POST.get("body") or "").strip()
    if not body or len(body) > 2000:
        messages.error(request, "Enter a comment of up to 2,000 characters.")
    elif not services.add_comment(idea_id, user, body):
        messages.error(request, "Comments are closed for this poll.")
    else:
        messages.success(request, "Your comment has been added.")
    return redirect("ideas:detail", idea_id=idea_id)


@login_required_mongo
@role_required("admin")
def review_queue(request):
    idea_list = serialize_list([
        idea for idea in services.list_ideas()
        if idea.get("status") == "pending_review"
    ])
    for idea in idea_list:
        idea["vote_totals"] = services.vote_totals(idea["id"])
        profile = student_profiles().find_one({"user_id": to_object_id(idea["author_id"])})
        idea["author_registration_number"] = (
            profile.get("registration_number", "") if profile else ""
        )
    return render(request, "ideas/review_queue.html", {
        "user": get_current_user(request),
        "ideas": idea_list,
    })


@login_required_mongo
@role_required("admin")
@require_http_methods(["POST"])
def review_idea(request, idea_id):
    decision = request.POST.get("decision", "")
    note = (request.POST.get("decision_note") or "").strip()
    if decision not in ("accepted", "declined") or not note or len(note) > 3000:
        messages.error(request, "Choose a decision and provide a note (up to 3,000 characters).")
        return redirect("ideas:detail", idea_id=idea_id)
    idea = services.get_idea(idea_id)
    if not idea:
        messages.error(request, "Idea not found.")
        return redirect("ideas:review_queue")
    user = get_current_user(request)
    if not services.review_idea(idea_id, user["id"], decision, note):
        messages.error(request, "This idea is not ready for review or was already reviewed.")
        return redirect("ideas:detail", idea_id=idea_id)
    from accounts.notification_services import notify_roles
    notify_roles(
        ["student"],
        f"Idea {decision}",
        f'"{idea["title"]}" was {decision}. {note}',
        sender=user,
        kind="idea",
        target_url=f"/ideas/{idea_id}/",
    )
    messages.success(request, "Decision saved and all students have been notified.")
    return redirect("ideas:review_queue")
