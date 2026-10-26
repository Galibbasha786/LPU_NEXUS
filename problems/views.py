from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.session import get_current_user, login_required_mongo, role_required
from core.mongo import users
from core.utils import serialize_doc, serialize_list, to_object_id

from . import services
from .constants import PROBLEM_CATEGORIES, PROBLEM_PRIORITIES, PROBLEM_STATUSES


@login_required_mongo
@role_required("student")
@require_http_methods(["GET", "POST"])
def report_problem(request):
    user = get_current_user(request)
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()
        category = request.POST.get("category", "")
        priority = request.POST.get("priority", "normal")
        location = (request.POST.get("location") or "").strip()
        if not title or not description or category not in dict(PROBLEM_CATEGORIES):
            messages.error(request, "Add a title, description, and valid category.")
        elif priority not in dict(PROBLEM_PRIORITIES):
            messages.error(request, "Choose a valid priority.")
        elif len(title) > 140 or len(description) > 5000 or len(location) > 200:
            messages.error(request, "Please shorten the title, description, or location.")
        else:
            problem = services.create_problem(
                user, title, description, category, location, priority,
            )
            from accounts.notification_services import notify_roles
            notify_roles(
                ["staff", "admin"],
                "New campus problem",
                f"{title} — reported by {user['full_name']}.",
                sender=user,
                kind="problem",
                target_url=f"/problems/queue/{problem['_id']}/",
            )
            messages.success(request, "Your problem is in the staff queue.")
            return redirect("problems:my_problems")
    return render(request, "problems/report_form.html", {
        "user": user,
        "categories": PROBLEM_CATEGORIES,
        "priorities": PROBLEM_PRIORITIES,
    })


@login_required_mongo
@role_required("student")
def my_problems(request):
    return render(request, "problems/my_problems.html", {
        "user": get_current_user(request),
        "problem_list": serialize_list(
            services.list_my_problems(request.session.get("lpu_user_id"))
        ),
    })


@login_required_mongo
@role_required("staff", "admin")
def problem_queue(request):
    status = request.GET.get("status", "")
    category = request.GET.get("category", "")
    search = (request.GET.get("q") or "").strip()
    if status not in dict(PROBLEM_STATUSES):
        status = ""
    if category not in dict(PROBLEM_CATEGORIES):
        category = ""
    return render(request, "problems/queue.html", {
        "user": get_current_user(request),
        "problem_list": serialize_list(services.list_problems(
            status=status or None, category=category or None,
            search=search or None,
        )),
        "stats": services.problem_stats(),
        "statuses": PROBLEM_STATUSES,
        "categories": PROBLEM_CATEGORIES,
        "current_status": status,
        "current_category": category,
        "search": search,
    })


@login_required_mongo
def problem_detail(request, problem_id):
    user = get_current_user(request)
    problem = services.get_problem(problem_id)
    if not problem:
        messages.error(request, "Problem report not found.")
        return redirect("accounts:dashboard")
    role = request.session.get("lpu_user_role")
    is_owner = str(problem.get("reported_by")) == user["id"]
    can_manage = role in ("staff", "admin")
    if not can_manage and not is_owner:
        messages.error(request, "You do not have access to this problem report.")
        return redirect("accounts:dashboard")
    assigned_staff = None
    if problem.get("assigned_to"):
        assigned_staff = users().find_one(
            {"_id": problem["assigned_to"]},
            {"full_name": 1, "email": 1},
        )
    return render(request, "problems/detail.html", {
        "user": user,
        "problem": serialize_doc(problem),
        "assigned_staff": serialize_doc(assigned_staff),
        "updates": serialize_list(services.get_problem_updates(problem_id)),
        "can_manage": can_manage,
        "statuses": PROBLEM_STATUSES,
        "priorities": PROBLEM_PRIORITIES,
        "staff_members": serialize_list(users().find(
            {"role": "staff", "active": {"$ne": False}},
            {"full_name": 1, "email": 1},
        ).sort("full_name", 1)),
    })


@login_required_mongo
@require_http_methods(["POST"])
def add_comment(request, problem_id):
    user = get_current_user(request)
    problem = services.get_problem(problem_id)
    if not problem:
        messages.error(request, "Problem report not found.")
        return redirect("accounts:dashboard")
    if (request.session.get("lpu_user_role") not in ("staff", "admin")
            and str(problem.get("reported_by")) != user["id"]):
        messages.error(request, "You do not have access to this problem report.")
        return redirect("accounts:dashboard")
    body = (request.POST.get("body") or "").strip()
    if not body or len(body) > 3000:
        messages.error(request, "Enter an update of up to 3,000 characters.")
    else:
        services.add_problem_comment(problem_id, user, body)
        if user["role"] in ("staff", "admin"):
            from accounts.notification_services import notify_user
            notify_user(
                problem["reported_by"],
                "New update on your problem report",
                f'A staff member added an update to "{problem["title"]}".',
                sender=user,
                kind="problem",
                target_url=f"/problems/queue/{problem_id}/",
            )
        messages.success(request, "Update added to the report.")
    return redirect("problems:detail", problem_id=problem_id)


@login_required_mongo
@role_required("staff", "admin")
@require_http_methods(["POST"])
def manage_problem(request, problem_id):
    problem = services.get_problem(problem_id)
    if not problem:
        messages.error(request, "Problem report not found.")
        return redirect("problems:queue")
    status = request.POST.get("status", "")
    priority = request.POST.get("priority", "")
    assignee = request.POST.get("assigned_to")
    if status not in dict(PROBLEM_STATUSES) or priority not in dict(PROBLEM_PRIORITIES):
        messages.error(request, "Choose a valid status and priority.")
        return redirect("problems:detail", problem_id=problem_id)
    if assignee and not users().find_one({
        "_id": to_object_id(assignee), "role": "staff", "active": {"$ne": False},
    }):
        messages.error(request, "Choose an active staff member.")
        return redirect("problems:detail", problem_id=problem_id)
    user = get_current_user(request)
    if not services.update_problem(problem_id, user, status, priority, assignee):
        messages.error(request, "The problem report could not be updated.")
        return redirect("problems:detail", problem_id=problem_id)
    if status != problem.get("status"):
        from accounts.notification_services import notify_user
        notify_user(
            problem["reported_by"],
            "Problem report updated",
            f'"{problem["title"]}" is now {status.replace("_", " ")}.',
            sender=user,
            kind="problem",
            target_url=f"/problems/queue/{problem_id}/",
        )
    messages.success(request, "Problem report updated.")
    return redirect("problems:detail", problem_id=problem_id)
