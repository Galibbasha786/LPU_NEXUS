from django.urls import path
from . import views

app_name = 'problems'
urlpatterns = [
    path("report/", views.report_problem, name="report"),
    path("my-reports/", views.my_problems, name="my_problems"),
    path("queue/", views.problem_queue, name="queue"),
    path("queue/<str:problem_id>/", views.problem_detail, name="detail"),
    path("queue/<str:problem_id>/update/", views.manage_problem, name="manage"),
    path("queue/<str:problem_id>/comment/", views.add_comment, name="comment"),
]