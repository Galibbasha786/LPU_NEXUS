from django.urls import path

from . import views

app_name = 'live_news'

urlpatterns = [
    path('', views.live_news_page, name='page'),
    path('api/streams/', views.active_streams, name='active_streams'),
    path('api/start/', views.start_stream, name='start_stream'),
    path('api/<str:stream_id>/token/', views.stream_token, name='stream_token'),
    path('api/<str:stream_id>/end/', views.end_stream, name='end_stream'),
]
