from django.urls import path

from . import views

app_name = 'campus_bulletins'

urlpatterns = [path('', views.bulletin_page, name='page')]
