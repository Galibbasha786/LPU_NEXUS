from django.urls import path

from . import views

app_name = "campus_ai"

urlpatterns = [
    path("", views.assistant_page, name="assistant"),
    path("ask/", views.ask_campus_question, name="ask"),
    path("triage-problem/", views.triage_problem, name="triage"),
]
