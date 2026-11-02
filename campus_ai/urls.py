from django.urls import path

from . import views

app_name = "campus_ai"

urlpatterns = [
    path("", views.assistant_page, name="assistant"),
    path("ask/", views.ask_campus_question, name="ask"),
    path("predict-problem-category/", views.predict_problem_category, name="predict_category"),
    path("triage-problem/", views.triage_problem, name="triage"),
]
