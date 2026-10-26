from django.urls import path
from . import views

app_name = 'ideas'
urlpatterns = [
    path("", views.idea_list, name="list"),
    path("admin/review/", views.review_queue, name="review_queue"),
    path("admin/review/<str:idea_id>/", views.review_idea, name="review"),
    path("<str:idea_id>/", views.idea_detail, name="detail"),
    path("<str:idea_id>/vote/", views.cast_vote, name="vote"),
    path("<str:idea_id>/comment/", views.add_comment, name="comment"),
]