from django.urls import path

from . import views

app_name = 'live_news'

urlpatterns = [
    path('', views.live_news_page, name='page'),
    path('api/streams/', views.active_streams, name='active_streams'),
    path('api/start/', views.start_stream, name='start_stream'),
    path('api/<str:stream_id>/go-live/', views.go_live_stream, name='go_live_stream'),
    path('api/<str:stream_id>/token/', views.stream_token, name='stream_token'),
    path('api/<str:stream_id>/heartbeat/', views.stream_heartbeat, name='heartbeat'),
    path('api/<str:stream_id>/leave/', views.leave_stream, name='leave_stream'),
    path('api/<str:stream_id>/participants/', views.stream_participants, name='participants'),
    path(
        'api/<str:stream_id>/participants/<str:participant_user_id>/remove/',
        views.remove_participant,
        name='remove_participant',
    ),
    path('api/<str:stream_id>/comments/', views.stream_comments, name='comments'),
    path('api/<str:stream_id>/comments/moderate/', views.moderate_comments, name='moderate_comments'),
    path('api/<str:stream_id>/end/', views.end_stream, name='end_stream'),
]
