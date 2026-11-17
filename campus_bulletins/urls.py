from django.urls import path

from . import views

app_name = 'campus_bulletins'

urlpatterns = [
    path('', views.bulletin_page, name='page'),
    path('reader/', views.news_reader, name='reader'),
    path('ticker/', views.bulletin_ticker_json, name='ticker'),
]
